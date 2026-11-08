"""本地部署用的模型接入：兼容 OpenAI 接口（本地千问）、外部判定回放、按能力选择实现、离线盲打分。
用一个假的兼容 OpenAI 的服务检查请求格式和结果解析；不需要真实模型。sherpa-onnx 的测试在设置了模型目录时才跑。"""
import base64
import json
import os
import subprocess
import threading
import wave
from http.server import BaseHTTPRequestHandler, HTTPServer

import numpy as np
import pytest

from app.pipeline.detector_config import load_file
from app.pipeline.offline import SpecError, VideoSpec, compare_with_gold, load_spec, parse_time, report_md, run_video
from app.providers.base import Frame, ProviderError, SegmentHint
from app.providers.openai_compat import OpenAICompatLLM, OpenAICompatVision, OpenAICompatVoice, parse_json
from app.providers.registry import Unavailable, from_env
from app.providers.replay import ReplayLLM, ReplayVision
from scoring import parse_config
from tests.scoring.helpers import raw_config


class FakeServer:
    """记录收到的请求，按队列返回预设的回复内容。"""

    def __init__(self):
        self.requests, self.replies = [], []
        outer = self

        class H(BaseHTTPRequestHandler):
            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                outer.requests.append({"path": self.path, "body": body, "auth": self.headers.get("Authorization")})
                content = outer.replies.pop(0)
                data = json.dumps({"choices": [{"message": {"content": content}}]}).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(data)

            def log_message(self, *a):
                pass

        self.httpd = HTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        self.url = f"http://127.0.0.1:{self.httpd.server_port}/v1"

    def close(self):
        self.httpd.shutdown()


@pytest.fixture
def server(monkeypatch):
    for k in ("HTTP_PROXY", "http_proxy", "HTTPS_PROXY", "https_proxy"):
        monkeypatch.delenv(k, raising=False)
    s = FakeServer()
    yield s
    s.close()


def test_parse_json_strips_think_and_fences():
    assert parse_json("<think>先想想</think>\n```json\n{\"a\": 1}\n```") == {"a": 1}
    assert parse_json("结果如下：{\"a\": 2} 完") == {"a": 2}
    with pytest.raises(ProviderError):
        parse_json("没有 JSON")


def test_llm_request_uses_schema_temperature_and_key(server):
    server.replies.append('{"level": 7, "quote": "x", "reason": "r", "confidence": 0.8}')
    llm = OpenAICompatLLM(server.url, "qwen3-30b-a3b", api_key="k", extra={"chat_template_kwargs": {"enable_thinking": False}})
    out = llm.complete_json("s1_need", "sys", "user", {"type": "object"}, temperature=0.0, payload={})
    req = server.requests[0]
    assert out["level"] == 7 and req["path"] == "/v1/chat/completions" and req["auth"] == "Bearer k"
    b = req["body"]
    assert b["model"] == "qwen3-30b-a3b" and b["temperature"] == 0.0 and b["chat_template_kwargs"] == {"enable_thinking": False}
    assert b["response_format"]["type"] == "json_schema" and b["response_format"]["json_schema"]["name"] == "s1_need"
    assert [m["role"] for m in b["messages"]] == ["system", "user"]


def test_llm_unreachable_is_provider_error():
    with pytest.raises(ProviderError, match="连不上"):
        OpenAICompatLLM("http://127.0.0.1:9/v1", "m", timeout_s=2).complete_json("t", "s", "u", {}, temperature=0, payload={})


def _jpg(tmp_path, n):
    paths = []
    for i in range(n):
        p = tmp_path / f"{i}.jpg"
        p.write_bytes(b"\xff\xd8fake-jpeg-%d" % i)
        paths.append(Frame(str(p), i * 1000))
    return paths


def test_vision_attire_and_frame_batches(server, tmp_path):
    frames = _jpg(tmp_path, 10)
    v = OpenAICompatVision(server.url, "qwen3-vl-8b", dress_code="深色正装", batch=8)
    server.replies.append(json.dumps({"attire": {"flag": True, "reason": "穿运动背心", "confidence": 0.8},
                                      "hairstyle": {"flag": False, "reason": "整齐", "confidence": 0.9}}))
    found = v.analyze("attire", frames, {})
    assert [(f.label, f.judgment) for f in found] == [("attire", "count"), ("hairstyle", "not_count")]
    parts = server.requests[-1]["body"]["messages"][1]["content"]
    imgs = [p for p in parts if p["type"] == "image_url"]
    assert 1 <= len(imgs) <= 6 and imgs[0]["image_url"]["url"].startswith("data:image/jpeg;base64,")
    assert "深色正装" in parts[0]["text"] and "不评价相貌" in parts[0]["text"]
    server.replies += [json.dumps({"frames": [{"index": i, "flag": i == 3, "label": "touch_face"} for i in range(8)]}),
                       json.dumps({"frames": [{"index": i, "flag": False} for i in range(2)]})]
    found = v.analyze("fidget", frames, {})
    assert [(f.at_ms, f.label, f.judgment) for f in found] == [(3000, "touch_face", "count")]
    server.replies.append(json.dumps({"frames": [{"index": 0, "flag": False}]}))  # 漏判帧 → 失败，不当作没有小动作
    with pytest.raises(ProviderError, match="漏判"):
        v.analyze("fidget", frames[:2], {})


def _wav(path, seconds, sr=16000):
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1), w.setsampwidth(2), w.setframerate(sr)
        w.writeframes((np.sin(np.arange(int(seconds * sr)) / 10) * 8000).astype(np.int16).tobytes())
    return str(path)


def test_voice_clips_median_and_range(server, tmp_path):
    audio = _wav(tmp_path / "a.wav", 12)
    voice = OpenAICompatVoice(server.url, "qwen3-omni", clips=3, clip_s=4)
    server.replies += [json.dumps({"score": s, "reason": f"r{s}", "confidence": 0.7}) for s in (3, 5, 4)]
    r = voice.rate(audio, "intonation", criterion="语调（抑扬顿挫-根据主观打分）", max_score=5, context={"pitch_range_st": 6})
    assert r.score == 4 and "各段得分 [3, 5, 4]" in r.reason
    parts = server.requests[0]["body"]["messages"][0]["content"]
    clip = base64.b64decode(parts[0]["input_audio"]["data"])
    with wave.open(__import__("io").BytesIO(clip)) as w:
        assert w.getnframes() == 4 * 16000
    server.replies.append(json.dumps({"score": 6}))
    with pytest.raises(ProviderError, match="0–5"):
        OpenAICompatVoice(server.url, "m", clips=1, clip_s=4).rate(audio, "timbre", criterion="", max_score=5, context={})


def test_replay_pending_then_answer(tmp_path):
    llm = ReplayLLM(str(tmp_path), judge="tester")
    payload = {"transcript": "abc", "_round": 1}
    with pytest.raises(ProviderError, match="待外部判定"):
        llm.complete_json("s1_need", "sys", "指令\n\n输入：{...}", {"type": "object"}, temperature=0, payload=payload)
    (pending,) = (tmp_path / "pending").iterdir()
    req = json.loads(pending.read_text())
    assert req["task"] == "s1_need" and req["instruction"] == "指令" and "_round" not in req["payload"]
    (tmp_path / "answers" / pending.name).write_text(json.dumps({"level": 5}))
    out = llm.complete_json("s1_need", "sys", "u", {}, temperature=0, payload={**payload, "_round": 2})  # 换轮次答案不变
    assert out == {"level": 5} and not pending.exists() and llm.model_version == "file:tester"
    vis = ReplayVision(str(tmp_path), {"attire"})
    with pytest.raises(ProviderError, match="未配置"):
        vis.analyze("fidget", _jpg(tmp_path, 1), {})


def test_registry_config_mode(tmp_path):
    p = from_env({"APP_LLM": "replay", "APP_REPLAY_DIR": str(tmp_path), "APP_VOICE": "mock"})
    assert isinstance(p.asr, Unavailable) and p.manifest()["llm"] == "replay-llm@file:external"
    with pytest.raises(ProviderError, match="ASR 未配置"):
        p.asr.transcribe("x.wav", disfluency_removal=False, word_timestamps=True, hint=SegmentHint("main"))
    with pytest.raises(RuntimeError, match="不支持"):
        from_env({"APP_LLM": "gpt"})
    with pytest.raises(RuntimeError, match="APP_LLM_BASE_URL"):
        from_env({"APP_LLM": "openai"})
    p = from_env({"APP_LLM": "openai", "APP_LLM_MODEL": "qwen3", "APP_OPENAI_BASE_URL": "http://h:1/v1",
                  "APP_VISION": "openai", "APP_VLM_MODEL": "qwen3-vl", "APP_VLM_BASE_URL": "http://h:2/v1"})
    assert (p.llm.base_url, p.vision.base_url) == ("http://h:1/v1", "http://h:2/v1")


@pytest.mark.parametrize("v,ms", [("01:30", 90_000), ("1:02:03.5", 3_723_500), (1500, 1500), ("00:00.25", 250)])
def test_parse_time(v, ms):
    assert parse_time(v) == ms


def test_parse_time_rejects_garbage():
    with pytest.raises(SpecError):
        parse_time("90 秒")


@pytest.fixture(scope="module")
def short_video(tmp_path_factory):
    d = tmp_path_factory.mktemp("v")
    p = d / "v.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc=size=160x120:rate=5:duration=40", "-f", "lavfi",
                    "-i", "sine=frequency=220:duration=40", "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
                    "-c:a", "aac", "-shortest", str(p)], check=True)
    return p


def test_offline_run_marks_unavailable_items_unscored(short_video, tmp_path):
    """Mock 能力 + 未配置的能力：未配置或缺输入的条目标“未评”并写原因，不当 0 分；维度不出分。"""
    from app.providers import mock
    from app.providers.base import Providers

    spec_file = tmp_path / "spec.json"
    spec_file.write_text(json.dumps({
        "name": "测试", "video": str(short_video), "main": {"start": "00:01", "end": "00:31"},
        "objections": [{"at": "00:10", "text": "孩子有医保了，还需要买吗？"}],
        "card": {"fixed_script": {"version": "s1", "text": "这款产品就三个好。"},
                 "s2_calibration": {"version": "c1", "fixed_script_version": "s1", "status": "draft"}},
    }, ensure_ascii=False))
    spec = load_spec(spec_file)
    prov = Providers(mock.MockASR(), Unavailable("SPEECH_EVAL"), mock.MockLLM(), mock.MockVision(), mock.MockLaugh(), Unavailable("VOICE"))
    cfg, (dcfg, _) = parse_config(raw_config()), load_file()
    out = run_video(spec, prov, cfg, dcfg, tmp_path / "work")
    det = out["detectors"]
    assert det["P3"]["status"] == "skipped" and "朗读" in det["P3"]["reason"]
    assert det["S3"]["status"] == "skipped" and "1 条" in det["S3"]["reason"]
    assert det["P5"]["status"] == "failed" and "VOICE 未配置" in det["P5"]["reason"]
    assert det["P9"]["status"] == "not_applicable" and det["S2"]["status"] == "completed"
    items = {i["item_id"]: i for i in out["result"]["items"]}
    assert items["P5"]["status"] == "missing_evidence" and items["P5"]["score"] is None
    assert items["S2"]["status"] == "scored" and out["result"]["total_grade"] is None
    assert out["segments"][0] == {"segment": "main", "start_ms": 1000, "end_ms": 31000}
    assert all(e["start_ms"] is None or 1000 <= e["start_ms"] <= 31000 for e in out["evidence"])
    md = report_md(out)
    assert "**未评**" in md and "VOICE 未配置" in md and "S2 产品讲解 | 50 |" in md
    rep = compare_with_gold([out], {"测试": {"S2": items["S2"]["score"], "P5": 3}}, cfg)
    assert rep["items"]["S2"]["agree_rate"] == 1.0 and rep["items"]["P5"]["ai_missing"] == 1


def test_offline_spec_rejects_objection_outside_main(short_video, tmp_path):
    from app.providers import mock
    from app.providers.base import Providers

    spec = VideoSpec(name="x", video=short_video, main_start_ms=0, main_end_ms=20_000,
                     objections=[{"objection_id": "o1", "text": "t", "at_ms": 25_000, "answer_points": []}])
    prov = Providers(mock.MockASR(), mock.MockSpeechEval(), mock.MockLLM(), mock.MockVision(), mock.MockLaugh(), mock.MockVoice())
    with pytest.raises(SpecError, match="主体段内"):
        run_video(spec, prov, parse_config(raw_config()), load_file()[0], tmp_path)


@pytest.mark.skipif(not os.environ.get("APP_SENSEVOICE_DIR"), reason="未设置 APP_SENSEVOICE_DIR（sherpa-onnx 模型目录）")
def test_sherpa_sensevoice_real_model():
    from app.providers.sherpa import SherpaSenseVoiceASR

    d = os.environ["APP_SENSEVOICE_DIR"]
    asr = SherpaSenseVoiceASR(d, os.environ["APP_VAD_MODEL"])
    wav = os.path.join(d, "test_wavs", "zh.wav")
    tr = asr.transcribe(wav, disfluency_removal=False, word_timestamps=True, hint=SegmentHint("main"))
    assert tr.params["disfluency_removal"] is False and "开饭时间" in tr.text
    assert all(a.start_ms <= b.start_ms for a, b in zip(tr.words, tr.words[1:]))

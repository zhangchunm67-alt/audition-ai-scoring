"""离线盲打分（金标准到位前，用真实录像检验流水线和模型）。

用法（在仓库根目录）：
  APP_PROVIDERS=config APP_ASR=sherpa ... .venv/bin/python scripts/blind_score.py specs/*.json --out var/blind

每个视频一份说明文件（JSON，模板见 docs/blind-test/spec.example.json）。
每条视频输出 <out>/<name>/result.json（完整结果：逐字稿、证据、各条目得分）和 report.md（可读报告）。
用外部判定回放（APP_LLM=replay）时，待判定的请求写在 APP_REPLAY_DIR/pending/，作答后重跑本脚本即可。
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "backend")]

from app.pipeline.detector_config import load_file  # noqa: E402
from app.pipeline.offline import load_spec, report_md, run_video  # noqa: E402
from app.providers.registry import get_providers  # noqa: E402
from scoring import load_config  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description="离线盲打分")
    ap.add_argument("specs", nargs="+", help="视频说明文件（JSON）")
    ap.add_argument("--out", default="var/blind", help="输出目录")
    ap.add_argument("--rubric", default=str(ROOT / "config/rubric/rubric-v0.3.yaml"))
    ap.add_argument("--work", default="var/blind-work", help="中间文件（音频、抽帧）目录")
    args = ap.parse_args()
    cfg = load_config(args.rubric)
    dcfg, _ = load_file()
    providers = get_providers()
    print("模型：", json.dumps(providers.manifest(), ensure_ascii=False))
    summary = []
    for sp in args.specs:
        spec = load_spec(sp)
        out = run_video(spec, providers, cfg, dcfg, Path(args.work) / spec.name)
        d = Path(args.out) / spec.name
        d.mkdir(parents=True, exist_ok=True)
        (d / "result.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), "utf-8")
        (d / "report.md").write_text(report_md(out), "utf-8")
        st = out["detectors"]
        done = sum(1 for v in st.values() if v["status"] == "completed")
        summary.append(f"{spec.name}: 完成 {done} 项，未评 {sum(1 for v in st.values() if v['status'] in ('failed', 'skipped'))} 项 → {d / 'report.md'}")
        print(summary[-1])
    pending = Path(os.environ.get("APP_REPLAY_DIR", "var/replay")) / "pending"
    if pending.exists() and any(pending.iterdir()):
        print(f"还有 {len(list(pending.iterdir()))} 个请求待外部判定：{pending}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

# 离线盲打分（金标准到位前）

金标准还没出来时，先用真实录像跑通整条流水线：语音识别、分段、检测器、引用定位、计分。等业务同事给出人工分，再用同一份结果做对比。

- 只跑一轮，不跑临界三轮，不出结论标签，不写数据库。
- 缺输入或缺能力的条目标为**未评**，并写明原因，绝不当作 0 分或满分。只要有条目未评，对应维度和总档位就不出分。

## 1. 每条视频写一份说明文件

模板：[`spec.example.json`](spec.example.json)。各字段的写法：

| 字段 | 说明 | 不填的后果 |
|---|---|---|
| `main` | 主体段起止（`mm:ss` 或 `hh:mm:ss`），应为 10 分钟。直播回放请挑一段完整讲品的 10 分钟 | 默认取视频开头 10 分钟；不足 10 分钟时，P2 按时长换算次数 |
| `reading` | 朗读段起止和朗读稿原文 | P3 未评 |
| `objections` | 观众异议：出现时间（相对主体段起点）、原文、答案要点。评分表要求 4 条 | 没有异议：S3、O4 未评；有异议但不是 4 条：S3 未评 |
| `props_available` | 画面里有没有贴片或 KT 板 | 默认没有，P9 不适用 |
| `card.fixed_script` + `card.s2_calibration` | 产品固定话术，加一条草稿校准记录（盲测时写 `blind-uncalibrated`） | S2 未评 |
| `card` 其他 | 术语白话对照（O1）、针对性卖点（O2）、场景（O3）、关键数字（L5） | 对应条目只能按通用标准判断 |

## 2. 运行

先装好依赖：

```bash
.venv/bin/pip install -e ".[local]"
```

再下载语音模型：

```bash
./scripts/download_models.sh
```

用 `APP_PROVIDERS=config` 逐项选择每种能力的实现，没选的项为“未配置”：

| 能力 | 变量 | 可选 |
|---|---|---|
| 语音识别 | `APP_ASR` | `sherpa`（本地 SenseVoice）、`mock` |
| 笑声候选 | `APP_LAUGH` | `sherpa`（本地 CED）、`mock` |
| 大模型判断 | `APP_LLM` | `openai`（本地千问或任何兼容 OpenAI 的服务）、`replay`（外部判定回放）、`mock` |
| 视觉（P1、P8、P9） | `APP_VISION` | `openai`、`replay`、`mock` |
| 声音评价（P5–P7） | `APP_VOICE` | `openai`（能听音频的千问 Omni）、`mock` |
| 普通话评测（P3） | `APP_SPEECH_EVAL` | 真实服务尚未接入，盲测里 P3 未评 |

### A. 在 Mac Studio 上用本地千问

模型要直接在 macOS 上运行，用 llama.cpp 的 `llama-server`，每个模型起一个进程、占一个端口；Docker 里用不了 Apple GPU。具体的模型仓库名以 llama.cpp 多模态文档和千问官方的 GGUF 发布为准。下面是一种配法：

```bash
llama-server -hf <千问文本模型 GGUF，如 Qwen3 30B-A3B Q4_K_M> --port 8081 --jinja -c 32768
```

```bash
llama-server -hf <千问视觉模型 GGUF，如 Qwen3-VL 8B> --port 8082 --jinja -c 16384
```

```bash
llama-server -hf <千问 Omni GGUF，如 Qwen3-Omni 30B-A3B> --port 8083 --jinja -c 32768
```

然后在仓库目录运行：

```bash
APP_PROVIDERS=config APP_ASR=sherpa APP_LAUGH=sherpa APP_LLM=openai APP_VISION=openai APP_VOICE=openai \
APP_SENSEVOICE_DIR=models/sherpa-onnx-sense-voice-zh-en-ja-ko-yue-2024-07-17 APP_VAD_MODEL=models/silero_vad.onnx \
APP_CED_DIR=models/sherpa-onnx-ced-mini-audio-tagging-2024-04-19 \
APP_LLM_BASE_URL=http://127.0.0.1:8081/v1 APP_LLM_MODEL=qwen-text \
APP_VLM_BASE_URL=http://127.0.0.1:8082/v1 APP_VLM_MODEL=qwen-vl \
APP_OMNI_BASE_URL=http://127.0.0.1:8083/v1 APP_OMNI_MODEL=qwen-omni \
APP_OPENAI_EXTRA='{"chat_template_kwargs": {"enable_thinking": false}}' \
.venv/bin/python scripts/blind_score.py specs/*.json --out var/blind
```

`APP_OPENAI_EXTRA` 会原样并入每个请求，这里用来关掉千问的“思考”输出。着装要求定下来以后（P-P1-DRESS），用 `APP_DRESS_CODE="……"` 传给视觉模型。声音评价默认每条截 3 段、每段 45 秒，分别打分取中位数，可用 `APP_VOICE_CLIPS`、`APP_VOICE_CLIP_S` 调整。

### B. 外部判定回放（还没部署本地千问时）

`APP_LLM=replay`、`APP_VISION=replay` 时，每个判断请求会写到 `APP_REPLAY_DIR/pending/`，里面有提示词、输出结构和输入。由人或另一个模型按结构作答，写入 `answers/` 下的同名文件，再重跑脚本。

回放出来的答案和真实模型一样，要经过输出结构校验和“引用必须能在原文找到”的检查。视觉回放默认只开 `attire,prop_pointing`，由 `APP_REPLAY_VISION_TASKS` 控制；P8 每条要看约 600 帧，回放时一般不开。

## 3. 输出

每条视频输出到 `<out>/<name>/`：

- `report.md`：维度、各条目得分或未评原因、声音测量（参考，不计分）、全部证据（时间、原句、理由）、主体段逐字稿；
- `result.json`：完整结果，包括逐字时间戳、检测器状态和计分明细。

## 4. 金标准到了以后

按 [`gold.example.csv`](gold.example.csv) 填人工分（列：视频、条目、人工分），然后运行：

```bash
.venv/bin/python scripts/compare_gold.py --results var/blind --gold gold.csv
```

输出以下内容：

- 各条目一致率：相差不超过该条目满分的 10%（口径 I28）；
- 平均绝对误差；
- AI 未评的条数；
- 维度档位一致率：相差不超过 1 档；
- 全部分歧明细。

## 已知限制（2026-11-08 实测）

- **SenseVoice 可能吞掉重复词。** 合成语音里“这个这个”识别成了“这这个”，这会直接影响 P7 的重复和卡壳统计。其他口头禅（那么、一个、对不对、的情况下、这边给你、懂了吗、什么呀）在同一段里都保留了。真实录像上必须再核对。
- **SenseVoice 不输出逐字置信度**，所以语音识别本身不会触发低置信标记。
- **笑声会被转写成“啊啊啊”。** P2 的口头禅词表不含“啊”（Q7 待确认），所以不会被重复扣分；P10 由笑声检测和大模型判断。
- **视频含候选人的人脸、声音和个人信息。** 拿去做测试前，请确认已取得本人同意；发给外部服务前，要确认同意书的范围覆盖。

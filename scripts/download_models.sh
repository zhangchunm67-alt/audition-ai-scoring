#!/usr/bin/env bash
# 下载本地语音模型（sherpa-onnx 格式，CPU 运行，Linux / macOS 通用）到 models/（或第一个参数指定的目录）：
#   SenseVoice（语音识别）、silero VAD（切段）、CED mini（音频事件，用于笑声候选）。
# 来源：https://github.com/k2-fsa/sherpa-onnx/releases 。下载约 1.3 GB。
set -euo pipefail
DIR="${1:-$(cd "$(dirname "$0")/.." && pwd)/models}"
BASE=https://github.com/k2-fsa/sherpa-onnx/releases/download
mkdir -p "$DIR" && cd "$DIR"
get_tar() {  # $1 = 发布目录，$2 = 包名
  if [ -d "$2" ]; then echo "已存在：$2"; return; fi
  curl -fL --retry 3 -o "$2.tar.bz2" "$BASE/$1/$2.tar.bz2" && tar xjf "$2.tar.bz2" && rm "$2.tar.bz2"
}
get_tar asr-models sherpa-onnx-sense-voice-zh-en-ja-ko-yue-2024-07-17
get_tar audio-tagging-models sherpa-onnx-ced-mini-audio-tagging-2024-04-19
[ -f silero_vad.onnx ] || curl -fL --retry 3 -o silero_vad.onnx "$BASE/asr-models/silero_vad.onnx"
cat <<EOT
已下载到 ${DIR}。在 .env 里加（容器内路径为 /models/...；直接在本机跑脚本时用本机路径）：
APP_ASR=sherpa
APP_SENSEVOICE_DIR=/models/sherpa-onnx-sense-voice-zh-en-ja-ko-yue-2024-07-17
APP_VAD_MODEL=/models/silero_vad.onnx
APP_LAUGH=sherpa
APP_CED_DIR=/models/sherpa-onnx-ced-mini-audio-tagging-2024-04-19
EOT

#!/usr/bin/env bash
# 启动一个本地模型服务（llama.cpp 的 llama-server），由 launchd 开机自启：scripts/macos/model_server.sh llm|vlm|omni
# 配置在部署目录的 models.env（chmod 600，不进 git，和 .env 一样存进密码管理器）：
#   LLAMA_SERVER=/opt/homebrew/bin/llama-server
#   MODEL_API_KEY=<随机串，与 .env 里的 APP_OPENAI_API_KEY 相同>
#   LLM_MODEL=<文本模型 GGUF 路径或 -hf 仓库名>  LLM_PORT=8081  LLM_CTX=32768
#   VLM_MODEL=…  VLM_PORT=8082  VLM_CTX=16384
#   OMNI_MODEL=…  OMNI_PORT=8083  OMNI_CTX=32768
# 安全：只监听本机回环地址 127.0.0.1，并要求 API key。容器经 host.docker.internal 访问本机回环地址
# （Docker Desktop 和 Colima 都支持，部署后按 README 检查清单验证）。不要改成 0.0.0.0：那样内网任何人都能调用模型。
set -euo pipefail
cd "$(dirname "$0")/../.."
[ -f models.env ] || { echo "缺少 models.env" >&2; exit 2; }
# shellcheck disable=SC1091
set -a; . ./models.env; set +a
name=$(echo "${1:?用法：$0 llm|vlm|omni}" | tr '[:lower:]' '[:upper:]')
model_var="${name}_MODEL"; port_var="${name}_PORT"; ctx_var="${name}_CTX"
model=${!model_var:?models.env 里没有 ${name}_MODEL}
port=${!port_var:?models.env 里没有 ${name}_PORT}
ctx=${!ctx_var:-16384}
[ -n "${MODEL_API_KEY:-}" ] || { echo "models.env 里没有 MODEL_API_KEY" >&2; exit 2; }
src=(-m "$model"); [ -f "$model" ] || src=(-hf "$model")
exec "${LLAMA_SERVER:-llama-server}" "${src[@]}" --host "${MODEL_HOST:-127.0.0.1}" --port "$port" --api-key "$MODEL_API_KEY" \
  --jinja -c "$ctx" --no-webui

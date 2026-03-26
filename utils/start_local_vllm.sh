#!/usr/bin/env bash
set -euo pipefail

#//modify Reusable local vLLM launcher for OpenPipe/Qwen3-14B-Instruct
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV_PATH="${ROOT_DIR}/.venv"
MODEL_PATH="${ROOT_DIR}/cfg/llm_client/local/OpenPipe__Qwen3-14B-Instruct"
SERVED_MODEL_NAME="qwen3-14b-instruct-local"
HOST="127.0.0.1"
PORT="8000"
DTYPE="bfloat16"
GPU_MEMORY_UTILIZATION="0.75"
MAX_MODEL_LEN="8192"

source "${VENV_PATH}/bin/activate"
export LOCAL_LLM_API_KEY="${LOCAL_LLM_API_KEY:-EMPTY}"

exec vllm serve "${MODEL_PATH}" \
  --served-model-name "${SERVED_MODEL_NAME}" \
  --host "${HOST}" \
  --port "${PORT}" \
  --dtype "${DTYPE}" \
  --gpu-memory-utilization "${GPU_MEMORY_UTILIZATION}" \
  --max-model-len "${MAX_MODEL_LEN}"

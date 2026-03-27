# Utils README

## API 方式运行

对应配置：`cfg/llm_client/openai.yaml`

```bash
source .venv/bin/activate
export OPENAI_API_KEY=<your_openai_api_key>
python main.py problem=tsp_gls llm_client=openai llm_client.model=gpt-3.5-turbo init_pop_size=1 pop_size=1 max_fe=2 timeout=300
```

如果要换模型，只改 `llm_client.model`，例如：

```bash
source .venv/bin/activate
export OPENAI_API_KEY=<your_openai_api_key>
python main.py problem=tsp_gls llm_client=openai llm_client.model=gpt-4o-mini init_pop_size=1 pop_size=1 max_fe=2 timeout=300
```

## 本地模型方式运行

对应配置：`cfg/llm_client/local.yaml`

先需要拉取模型，并放到 `reevo_VRP/cfg/llm_client/local` 目录下。

先启动本地 vLLM 服务：

```bash
./utils/start_local_vllm.sh
```

再在另一个终端运行：

```bash
source .venv/bin/activate
export LOCAL_LLM_API_KEY=EMPTY
python main.py problem=tsp_gls llm_client=local init_pop_size=1 pop_size=1 max_fe=2 timeout=300
```

如果运行 `cvrp_hgs`，推荐直接把所有 Hydra 参数写在同一行，尤其是 `timeout=...`，不要单独换行成另一条 shell 命令。

`cvrp_hgs` 最小冒烟：

```bash
source .venv/bin/activate
export LOCAL_LLM_API_KEY=EMPTY
python main.py problem=cvrp_hgs llm_client=local init_pop_size=1 pop_size=1 max_fe=2 timeout=1800
```

`cvrp_hgs` 正式演化：

```bash
source .venv/bin/activate
export LOCAL_LLM_API_KEY=EMPTY
python main.py problem=cvrp_hgs llm_client=local init_pop_size=16 pop_size=16 max_fe=257 timeout=7200
```

本地 vLLM 启动脚本位置：

```bash
utils/start_local_vllm.sh
```

脚本内当前关键参数：

```bash
MODEL_PATH="${ROOT_DIR}/cfg/llm_client/local/OpenPipe__Qwen3-14B-Instruct"
SERVED_MODEL_NAME="qwen3-14b-instruct-local"
PORT="8000"
GPU_MEMORY_UTILIZATION="0.75"
MAX_MODEL_LEN="8192"
```

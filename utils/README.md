# Utils README

## 从 0 到能跑 `cvrp_hgs`

除了 `uv sync` 之外，还需要：
- 系统里有 `c++` 和 `pkg-config`
- 如果用本地模型，模型目录已放到 `cfg/llm_client/local/OpenPipe__Qwen3-14B-Instruct`

步骤：

```bash
uv sync
source .venv/bin/activate
export LOCAL_LLM_API_KEY=EMPTY
./utils/start_local_vllm.sh
```

另一个终端：

```bash
source .venv/bin/activate
export LOCAL_LLM_API_KEY=EMPTY
python main.py problem=cvrp_hgs llm_client=local init_pop_size=1 pop_size=1 max_fe=2 timeout=1800
```

说明：
- `uv sync` 会创建 `.venv` 并安装 Python 依赖
- `utils/pyvrp_rep` 不需要手动预编译，`cvrp_hgs` 评测时会自动 build
- `llm_client=local` 仍然需要先启动 `./utils/start_local_vllm.sh`

## `cvrp_hgs`

最小冒烟：

```bash
source .venv/bin/activate
export LOCAL_LLM_API_KEY=EMPTY
python main.py problem=cvrp_hgs llm_client=local init_pop_size=1 pop_size=1 max_fe=2 timeout=1800
```

正式演化：

```bash
source .venv/bin/activate
export LOCAL_LLM_API_KEY=EMPTY
python main.py problem=cvrp_hgs llm_client=local
```

## 其他本地模型运行

先启动：

```bash
./utils/start_local_vllm.sh
```

再运行：

```bash
source .venv/bin/activate
export LOCAL_LLM_API_KEY=EMPTY
python main.py problem=tsp_gls llm_client=local init_pop_size=1 pop_size=1 max_fe=2 timeout=300
```

## API 方式运行

```bash
source .venv/bin/activate
export OPENAI_API_KEY=<your_openai_api_key>
python main.py problem=tsp_gls llm_client=openai llm_client.model=gpt-4o-mini init_pop_size=1 pop_size=1 max_fe=2 timeout=300
```

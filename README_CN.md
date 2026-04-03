# EvoHGS
Evolving Hybrid Genetic Search via LLMs for Multi-Task Vehicle Routing

## 数据与节点规模

数据生成、`.vrp` 基线求解、`pyvrp`/`OR-Tools` 参考解生成，见 [data/README.md](/home/zguo/Coding/reevo/data/README.md)。

当前仓库里已经生成并使用的节点规模有：
- `101`
- `201`
- `401`

对应关系：
- `101` = `100` 个客户 + `1` 个 depot
- `201` = `200` 个客户 + `1` 个 depot
- `401` = `400` 个客户 + `1` 个 depot

## 从 0 到能跑 `cvrp_hgs`

除了 `uv sync` 之外，还需要：
- 系统里有 `c++` 和 `pkg-config`
- 如果用本地模型，先从 Hugging Face 下载 `OpenPipe/Qwen3-14B-Instruct`：[(点击)这里](https://huggingface.co/OpenPipe/Qwen3-14B-Instruct)
- 下载后把模型放到 `cfg/llm_client/local/OpenPipe__Qwen3-14B-Instruct`

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
- `problem=cvrp_hgs` 只是示例，这里可以切换为下面任一个 HGS 问题名
- Hugging Face 模型页：[(点击)这里](https://huggingface.co/OpenPipe/Qwen3-14B-Instruct)

## 当前已添加的 HGS 问题

- `cvrp_hgs`
- `ovrp_hgs`
- `ovrptw_hgs`
- `vrpb_hgs`
- `vrpl_hgs`
- `vrptw_hgs`

通用写法：

```bash
source .venv/bin/activate
export LOCAL_LLM_API_KEY=EMPTY
python main.py problem=<problem_name> llm_client=local
```

把 `<problem_name>` 替换成上面任一个即可。

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

## `vrptw_hgs`

最小冒烟：

```bash
source .venv/bin/activate
export LOCAL_LLM_API_KEY=EMPTY
python main.py problem=vrptw_hgs llm_client=local llm_client.temperature=0.2 init_pop_size=4 pop_size=4 max_fe=5 timeout=1800
```

直接验证当前根目录 `selective_route_exchange.cpp`：

```bash
source .venv/bin/activate
python problems/vrptw_hgs/eval.py -1 . train selective_route_exchange.cpp
```

说明：
- `vrptw_hgs` 会读取 `cfg/problem/vrptw_hgs.yaml`
- 数据目录配置为 `data/generated/VRPTW/101` 和 `data/opt/VRPTW/101`
- `utils/pyvrp_rep` 不需要手动预编译，评测时会自动增量 build

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

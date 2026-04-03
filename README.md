# EvoHGS
Evolving Hybrid Genetic Search via LLMs for Multi-Task Vehicle Routing

## Data and Instance Sizes

For data generation, baseline `.vrp` solving, and `pyvrp`/`OR-Tools` reference-solution generation, see [data/README.md](/home/zguo/Coding/reevo/data/README.md).

The instance sizes currently generated and used in this repository are:
- `101`
- `201`
- `401`

Mapping:
- `101` = `100` customers + `1` depot
- `201` = `200` customers + `1` depot
- `401` = `400` customers + `1` depot

## Running `cvrp_hgs` from Scratch

In addition to `uv sync`, you also need:
- `c++` and `pkg-config` available on the system
- If you use the local model, download `OpenPipe/Qwen3-14B-Instruct` from Hugging Face first: [link](https://huggingface.co/OpenPipe/Qwen3-14B-Instruct)
- After downloading, place the model under `cfg/llm_client/local/OpenPipe__Qwen3-14B-Instruct`

Steps:

```bash
uv sync
source .venv/bin/activate
export LOCAL_LLM_API_KEY=EMPTY
./utils/start_local_vllm.sh
```

In another terminal:

```bash
source .venv/bin/activate
export LOCAL_LLM_API_KEY=EMPTY
python main.py problem=cvrp_hgs llm_client=local init_pop_size=1 pop_size=1 max_fe=2 timeout=1800
```

Notes:
- `uv sync` creates `.venv` and installs the Python dependencies
- `utils/pyvrp_rep` does not need manual precompilation; `cvrp_hgs` builds it automatically during evaluation
- `llm_client=local` still requires `./utils/start_local_vllm.sh` to be running first
- `problem=cvrp_hgs` is only an example; you can switch it to any HGS problem listed below
- Hugging Face model page: [link](https://huggingface.co/OpenPipe/Qwen3-14B-Instruct)

## Currently Added HGS Problems

- `cvrp_hgs`
- `ovrp_hgs`
- `ovrptw_hgs`
- `vrpb_hgs`
- `vrpl_hgs`
- `vrptw_hgs`

General form:

```bash
source .venv/bin/activate
export LOCAL_LLM_API_KEY=EMPTY
python main.py problem=<problem_name> llm_client=local
```

Replace `<problem_name>` with any of the problem names above.

## `cvrp_hgs`

Minimal smoke test:

```bash
source .venv/bin/activate
export LOCAL_LLM_API_KEY=EMPTY
python main.py problem=cvrp_hgs llm_client=local init_pop_size=1 pop_size=1 max_fe=2 timeout=1800
```

Full evolution run:

```bash
source .venv/bin/activate
export LOCAL_LLM_API_KEY=EMPTY
python main.py problem=cvrp_hgs llm_client=local
```

## `vrptw_hgs`

Minimal smoke test:

```bash
source .venv/bin/activate
export LOCAL_LLM_API_KEY=EMPTY
python main.py problem=vrptw_hgs llm_client=local llm_client.temperature=0.2 init_pop_size=4 pop_size=4 max_fe=5 timeout=1800
```

Validate the current root-level `selective_route_exchange.cpp` directly:

```bash
source .venv/bin/activate
python problems/vrptw_hgs/eval.py -1 . train selective_route_exchange.cpp
```

Notes:
- `vrptw_hgs` reads `cfg/problem/vrptw_hgs.yaml`
- The data directories are configured as `data/generated/VRPTW/101` and `data/opt/VRPTW/101`
- `utils/pyvrp_rep` does not need manual precompilation; evaluation triggers incremental builds automatically

## Running Other Local-Model Tasks

Start the server first:

```bash
./utils/start_local_vllm.sh
```

Then run:

```bash
source .venv/bin/activate
export LOCAL_LLM_API_KEY=EMPTY
python main.py problem=tsp_gls llm_client=local init_pop_size=1 pop_size=1 max_fe=2 timeout=300
```

## Running via API

```bash
source .venv/bin/activate
export OPENAI_API_KEY=<your_openai_api_key>
python main.py problem=tsp_gls llm_client=openai llm_client.model=gpt-4o-mini init_pop_size=1 pop_size=1 max_fe=2 timeout=300
```

# Data Workflow

## Generate `.vrp`

默认输出目录：

- `data/generated/<PROBLEM>/<节点数>/n101-0001.vrp`

其中：

- `problem_size=100` -> `101`
- `problem_size=20` -> `21`

支持的问题：

- `Train_ALL`
- `ALL`
- `CVRP`
- `OVRP`
- `VRPB`
- `VRPL`
- `VRPTW`
- `OVRPTW`
- `OVRPB`
- `OVRPL`
- `VRPBL`
- `VRPBTW`
- `VRPLTW`
- `OVRPBL`
- `OVRPBTW`
- `OVRPLTW`
- `VRPBLTW`
- `OVRPBLTW`

`Train_ALL`：

```bash
./.venv/bin/python data/utils/generate_data.py --problem Train_ALL --problem_size 100 --num_samples 50
```

全部：

```bash
./.venv/bin/python data/utils/generate_data.py --problem ALL --problem_size 100 --num_samples 50
```

如果需要旧的聚合格式：

```bash
./.venv/bin/python data/utils/generate_data.py --problem CVRP --problem_size 100 --num_samples 50 --format pkl
```

默认配置在 `data/config.yaml`。

## Solve `.vrp` -> `.sol`

输出目录：

- `data/opt/<PROBLEM>/<节点数>/pyvrp/`
- `data/opt/<PROBLEM>/<节点数>/ortools/`

输出文件：

- `n101-0001.sol`

输出格式：

```text
Route #1: 45 17 4 44 37 10
Route #2: 2 23 32 50 11 26 20 15 27
Cost 27591
Time 1.068822s
```

运行前提：

- 从仓库根目录 `reevo/` 执行下面命令。
- 使用仓库虚拟环境 `./.venv/bin/python`。
- `OR-Tools` 由根目录 [pyproject.toml](/home/zguo/Coding/reevo/pyproject.toml) 管理。
- `solve_reference_pyvrp.py` 会自动从 `utils/pyvrp_rep` 加载本地 `pyvrp` 实现，不需要额外安装独立的 `pyvrp` 包。

## OR-Tools

单个问题：

```bash
./.venv/bin/python data/utils/solve_reference_ortools.py --problem CVRP
```

全部 generated：

```bash
./.venv/bin/python data/utils/solve_reference_ortools.py
```

## pyvrp / HGS

`solve_reference_pyvrp.py` 当前支持全部当前问题类型。

单个问题：

```bash
./.venv/bin/python data/utils/solve_reference_pyvrp.py --problem CVRP
```

全部 generated：

```bash
./.venv/bin/python data/utils/solve_reference_pyvrp.py
```

## 同时跑 OR-Tools 和 pyvrp

```bash
bash -lc './.venv/bin/python data/utils/solve_reference_ortools.py && ./.venv/bin/python data/utils/solve_reference_pyvrp.py'
```

这时会同时保留两套结果：

- `data/opt/<PROBLEM>/<节点数>/ortools/*.sol`
- `data/opt/<PROBLEM>/<节点数>/pyvrp/*.sol`

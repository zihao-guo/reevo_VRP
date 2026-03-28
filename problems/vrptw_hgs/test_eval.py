import math
from pathlib import Path

from problems.vrptw_hgs.eval import REPO_ROOT, calculate_exact_vrptw_cost, load_problem_cfg


class StubRoute:
    def __init__(self, visits):
        self._visits = visits

    def visits(self):
        return self._visits


def load_stub_routes(solution_path: Path) -> list[StubRoute]:
    routes = []
    with open(solution_path, "r", encoding="utf-8") as file:
        for raw_line in file:
            line = raw_line.strip()
            if not line.startswith("Route #"):
                continue
            _, rhs = line.split(":", 1)
            routes.append(StubRoute([int(token) for token in rhs.split()]))
    return routes


def load_expected_cost(solution_path: Path) -> float:
    with open(solution_path, "r", encoding="utf-8") as file:
        for raw_line in file:
            line = raw_line.strip()
            if line.startswith("Cost "):
                return float(line.split()[1])
    raise ValueError(f"Missing cost in `{solution_path}`.")


def test_calculate_exact_vrptw_cost_matches_baseline_solution():
    instance_path = REPO_ROOT / "data" / "generated" / "VRPTW" / "101" / "n101-0001.vrp"
    solution_path = REPO_ROOT / "data" / "opt" / "VRPTW" / "101" / "pyvrp" / "n101-0001.sol"

    routes = load_stub_routes(solution_path)
    expected_cost = load_expected_cost(solution_path)

    assert math.isclose(
        calculate_exact_vrptw_cost(instance_path, routes),
        expected_cost,
        rel_tol=0.0,
        abs_tol=1e-6,
    )


def test_vrptw_problem_cfg_uses_real_uppercase_directories():
    cfg = load_problem_cfg(REPO_ROOT)

    assert cfg["dataset_dir"] == "data/generated/VRPTW/101"
    assert cfg["baseline_dir"] == "data/opt/VRPTW/101"

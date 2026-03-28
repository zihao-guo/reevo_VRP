import math
from pathlib import Path

from problems.ovrp_hgs.eval import REPO_ROOT, calculate_exact_ovrp_cost


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


def test_calculate_exact_ovrp_cost_matches_open_baseline_solution():
    instance_path = REPO_ROOT / "data" / "generated" / "OVRP" / "101" / "n101-0001.vrp"
    solution_path = REPO_ROOT / "data" / "opt" / "OVRP" / "101" / "pyvrp" / "n101-0001.sol"

    routes = load_stub_routes(solution_path)
    expected_cost = load_expected_cost(solution_path)

    assert math.isclose(
        calculate_exact_ovrp_cost(instance_path, routes),
        expected_cost,
        rel_tol=0.0,
        abs_tol=1e-6,
    )

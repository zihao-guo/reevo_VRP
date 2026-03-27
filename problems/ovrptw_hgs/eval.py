import concurrent.futures
import json
import math
import multiprocessing as mp
import os
import shutil
import subprocess
import sys
import sysconfig
import tempfile
from pathlib import Path
from functools import lru_cache

import yaml
import pybind11


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


PROBLEM_DIR = Path(__file__).resolve().parent
if str(PROBLEM_DIR) not in sys.path:
    sys.path.insert(0, str(PROBLEM_DIR))

from anti_plagiarism import assert_below_threshold  # noqa: E402
from code_extraction import extract_cpp_code  # noqa: E402

VRP_FILE_SCALE = 1000


def load_problem_cfg(root_dir: Path) -> dict:
    cfg_path = root_dir / "cfg" / "problem" / "ovrptw_hgs.yaml"
    with open(cfg_path, "r", encoding="utf-8") as file:
        return yaml.safe_load(file)


def problem_paths(root_dir: Path, cfg: dict) -> dict[str, Path]:
    return {
        "dataset_dir": root_dir / cfg["dataset_dir"],
        "baseline_dir": root_dir / cfg["baseline_dir"],
        "pyvrp_root": root_dir / cfg["pyvrp_root"],
        "candidate_cpp": root_dir / cfg["candidate_cpp"],
        "original_reference": root_dir / cfg["original_reference"],
        "build_lock": root_dir / cfg["build_lock"],
    }


def load_candidate_code(root_dir: Path, candidate_path: str | None) -> str:
    source_path = Path(candidate_path) if candidate_path else root_dir / "problems" / "ovrptw_hgs" / "gpt.py"
    content = source_path.read_text(encoding="utf-8")
    code = extract_cpp_code(content)
    if code is None:
        raise ValueError(f"Failed to extract C++ code from `{source_path}`.")
    return code


def should_enforce_plagiarism(candidate_path: str | None) -> bool:
    # //modify Allow the seed baseline and final validation fallback to run unchanged.
    if candidate_path is None:
        return False

    candidate_name = Path(candidate_path).name
    return candidate_name != "problem_iter0_candidate0_selective_route_exchange.cpp"


def load_instances(paths: dict[str, Path]) -> list[str]:
    return sorted(path.name for path in paths["dataset_dir"].glob("*.vrp"))


def select_proxy_instances(instances: list[str], count: int) -> list[str]:
    if count >= len(instances):
        return instances

    indices = []
    last_idx = len(instances) - 1
    for step in range(count):
        idx = round(step * last_idx / (count - 1))
        if idx not in indices:
            indices.append(idx)
    return [instances[idx] for idx in indices]


def baseline_result(paths: dict[str, Path], instance_name: str) -> dict:
    stem = Path(instance_name).stem
    pyvrp_reference = load_reference_solution(
        preferred_path=paths["baseline_dir"] / "pyvrp" / f"{stem}.sol",
        fallback_paths=[
            paths["baseline_dir"] / "pyvrp" / f"{stem}.pyvrp.sol",
            paths["baseline_dir"] / f"{stem}.pyvrp.sol",
        ],
    )
    ortools_reference = load_reference_solution(
        preferred_path=paths["baseline_dir"] / "ortools" / f"{stem}.sol",
        fallback_paths=[
            paths["baseline_dir"] / "ortools" / f"{stem}.ortools.sol",
            paths["baseline_dir"] / f"{stem}.ortools.sol",
        ],
    )
    return {
        "obj": pyvrp_reference["cost"],
        "solver_runtime_seconds": pyvrp_reference["runtime_seconds"],
        "ortools_obj": ortools_reference["cost"],
        "ortools_runtime_seconds": ortools_reference["runtime_seconds"],
    }


def load_reference_solution(
    preferred_path: Path,
    fallback_paths: list[Path] | None = None,
) -> dict[str, float]:
    candidate_paths = [preferred_path]
    if fallback_paths:
        candidate_paths.extend(fallback_paths)

    solution_path = next((path for path in candidate_paths if path.exists()), None)
    if solution_path is None:
        searched = ", ".join(f"`{path}`" for path in candidate_paths)
        raise FileNotFoundError(f"Reference solution not found. Searched: {searched}.")

    cost = None
    runtime_seconds = None

    with open(solution_path, "r", encoding="utf-8") as file:
        for raw_line in file:
            line = raw_line.strip()
            if line.startswith("Cost "):
                cost = float(line.split()[1])
            elif line.startswith("Time "):
                runtime_seconds = float(line.split()[1].removesuffix("s"))

    if cost is None or runtime_seconds is None:
        raise ValueError(f"Failed to parse Cost/Time from `{solution_path}`.")

    return {"cost": cost, "runtime_seconds": runtime_seconds}


def calculate_exact_ovrptw_cost(instance_path: Path, routes) -> float:
    coords: dict[int, tuple[float, float]] = {}
    in_coord_section = False

    with open(instance_path, "r", encoding="utf-8") as file:
        for raw_line in file:
            line = raw_line.strip()
            if not line:
                continue

            if line == "NODE_COORD_SECTION":
                in_coord_section = True
                continue

            if line == "DEMAND_SECTION":
                break

            if in_coord_section:
                node_idx, x_coord, y_coord = line.split()
                coords[int(node_idx)] = (
                    int(x_coord) / VRP_FILE_SCALE,
                    int(y_coord) / VRP_FILE_SCALE,
                )

    if 1 not in coords:
        raise ValueError(f"Failed to parse depot coordinates from `{instance_path}`.")

    total_cost = 0.0
    for route in routes:
        # //modify PyVRP's VRPLIB reader stores depot at index 0, so client
        # //modify visits must shift by +1 to match the original file numbering.
        visits = [visit + 1 for visit in route.visits()]
        sequence = [1, *visits, 1]
        for frm, to in zip(sequence[:-1], sequence[1:]):
            x1, y1 = coords[frm]
            x2, y2 = coords[to]
            total_cost += math.hypot(x1 - x2, y1 - y2)

    return total_cost


def ensure_pyvrp_built(pyvrp_root: Path, build_dir_name: str) -> None:
    ext_suffix = sysconfig.get_config_var("EXT_SUFFIX")
    expected = pyvrp_root / "pyvrp" / f"_pyvrp{ext_suffix}"
    build_dir = pyvrp_root / build_dir_name

    if build_dir_uses_old_pybind11(build_dir) or build_dir_source_mismatch(build_dir, pyvrp_root):
        shutil.rmtree(build_dir, ignore_errors=True)

    if expected.exists() and build_dir.exists():
        return

    cmd = [
        sys.executable,
        "buildtools/build_extensions.py",
        "--build_dir",
        build_dir_name,
        "--build_type",
        "release",
    ]
    subprocess.run(cmd, cwd=pyvrp_root, check=True, env=build_env())


def incremental_build_candidate(
    pyvrp_root: Path,
    build_dir_name: str,
    candidate_cpp: Path,
    candidate_code: str,
) -> None:
    # //modify Candidate builds happen inside per-candidate sandboxes. New
    # //modify PyVRP no longer uses a separate candidate plugin file, so we
    # //modify overwrite the real crossover source in that sandbox and rebuild.
    candidate_cpp.write_text(candidate_code + "\n", encoding="utf-8")

    cmd = [
        sys.executable,
        "buildtools/build_extensions.py",
        "--build_dir",
        build_dir_name,
        "--build_type",
        "release",
    ]
    subprocess.run(cmd, cwd=pyvrp_root, check=True, env=build_env())


def build_dir_uses_old_pybind11(build_dir: Path) -> bool:
    log_path = build_dir / "meson-logs" / "meson-log.txt"
    if not log_path.exists():
        return False

    content = log_path.read_text(encoding="utf-8", errors="ignore")
    return "Run-time dependency pybind11 found: YES 2.9.1" in content


def build_dir_source_mismatch(build_dir: Path, pyvrp_root: Path) -> bool:
    intro_path = build_dir / "meson-info" / "intro-buildsystem_files.json"
    if not intro_path.exists():
        return False

    try:
        buildsystem_files = json.loads(intro_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False

    root_prefix = str(pyvrp_root.resolve()) + os.sep
    for entry in buildsystem_files:
        if not isinstance(entry, str):
            continue
        if not entry.endswith(("meson.build", "pyproject.toml")):
            continue
        resolved = str(Path(entry).resolve(strict=False))
        if not resolved.startswith(root_prefix):
            return True

    return False


def build_env() -> dict[str, str]:
    # //modify Force Meson/CMake/pkg-config to resolve pybind11 from the active .venv.
    env = os.environ.copy()
    venv_bin = str(Path(sys.executable).resolve().parent)
    pybind_root = Path(pybind11.__file__).resolve().parent
    pkgconfig_dir = pybind_root / "share" / "pkgconfig"
    cmake_dir = pybind_root / "share" / "cmake"
    purelib_dir = Path(sysconfig.get_paths()["purelib"])

    env["PATH"] = f"{venv_bin}:{env.get('PATH', '')}"
    env["PKG_CONFIG_PATH"] = (
        f"{pkgconfig_dir}:{env['PKG_CONFIG_PATH']}"
        if env.get("PKG_CONFIG_PATH")
        else str(pkgconfig_dir)
    )
    env["CMAKE_PREFIX_PATH"] = (
        f"{cmake_dir}:{env['CMAKE_PREFIX_PATH']}"
        if env.get("CMAKE_PREFIX_PATH")
        else str(cmake_dir)
    )
    env["PYTHONPATH"] = (
        f"{purelib_dir}:{env['PYTHONPATH']}"
        if env.get("PYTHONPATH")
        else str(purelib_dir)
    )
    return env


@lru_cache(maxsize=4)
def ensure_local_pyvrp_import(pyvrp_root: Path) -> Path:
    pyvrp_root = pyvrp_root.resolve()
    if str(pyvrp_root) not in sys.path:
        sys.path.insert(0, str(pyvrp_root))

    import pyvrp

    imported_from = Path(pyvrp.__file__).resolve()
    if pyvrp_root not in imported_from.parents:
        raise ImportError(
            "Imported `pyvrp` from an unexpected location. "
            f"Expected under {pyvrp_root}, got {imported_from}."
        )

    return imported_from


def sandbox_problem_paths(paths: dict[str, Path], sandbox_pyvrp_root: Path) -> dict[str, Path]:
    # //modify Re-point all PyVRP-local paths into a candidate-specific sandbox
    # //modify so different candidates can build and evaluate concurrently.
    source_root = paths["pyvrp_root"]
    sandbox_paths = dict(paths)
    sandbox_paths["pyvrp_root"] = sandbox_pyvrp_root
    sandbox_paths["candidate_cpp"] = sandbox_pyvrp_root / paths["candidate_cpp"].relative_to(source_root)
    return sandbox_paths


def clone_pyvrp_sandbox(shared_pyvrp_root: Path, sandbox_parent: Path) -> Path:
    # //modify Copy a source-only PyVRP tree into an isolated sandbox so each
    # //modify candidate gets its own build directory and can compile in
    # //modify parallel without interfering with other candidates.
    sandbox_root = sandbox_parent / shared_pyvrp_root.name
    shutil.copytree(
        shared_pyvrp_root,
        sandbox_root,
        ignore=shutil.ignore_patterns(
            "__pycache__",
            ".pytest_cache",
            ".mypy_cache",
            ".ruff_cache",
            "docs",
            "examples",
            "tests",
            "build-*",
        ),
    )
    return sandbox_root


def solve_instance(
    pyvrp_root: Path,
    dataset_dir: Path,
    instance_name: str,
    baseline: dict,
    round_func: str,
    seed: int,
    max_iterations: int,
) -> dict:
    ensure_local_pyvrp_import(pyvrp_root)

    from pyvrp.read import read
    from pyvrp.solve import SolveParams, solve
    from pyvrp.stop import MaxIterations

    data = read(dataset_dir / instance_name, round_func)
    result = solve(
        data,
        MaxIterations(max_iterations),
        seed=seed,
        collect_stats=False,
        display=False,
        params=SolveParams(),
    )

    obj = calculate_exact_ovrptw_cost(dataset_dir / instance_name, result.best.routes())
    feasible = result.is_feasible() and math.isfinite(obj)
    if not feasible:
        obj = float(baseline["obj"]) + max(100000.0, float(baseline["obj"]) * 10.0)

    baseline_obj = float(baseline["obj"])
    baseline_runtime = float(baseline["solver_runtime_seconds"])
    ortools_obj = float(baseline["ortools_obj"])
    ortools_runtime = float(baseline["ortools_runtime_seconds"])
    # //modify Optimise against the original HGS baseline stored under data/opt/OVRPTW/101/pyvrp.
    delta_gap_percent_vs_baseline = ((obj / baseline_obj) - 1.0) * 100.0

    return {
        "instance": instance_name,
        "feasible": feasible,
        "obj": obj,
        "runtime": float(result.runtime),
        "baseline_obj": baseline_obj,
        "baseline_runtime": baseline_runtime,
        "ortools_obj": ortools_obj,
        "ortools_runtime": ortools_runtime,
        "delta_gap_percent_vs_baseline": delta_gap_percent_vs_baseline,
        "delta_runtime_seconds_vs_baseline": float(result.runtime) - baseline_runtime,
        "delta_gap_percent_vs_ortools": ((obj / ortools_obj) - 1.0) * 100.0,
        "delta_runtime_seconds_vs_ortools": float(result.runtime) - ortools_runtime,
    }


def solve_instance_from_args(args) -> dict:
    return solve_instance(*args)


def _smoke_worker(queue, args) -> None:
    try:
        queue.put(("ok", solve_instance(*args)))
    except Exception as exc:  # //modify Surface smoke-test failures without hanging the main evaluator.
        queue.put(("err", repr(exc)))


def run_smoke_test(
    pyvrp_root: Path,
    dataset_dir: Path,
    instance_name: str,
    baseline: dict,
    round_func: str,
    seed: int,
    max_iterations: int,
    timeout_seconds: int,
) -> dict:
    ctx = mp.get_context("spawn")
    queue = ctx.Queue()
    args = (pyvrp_root, dataset_dir, instance_name, baseline, round_func, seed, max_iterations)
    process = ctx.Process(target=_smoke_worker, args=(queue, args))
    process.start()
    process.join(timeout_seconds)

    if process.is_alive():
        process.terminate()
        process.join()
        raise TimeoutError(
            f"Smoke test timed out after {timeout_seconds}s on instance `{instance_name}`."
        )

    if queue.empty():
        raise RuntimeError(
            f"Smoke test exited without result on instance `{instance_name}` (exit code {process.exitcode})."
        )

    status, payload = queue.get()
    if status == "err":
        raise RuntimeError(f"Smoke test failed on instance `{instance_name}`: {payload}")
    return payload


def evaluate_instances(
    pyvrp_root: Path,
    dataset_dir: Path,
    instances: list[str],
    paths: dict[str, Path],
    round_func: str,
    seed: int,
    max_iterations: int,
    workers: int,
) -> list[dict]:
    baselines = [baseline_result(paths, instance) for instance in instances]
    args = [
        (pyvrp_root, dataset_dir, instance, baseline, round_func, seed, max_iterations)
        for instance, baseline in zip(instances, baselines)
    ]

    if workers <= 1:
        return [solve_instance(*arg) for arg in args]

    with concurrent.futures.ProcessPoolExecutor(max_workers=workers) as executor:
        return list(executor.map(solve_instance_from_args, args))


def summarise(results: list[dict]) -> dict:
    count = len(results)
    improved = sum(1 for result in results if result["delta_gap_percent_vs_baseline"] < 0.0)
    feasible = sum(1 for result in results if result["feasible"])
    avg_obj = sum(result["obj"] for result in results) / count
    avg_runtime = sum(result["runtime"] for result in results) / count
    avg_delta_gap = sum(result["delta_gap_percent_vs_baseline"] for result in results) / count
    avg_delta_runtime_baseline = (
        sum(result["delta_runtime_seconds_vs_baseline"] for result in results) / count
    )
    avg_delta_gap_ortools = sum(result["delta_gap_percent_vs_ortools"] for result in results) / count
    avg_delta_runtime_ortools = (
        sum(result["delta_runtime_seconds_vs_ortools"] for result in results) / count
    )
    return {
        "count": count,
        "feasible_count": feasible,
        "improved_count": improved,
        "avg_obj": avg_obj,
        "avg_runtime": avg_runtime,
        "avg_delta_gap_percent_vs_baseline": avg_delta_gap,
        "avg_delta_runtime_seconds_vs_baseline": avg_delta_runtime_baseline,
        "avg_delta_gap_percent_vs_ortools": avg_delta_gap_ortools,
        "avg_delta_runtime_seconds_vs_ortools": avg_delta_runtime_ortools,
    }


def main() -> None:
    print("[*] Running ...")
    root_dir = Path(sys.argv[2]).resolve()
    mood = sys.argv[3]
    candidate_path = sys.argv[4] if len(sys.argv) > 4 else None
    assert mood in {"train", "val", "test"}

    cfg = load_problem_cfg(root_dir)
    paths = problem_paths(root_dir, cfg)
    generated_output_override = os.environ.get("REEVO_GENERATED_OUTPUT")
    generated_output_path = (
        Path(generated_output_override).resolve() if generated_output_override else None
    )
    candidate_code = load_candidate_code(root_dir, candidate_path)
    reference_code = paths["original_reference"].read_text(encoding="utf-8")

    if should_enforce_plagiarism(candidate_path):
        similarity = assert_below_threshold(
            candidate_code,
            reference_code,
            float(cfg["plagiarism_threshold"]),
        )
    else:
        from anti_plagiarism import similarity_ratio

        similarity = similarity_ratio(candidate_code, reference_code)

    if candidate_path is None:
        if generated_output_path is None:
            raise RuntimeError(
                "REEVO_GENERATED_OUTPUT must be set when exporting the final OVRPTW HGS candidate."
            )
        generated_output_path.parent.mkdir(parents=True, exist_ok=True)
        generated_output_path.write_text(candidate_code + "\n", encoding="utf-8")

    workers = max(1, (os.cpu_count() or 1) // int(cfg["parallel_workers_divisor"]))
    instances = load_instances(paths)
    smoke_instance = cfg.get("smoke_test_instance", instances[0])
    smoke_timeout = int(cfg.get("smoke_test_timeout", 120))
    max_iterations = int(cfg.get("max_iterations", 1000))

    with tempfile.TemporaryDirectory(prefix="ovrptw-hgs-pyvrp-") as sandbox_dir:
        sandbox_root = Path(sandbox_dir)
        sandbox_pyvrp_root = clone_pyvrp_sandbox(paths["pyvrp_root"], sandbox_root)
        sandbox_paths = sandbox_problem_paths(paths, sandbox_pyvrp_root)
        incremental_build_candidate(
            sandbox_paths["pyvrp_root"],
            cfg["pyvrp_build_dir"],
            sandbox_paths["candidate_cpp"],
            candidate_code,
        )
        try:
            smoke_result = run_smoke_test(
                sandbox_paths["pyvrp_root"],
                sandbox_paths["dataset_dir"],
                smoke_instance,
                baseline_result(paths, smoke_instance),
                cfg["round_func"],
                int(cfg["seed"]),
                max_iterations,
                smoke_timeout,
            )
        except Exception as exc:
            print(f"[*] Anti-plagiarism similarity: {similarity:.6f}")
            print(f"[*] Smoke test instance: {smoke_instance}")
            print(f"[*] Smoke test failed: {exc}")
            if mood == "train":
                print("inf")
            return

        results = evaluate_instances(
            sandbox_paths["pyvrp_root"],
            sandbox_paths["dataset_dir"],
            instances,
            paths,
            cfg["round_func"],
            int(cfg["seed"]),
            max_iterations,
            workers,
        )

    summary = summarise(results)
    print(f"[*] Anti-plagiarism similarity: {similarity:.6f}")
    print(f"[*] Smoke test instance: {smoke_instance}")
    print(f"[*] Smoke test feasible: {smoke_result['feasible']}")
    print(f"[*] Smoke test objective: {smoke_result['obj']:.6f}")
    print(f"[*] Smoke test runtime seconds: {smoke_result['runtime']:.6f}")
    print(f"[*] Instances evaluated: {summary['count']}")
    print(f"[*] Feasible solutions: {summary['feasible_count']}/{summary['count']}")
    print(f"[*] Improved over baseline: {summary['improved_count']}/{summary['count']}")
    print(f"[*] Average objective: {summary['avg_obj']:.6f}")
    print(f"[*] Average delta gap vs baseline (%): {summary['avg_delta_gap_percent_vs_baseline']:.6f}")
    print(f"[*] Average delta runtime vs baseline (s): {summary['avg_delta_runtime_seconds_vs_baseline']:.6f}")
    print(f"[*] Average runtime seconds: {summary['avg_runtime']:.6f}")
    print(f"[*] Average delta gap vs OR-Tools (%): {summary['avg_delta_gap_percent_vs_ortools']:.6f}")
    print(f"[*] Average delta runtime vs OR-Tools (s): {summary['avg_delta_runtime_seconds_vs_ortools']:.6f}")

    if mood == "train":
        print(f"{summary['avg_delta_gap_percent_vs_baseline']:.6f}")


if __name__ == "__main__":
    main()

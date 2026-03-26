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

import yaml
import pybind11


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


PROBLEM_DIR = Path(__file__).resolve().parent
if str(PROBLEM_DIR) not in sys.path:
    sys.path.insert(0, str(PROBLEM_DIR))

from anti_plagiarism import assert_below_threshold  # noqa: E402
from code_extraction import extract_cpp_code  # noqa: E402


def load_problem_cfg(root_dir: Path) -> dict:
    cfg_path = root_dir / "cfg" / "problem" / "cvrp_hgs.yaml"
    with open(cfg_path, "r", encoding="utf-8") as file:
        return yaml.safe_load(file)


def problem_paths(root_dir: Path, cfg: dict) -> dict[str, Path]:
    return {
        "dataset_dir": root_dir / cfg["dataset_dir"],
        "baseline_dir": root_dir / cfg["baseline_dir"],
        "pyvrp_root": root_dir / cfg["pyvrp_root"],
        "original_cpp": root_dir / cfg["original_cpp"],
        "candidate_cpp": root_dir / cfg["candidate_cpp"],
        "generated_output": root_dir / cfg["output_file"],
        "original_reference": root_dir / cfg["original_reference"],
        "build_lock": root_dir / cfg["build_lock"],
    }


def load_candidate_code(root_dir: Path, candidate_path: str | None) -> str:
    source_path = Path(candidate_path) if candidate_path else root_dir / "problems" / "cvrp_hgs" / "gpt.py"
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
    run_meta_path = paths["baseline_dir"] / "run_meta.json"
    with open(run_meta_path, "r", encoding="utf-8") as file:
        meta = json.load(file)
    return meta["instances"]


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
    result_path = paths["baseline_dir"] / stem / "result.json"
    with open(result_path, "r", encoding="utf-8") as file:
        return json.load(file)


def ensure_pyvrp_built(pyvrp_root: Path, build_dir_name: str) -> None:
    ext_suffix = sysconfig.get_config_var("EXT_SUFFIX")
    expected = pyvrp_root / "pyvrp" / f"_pyvrp{ext_suffix}"
    build_dir = pyvrp_root / build_dir_name

    if build_dir_uses_old_pybind11(build_dir):
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
    # //modify Candidate builds now happen inside per-candidate sandboxes, so we
    # //modify only need to update the candidate plugin source file there.
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


def sandbox_problem_paths(paths: dict[str, Path], sandbox_pyvrp_root: Path) -> dict[str, Path]:
    # //modify Re-point all PyVRP-local paths into a candidate-specific sandbox
    # //modify so different candidates can build and evaluate concurrently.
    source_root = paths["pyvrp_root"]
    sandbox_paths = dict(paths)
    sandbox_paths["pyvrp_root"] = sandbox_pyvrp_root
    sandbox_paths["original_cpp"] = sandbox_pyvrp_root / paths["original_cpp"].relative_to(source_root)
    sandbox_paths["candidate_cpp"] = sandbox_pyvrp_root / paths["candidate_cpp"].relative_to(source_root)
    return sandbox_paths


def clone_pyvrp_sandbox(shared_pyvrp_root: Path, sandbox_parent: Path) -> Path:
    # //modify Copy a source-only PyVRP tree into an isolated sandbox so each
    # //modify candidate gets its own build directory and plugin installation.
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
) -> dict:
    if str(pyvrp_root) not in sys.path:
        sys.path.insert(0, str(pyvrp_root))

    os.environ["PYVRP_SREX_USE_PLUGIN"] = "1"

    from pyvrp.read import read
    from pyvrp.solve import SolveParams, solve
    from pyvrp.stop import MaxRuntime

    data = read(dataset_dir / instance_name, round_func)
    result = solve(
        data,
        MaxRuntime(float(baseline["solver_runtime_seconds"])),
        seed=seed,
        collect_stats=False,
        display=False,
        params=SolveParams(),
    )

    obj = float(result.cost())
    feasible = result.is_feasible() and math.isfinite(obj)
    if not feasible:
        obj = float(baseline["obj"]) + max(100000.0, float(baseline["optimal_cost"]) * 10.0)

    baseline_obj = float(baseline["obj"])
    # //modify Optimise against baseline by delta gap percentage instead of raw objective difference.
    delta_gap_percent_vs_baseline = ((obj / baseline_obj) - 1.0) * 100.0

    return {
        "instance": instance_name,
        "feasible": feasible,
        "obj": obj,
        "runtime": float(result.runtime),
        "baseline_obj": baseline_obj,
        "optimal_cost": float(baseline["optimal_cost"]),
        "delta_gap_percent_vs_baseline": delta_gap_percent_vs_baseline,
        "gap_percent": ((obj - float(baseline["optimal_cost"])) / float(baseline["optimal_cost"])) * 100.0,
        "baseline_gap_percent": float(baseline["optimal_gap_percent"]),
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
    timeout_seconds: int,
) -> dict:
    ctx = mp.get_context("spawn")
    queue = ctx.Queue()
    args = (pyvrp_root, dataset_dir, instance_name, baseline, round_func, seed)
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
    workers: int,
) -> list[dict]:
    baselines = [baseline_result(paths, instance) for instance in instances]
    args = [
        (pyvrp_root, dataset_dir, instance, baseline, round_func, seed)
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
    avg_gap = sum(result["gap_percent"] for result in results) / count
    avg_baseline_gap = sum(result["baseline_gap_percent"] for result in results) / count
    return {
        "count": count,
        "feasible_count": feasible,
        "improved_count": improved,
        "avg_obj": avg_obj,
        "avg_runtime": avg_runtime,
        "avg_delta_gap_percent_vs_baseline": avg_delta_gap,
        "avg_gap_percent": avg_gap,
        "avg_baseline_gap_percent": avg_baseline_gap,
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
    if generated_output_override:
        paths["generated_output"] = Path(generated_output_override).resolve()
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
        paths["generated_output"].parent.mkdir(parents=True, exist_ok=True)
        paths["generated_output"].write_text(candidate_code + "\n", encoding="utf-8")

    workers = max(1, (os.cpu_count() or 1) // int(cfg["parallel_workers_divisor"]))
    instances = load_instances(paths)
    smoke_instance = cfg.get("smoke_test_instance", instances[0])
    smoke_timeout = int(cfg.get("smoke_test_timeout", 120))

    with tempfile.TemporaryDirectory(prefix="cvrp-hgs-pyvrp-") as sandbox_dir:
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
    print(f"[*] Average objective: {summary['avg_obj']:.2f}")
    print(f"[*] Average delta gap vs baseline (%): {summary['avg_delta_gap_percent_vs_baseline']:.2f}")
    print(f"[*] Average runtime seconds: {summary['avg_runtime']:.2f}")
    print(f"[*] Average optimal gap percent: {summary['avg_gap_percent']:.2f}")
    print(f"[*] Baseline average optimal gap percent: {summary['avg_baseline_gap_percent']:.2f}")

    if mood == "train":
        print(f"{summary['avg_delta_gap_percent_vs_baseline']:.2f}")


if __name__ == "__main__":
    main()

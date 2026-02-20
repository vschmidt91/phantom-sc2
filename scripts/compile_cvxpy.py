import argparse
import importlib.machinery
import logging
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import cvxpy as cp

from cvxpygen import cpg


logging.basicConfig(
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


def _build_problem(size: int) -> cp.Problem:
    x = cp.Variable((size, size), "x")
    w = cp.Parameter((size, size), name="w")
    b = cp.Parameter(size, name="b")
    gw = cp.Parameter(size, name="gw")
    g = cp.Parameter(1, name="g")
    t = cp.Parameter(size, name="t")

    objective = cp.Minimize(cp.vdot(w, x))
    constraints = [
        cp.sum(x, 0) <= b,
        cp.sum(x, 1) == t,
        cp.vdot(cp.sum(x, 0), gw) == g,
        0 <= x,
    ]
    return cp.Problem(objective, constraints)


def _verify_importable(module_dir: Path) -> None:
    candidates = sorted(
        {
            candidate
            for suffix in importlib.machinery.EXTENSION_SUFFIXES
            for candidate in module_dir.glob(f"*{suffix}")
        }
    )
    if not candidates:
        raise RuntimeError(f"No extension binary found in {module_dir}")
    binary = candidates[0]
    try:
        subprocess.check_output(
            [
                sys.executable,
                "-c",
                (
                    "import importlib.util, sys; "
                    f"spec=importlib.util.spec_from_file_location('cpg_module', r'{binary}'); "
                    "module=importlib.util.module_from_spec(spec); "
                    "spec.loader.exec_module(module)"
                ),
            ],
            stderr=subprocess.STDOUT,
            text=True,
        )
    except Exception as ex:
        raise RuntimeError(f"Generated cpg_module is not importable from {module_dir}: {ex}") from ex


def _resolve_cmake(cmake_override: Path | None) -> Path:
    if cmake_override is not None:
        candidate = cmake_override.expanduser().resolve()
        if not candidate.is_file():
            raise RuntimeError(f"CMake executable override does not exist: {candidate}")
        return candidate

    from_path = shutil.which("cmake")
    if from_path is not None:
        return Path(from_path).resolve()

    try:
        import cmake as cmake_pkg
    except Exception:
        cmake_pkg = None

    if cmake_pkg is not None:
        candidate = Path(cmake_pkg.CMAKE_BIN_DIR) / ("cmake.exe" if os.name == "nt" else "cmake")
        if candidate.is_file():
            return candidate.resolve()

    raise RuntimeError(
        "CMake is required to compile CVXPYGEN modules. Install `cmake`, add it to PATH, "
        "or pass --cmake / set PHANTOM_CMAKE."
    )


def _prepend_path(directory: Path) -> None:
    values = [v for v in os.environ.get("PATH", "").split(os.pathsep) if v]
    directory_str = str(directory)
    if directory_str not in values:
        os.environ["PATH"] = os.pathsep.join([directory_str, *values])


def _build_single_problem(final_root: Path, log2_size: int) -> str:
    size = 2 ** log2_size
    problem_name = f"harvest{log2_size}"

    logger.info("Starting build for %s", problem_name)
    with tempfile.TemporaryDirectory(prefix=f"harvest{log2_size}_build", ignore_cleanup_errors=True) as tmp_build_root:
        build_root = Path(tmp_build_root) / problem_name
        build_root.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix=f"{problem_name}_stage", ignore_cleanup_errors=True) as tmp_stage_root:
            stage_dir = Path(tmp_stage_root) / problem_name
            stage_dir.mkdir(parents=True, exist_ok=True)
            build_dir = build_root / problem_name
            previous_cwd = Path.cwd()
            sys.path.insert(0, str(build_root))
            try:
                os.chdir(build_root)
                cpg.generate_code(_build_problem(size), code_dir=problem_name, prefix=problem_name, solver="OSQP")
            finally:
                os.chdir(previous_cwd)
                sys.path.pop(0)

            generated = list(build_dir.glob("cpg_module.*"))
            if not generated:
                raise RuntimeError(f"No cpg_module artifact generated in {build_dir}")

            for artifact in generated:
                shutil.copy2(artifact, stage_dir / f"{problem_name}{artifact.name.removeprefix('cpg_module')}")

            _verify_importable(stage_dir)
            final_root.mkdir(parents=True, exist_ok=True)
            for artifact in stage_dir.iterdir():
                shutil.copy2(artifact, final_root / artifact.name)

    logger.info("Finished build for %s", problem_name)

    return problem_name


def main() -> None:
    parser = argparse.ArgumentParser(description="Compile a single CVXPYGEN harvest solver binary.")
    parser.add_argument("--log2-size", type=int, default=6, help="Compile solver for size 2**N (default: 2**6).")
    parser.add_argument("--output-dir", type=Path, default=Path("bin"), help="Output directory (default: bin).")
    parser.add_argument(
        "--cmake",
        type=Path,
        default=None,
        help="Path to cmake executable. Defaults to PATH, then Python `cmake` package.",
    )
    args = parser.parse_args()

    output_dir = args.output_dir.resolve()
    cmake_override = args.cmake or (Path(os.environ["PHANTOM_CMAKE"]) if "PHANTOM_CMAKE" in os.environ else None)
    cmake_exe = _resolve_cmake(cmake_override)
    _prepend_path(cmake_exe.parent)
    try:
        subprocess.check_output([str(cmake_exe), "--version"])
    except Exception as ex:
        raise RuntimeError(f"Resolved CMake is not executable: {cmake_exe}: {ex}") from ex
    logger.info("Using CMake at %s", cmake_exe)

    final_root = output_dir / "cpg"
    if final_root.exists():
        shutil.rmtree(final_root, ignore_errors=True)
    final_root.mkdir(parents=True, exist_ok=True)
    logger.info("Aggregating builds into %s", final_root)
    for log2_size in range(1, args.log2_size + 1):
        problem_name = _build_single_problem(final_root, log2_size)
        print(f"Built {problem_name} at {final_root}")

    bundle_path = output_dir / "cpg.tar.xz"
    logger.info("Creating aggregate bundle %s", bundle_path)
    with tempfile.TemporaryDirectory() as pack_dir:
        pack_root = Path(pack_dir) / "cpg"
        shutil.copytree(final_root, pack_root)
        shutil.make_archive(str((output_dir / "cpg").resolve()), "xztar", root_dir=pack_dir, base_dir="cpg")

    print(f"Packed bundle at {bundle_path}")


if __name__ == "__main__":
    main()

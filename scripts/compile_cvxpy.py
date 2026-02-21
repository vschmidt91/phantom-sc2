import importlib.machinery
import importlib.util
import lzma
import logging
import shutil
import subprocess
import tarfile
import tempfile
from pathlib import Path

import click
import cvxpy as cp
from cvxpygen import cpg
from utils import CommandWithConfigFile

from phantom.common.distribute.cpg import solver

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
        x >= 0,
    ]
    return cp.Problem(objective, constraints)


def _verify_importable(binary: Path) -> None:
    try:
        spec = importlib.util.spec_from_file_location("cpg_module", binary)
        if spec is None or spec.loader is None:
            raise RuntimeError(f"Cannot create module spec for {binary}")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    except Exception as ex:
        raise RuntimeError(f"Generated cpg_module is not importable from {binary}: {ex}") from ex


def _resolve_cmake() -> Path:
    cmake = shutil.which("cmake")
    if cmake:
        return Path(cmake).resolve()
    raise RuntimeError(
        "CMake is required to compile CVXPYGEN modules. Install `cmake` and ensure it is on PATH."
    )


def _resolve_default_output_dir() -> Path:
    solver_file = getattr(solver, "__file__", None)
    if not solver_file:
        raise RuntimeError(f"{solver.__name__} has no __file__ path.")
    return Path(solver_file).resolve().parent


def _build_single_problem(final_root: Path, log2_size: int) -> str:
    size = 2 ** log2_size
    problem_name = f"assign{log2_size}"

    logger.info("Starting build for %s", problem_name)
    with tempfile.TemporaryDirectory(prefix=f"{problem_name}_build", ignore_cleanup_errors=True) as tmp_build_root:
        build_root = Path(tmp_build_root) / problem_name
        build_root.mkdir(parents=True, exist_ok=True)
        build_dir = build_root / problem_name
        cpg.generate_code(
            _build_problem(size),
            code_dir=str(build_dir),
            prefix=problem_name,
            solver=cp.OSQP,
            # cvxpygen imports using `f"{code_dir}.cpg_solver"`, which breaks for absolute
            # Windows paths. Compile wrapper manually to avoid that import path assumption.
            wrapper=False,
        )
        cpg.compile_python_module(str(build_dir))

        generated = list(build_dir.glob("cpg_module.*"))
        if not generated:
            raise RuntimeError(f"No cpg_module artifact generated in {build_dir}")

        final_root.mkdir(parents=True, exist_ok=True)
        copied = []
        for artifact in generated:
            out = final_root / f"{problem_name}{artifact.name.removeprefix('cpg_module')}"
            shutil.copy2(artifact, out)
            copied.append(out)

        for artifact in copied:
            _verify_importable(artifact)

    logger.info("Finished build for %s", problem_name)

    return problem_name


def _extension_artifacts(root: Path, stem_prefix: str = "assign") -> list[Path]:
    candidates = {
        candidate
        for suffix in importlib.machinery.EXTENSION_SUFFIXES
        for candidate in root.glob(f"{stem_prefix}*{suffix}")
    }
    return sorted(candidates, key=lambda p: p.name)


def _build_max_compression_bundle(output_dir: Path, artifacts: list[Path]) -> Path:
    bundle_path = output_dir / "cpg.tar.xz"
    with tarfile.open(
        bundle_path,
        mode="w:xz",
        preset=(9 | lzma.PRESET_EXTREME),
        format=tarfile.PAX_FORMAT,
    ) as archive:
        for artifact in artifacts:
            archive.add(artifact, arcname=f"cpg/{artifact.name}", recursive=False)
    return bundle_path


@click.command(cls=CommandWithConfigFile("config"))
@click.option("--config", type=click.File("rb"))
@click.option("--log2-size", type=int, default=6, show_default=True)
def main(
    config,  # consumed by CommandWithConfigFile
    log2_size: int,
) -> None:
    del config

    output_dir = _resolve_default_output_dir()
    cmake_exe = _resolve_cmake()
    try:
        subprocess.check_output([str(cmake_exe), "--version"])
    except Exception as ex:
        raise RuntimeError(f"Resolved CMake is not executable: {cmake_exe}: {ex}") from ex
    logger.info("Using CMake at %s", cmake_exe)

    final_root = output_dir
    final_root.mkdir(parents=True, exist_ok=True)
    for artifact in _extension_artifacts(final_root):
        artifact.unlink(missing_ok=True)
    logger.info("Aggregating builds into %s", final_root)
    for log2_size_item in range(1, log2_size + 1):
        problem_name = _build_single_problem(final_root, log2_size_item)
        print(f"Built {problem_name} at {final_root}")

    bundle_path = output_dir / "cpg.tar.xz"
    logger.info("Creating aggregate bundle %s", bundle_path)
    artifacts = _extension_artifacts(final_root)
    if bundle_path.exists():
        bundle_path.unlink()
    _build_max_compression_bundle(output_dir, artifacts)

    print(f"Packed bundle at {bundle_path}")


if __name__ == "__main__":
    main()

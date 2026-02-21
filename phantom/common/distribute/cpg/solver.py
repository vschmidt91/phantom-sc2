import importlib.machinery
import importlib.util
import math
import re
import shutil
import sys
import tarfile
from functools import cache
from pathlib import Path
from types import ModuleType

import numpy as np
from loguru import logger

_BLOCKED_COST = 1e6
_INTEGER_TOL = 1e-4
_RETRYABLE_STATUS = "maximum iterations reached"
_MODULE_NAME = "cpg_module"
_PROBLEM_PATTERN = re.compile(r"assign(\d+)")
_ARCHIVE_NAME = "cpg.tar.xz"


class CpgSolver:
    def __init__(self, module: ModuleType, problem_size: int, problem_name: str) -> None:
        self.module = module
        self.problem_size = problem_size
        self.problem_name = problem_name
        self._configure_solver()

        params_type = getattr(module, f"{problem_name}_cpg_params")
        updated_type = getattr(module, f"{problem_name}_cpg_updated")
        self._params = params_type()
        self._updated = updated_type()
        self._gw = np.zeros(self.problem_size, dtype=float)
        self._g = 0.0

    def _configure_solver(self) -> None:
        for fn, value in [
            ("set_solver_default_settings", None),
            ("set_solver_eps_abs", 1e-6),
            ("set_solver_eps_rel", 1e-6),
            ("set_solver_eps_prim_inf", 1e-6),
            ("set_solver_eps_dual_inf", 1e-6),
            ("set_solver_max_iter", 20_000),
            ("set_solver_warm_starting", True),
        ]:
            if not hasattr(self.module, fn):
                continue
            method = getattr(self.module, fn)
            if value is None:
                method()
            else:
                method(value)

    def set_total(self, coeffs: np.ndarray, limit: int) -> None:
        gw = np.zeros(self.problem_size, dtype=float)
        gw[: coeffs.shape[0]] = coeffs
        self._gw = gw
        self._g = float(limit)

    def solve(self, cost: np.ndarray, limit: np.ndarray) -> np.ndarray:
        n, m = cost.shape
        padded = np.full((self.problem_size, self.problem_size), _BLOCKED_COST, dtype=float)
        padded[:n, :m] = np.minimum(
            np.nan_to_num(cost, copy=True, nan=_BLOCKED_COST, posinf=_BLOCKED_COST), _BLOCKED_COST
        )

        b = np.zeros(self.problem_size, dtype=float)
        b[:m] = limit

        t = np.zeros(self.problem_size, dtype=float)
        t[:n] = 1.0

        # CVXPYGEN vectorizes matrices in Fortran order.
        self._params.w = padded.ravel(order="F")
        self._params.b = b
        self._params.t = t
        self._params.gw = self._gw
        self._params.g = self._g

        self._updated.w = True
        self._updated.b = True
        self._updated.t = True
        self._updated.gw = True
        self._updated.g = True

        result = self.module.solve(self._updated, self._params)
        status = result.cpg_info.status
        if status == _RETRYABLE_STATUS and hasattr(self.module, "set_solver_warm_starting"):
            self.module.set_solver_warm_starting(False)
            try:
                result = self.module.solve(self._updated, self._params)
                status = result.cpg_info.status
            finally:
                self.module.set_solver_warm_starting(True)
        if status == _RETRYABLE_STATUS:
            logger.warning(f"CVXPYGEN solve hit iteration limit for {self.problem_name}; using current iterate")
        elif status != "solved":
            raise RuntimeError(f"CVXPYGEN solve failed: {status}")

        x = np.asarray(result.cpg_prim.x, dtype=float).reshape(self.problem_size, self.problem_size, order="F")
        rounded = np.rint(x)
        x = np.where(np.abs(x - rounded) <= _INTEGER_TOL, rounded, x)
        return x[:n, :m]


def _cpg_root() -> Path:
    return Path(__file__).resolve().parent


def _log_index(path: Path) -> int:
    if match := _PROBLEM_PATTERN.search(path.name):
        return int(match.group(1))
    return -1


def _assign_binaries(directory: Path) -> list[Path]:
    if not directory.is_dir():
        return []
    binaries = {
        candidate
        for suffix in importlib.machinery.EXTENSION_SUFFIXES
        for candidate in directory.glob(f"assign[0-9]*{suffix}")
    }
    return sorted(binaries, key=lambda p: (_log_index(p), p.name), reverse=True)


def _import_cpg_module(binary: Path) -> ModuleType | None:
    if not binary.is_file():
        return None

    previous = sys.modules.pop(_MODULE_NAME, None)
    try:
        spec = importlib.util.spec_from_file_location(_MODULE_NAME, binary)
        if spec is None or spec.loader is None:
            return None
        module = importlib.util.module_from_spec(spec)
        sys.modules[_MODULE_NAME] = module
        spec.loader.exec_module(module)
        return module
    except Exception as ex:
        logger.debug(f"Unable to import CVXPYGEN module from {binary}: {ex}")
        sys.modules.pop(_MODULE_NAME, None)
        if previous is not None:
            sys.modules[_MODULE_NAME] = previous

    return None


def _load_compiled_solver_for_log(cpg_root: Path, log_n: int) -> tuple[ModuleType, int, str] | None:
    problem_name = f"assign{log_n}"
    for binary in _assign_binaries(cpg_root):
        match = _PROBLEM_PATTERN.search(binary.name)
        if not match or int(match.group(1)) != log_n:
            continue
        module = _import_cpg_module(binary)
        if module is None:
            continue
        if not hasattr(module, f"{problem_name}_cpg_params"):
            continue
        return module, 2**log_n, problem_name
    return None


def _archive_solver_logs(cpg_root: Path) -> tuple[int, ...]:
    archive_path = cpg_root / _ARCHIVE_NAME
    if not archive_path.is_file():
        return ()

    logs: set[int] = set()
    suffixes = tuple(importlib.machinery.EXTENSION_SUFFIXES)
    try:
        with tarfile.open(archive_path, mode="r:xz") as archive:
            for member in archive.getmembers():
                if not member.isfile():
                    continue
                name = Path(member.name).name
                if not name.endswith(suffixes):
                    continue
                if match := _PROBLEM_PATTERN.search(name):
                    logs.add(int(match.group(1)))
    except Exception as ex:
        logger.warning(f"Failed to inspect CVXPYGEN archive {archive_path}: {ex}")
        return ()

    return tuple(sorted(logs))


def _ensure_compiled_binary_for_log(cpg_root: Path, log_n: int) -> None:
    for binary in _assign_binaries(cpg_root):
        if match := _PROBLEM_PATTERN.search(binary.name):
            if int(match.group(1)) == log_n:
                return

    archive_path = cpg_root / _ARCHIVE_NAME
    if not archive_path.is_file():
        return

    suffixes = tuple(importlib.machinery.EXTENSION_SUFFIXES)
    extracted = 0
    try:
        with tarfile.open(archive_path, mode="r:xz") as archive:
            for member in archive.getmembers():
                if not member.isfile():
                    continue
                name = Path(member.name).name
                if not name.endswith(suffixes):
                    continue
                if not (match := _PROBLEM_PATTERN.search(name)):
                    continue
                if int(match.group(1)) != log_n:
                    continue
                source = archive.extractfile(member)
                if source is None:
                    continue
                target = cpg_root / name
                with source, target.open("wb") as sink:
                    shutil.copyfileobj(source, sink)
                extracted += 1
    except Exception as ex:
        logger.warning(f"Failed to extract CVXPYGEN archive {archive_path}: {ex}")
        return

    if extracted > 0:
        logger.info(f"Extracted {extracted} CVXPYGEN binary file(s) for assign{log_n} into {cpg_root}")


@cache
def _available_solver_logs() -> tuple[int, ...]:
    cpg_root = _cpg_root()
    logs = {
        int(match.group(1))
        for binary in _assign_binaries(cpg_root)
        if (match := _PROBLEM_PATTERN.search(binary.name))
    }
    logs.update(_archive_solver_logs(cpg_root))
    return tuple(sorted(logs))


def _required_problem_log(n: int, m: int) -> int:
    return math.ceil(math.log2(max(n, m)))


def _pick_solver_log(n: int, m: int, max_size: int) -> int | None:
    if n <= 0 or m <= 0:
        return None

    required_log = _required_problem_log(n, m)
    for log_n in _available_solver_logs():
        size = 2**log_n
        if log_n >= required_log and size <= max_size:
            return log_n
    return None


@cache
def _init_cpg_solver_for_log(log_n: int) -> CpgSolver | None:
    cpg_root = _cpg_root()
    load_result = _load_compiled_solver_for_log(cpg_root, log_n)
    if load_result is None:
        _ensure_compiled_binary_for_log(cpg_root, log_n)
        load_result = _load_compiled_solver_for_log(cpg_root, log_n)
    if load_result is None:
        logger.debug(f"No CVXPYGEN binary found for assign{log_n} in {cpg_root}.")
        return None

    module, problem_size, problem_name = load_result
    solver = CpgSolver(module, problem_size, problem_name)
    logger.info(f"Using CVXPYGEN assignment solver {problem_name} with size {problem_size}x{problem_size}")
    return solver


def get_cpg_solver(n: int, m: int, max_size: int) -> CpgSolver | None:
    if (log_n := _pick_solver_log(n, m, max_size)) is None:
        return None
    return _init_cpg_solver_for_log(log_n)

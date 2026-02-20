import importlib.machinery
import importlib.util
import re
import sys
from functools import cache
from pathlib import Path
from types import ModuleType

import numpy as np
from loguru import logger

_MODULE_NAME = "cpg_module"
_BLOCKED_COST = 1e6
_INTEGER_TOL = 1e-4


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

    def can_solve(self, n: int, m: int, max_size: int) -> bool:
        return n <= self.problem_size and m <= self.problem_size and self.problem_size <= max_size

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

        self._params.w = padded.ravel()
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
        if result.cpg_info.status != "solved":
            raise RuntimeError(f"CVXPYGEN solve failed: {result.cpg_info.status}")

        x = np.asarray(result.cpg_prim.x, dtype=float).reshape(self.problem_size, self.problem_size, order="F")
        rounded = np.rint(x)
        x = np.where(np.abs(x - rounded) <= _INTEGER_TOL, rounded, x)
        return x[:n, :m]


def _repo_bin_root() -> Path | None:
    here = Path(__file__).resolve()
    for parent in here.parents:
        candidate = parent / "bin"
        if candidate.is_dir():
            return candidate
    return None


def _import_cpg_module(path: Path) -> ModuleType | None:
    def _candidates(directory: Path) -> list[Path]:
        def _log_index(p: Path) -> int:
            match = re.search(r"harvest(\d+)", p.name)
            if match:
                return int(match.group(1))
            return -1

        ext_candidates = sorted(
            {
                candidate
                for suffix in importlib.machinery.EXTENSION_SUFFIXES
                for candidate in directory.glob(f"*{suffix}")
            }
        )
        candidates = sorted((p for p in ext_candidates if p.name.startswith("harvest")), key=_log_index, reverse=True)
        if candidates:
            return candidates
        candidates = sorted((p for p in ext_candidates if p.name.startswith("cpg_module")), key=lambda p: p.name)
        if candidates:
            return candidates
        return ext_candidates

    if path.is_file():
        binaries = [path]
    elif path.is_dir():
        binaries = _candidates(path)
    else:
        return None

    for binary in binaries:
        previous = sys.modules.pop(_MODULE_NAME, None)
        try:
            spec = importlib.util.spec_from_file_location(_MODULE_NAME, binary)
            if spec is None or spec.loader is None:
                continue
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


def _load_from_single_folder(bin_root: Path) -> tuple[ModuleType, int, str] | None:
    cpg_dir = bin_root / "cpg"
    module = _import_cpg_module(cpg_dir)
    if module is None:
        return None

    problem_size = None
    for name in dir(module):
        if match := re.fullmatch(r"harvest(\d+)_cpg_params", name):
            problem_size = 2 ** int(match.group(1))
            break
    if problem_size is None:
        return None

    return module, problem_size, f"harvest{int(np.log2(problem_size))}"


def _load_from_legacy_folders(bin_root: Path) -> tuple[ModuleType, int, str] | None:
    candidates = sorted(bin_root.glob("harvest[0-9]*"), reverse=True)
    for folder in candidates:
        match = re.fullmatch(r"harvest(\d+)", folder.name)
        if not match:
            continue
        log_n = int(match.group(1))
        module = _import_cpg_module(folder)
        if module is None:
            continue
        if not hasattr(module, f"harvest{log_n}_cpg_params"):
            continue
        return module, 2**log_n, f"harvest{log_n}"
    return None


@cache
def _init_cpg_solver() -> CpgSolver | None:
    bin_root = _repo_bin_root()
    if bin_root is None:
        return None

    load_result = _load_from_single_folder(bin_root) or _load_from_legacy_folders(bin_root)
    if load_result is None:
        logger.debug("No CVXPYGEN binary found. Falling back to highspy assignment solver.")
        return None

    module, problem_size, problem_name = load_result
    solver = CpgSolver(module, problem_size, problem_name)
    logger.info(f"Using CVXPYGEN assignment solver {problem_name} with size {problem_size}x{problem_size}")
    return solver


def get_cpg_solver() -> CpgSolver | None:
    return _init_cpg_solver()

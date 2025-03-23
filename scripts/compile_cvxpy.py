import os
import shutil
import sys
import tempfile
from glob import glob
from itertools import product

import cvxpy as cp
from cvxpygen import cpg

sys.path.append("ares-sc2/src/ares")
sys.path.append("ares-sc2/src")
sys.path.append("ares-sc2")

SOLVER = "ECOS"
SOLVER_OPTIONS = dict(
    time_limit=10e-3,
)

if __name__ == "__main__":
    output_dir = "bin"

    # with tempfile.TemporaryDirectory() as temp_dir:
    temp_dir = "bin/assign/"
    os.makedirs(temp_dir, exist_ok=True)
    for n, m in product(range(1, 10), range(1, 10)):
        x = cp.Variable((n, m), "x")
        w = cp.Parameter((n, m), name="w")
        b = cp.Parameter(m, name="b")
        gw = cp.Parameter(m, name="gw")
        g = cp.Parameter(1, name="g")
        t = cp.Parameter(n, name="t")

        objective = cp.Minimize(cp.vdot(w, x))
        constraints = [
            cp.sum(x, 0) <= b,  # enforce even distribution
            cp.sum(x, 1) == t,
            cp.vdot(cp.sum(x, 0), gw) == g,
            0 <= x,
        ]
        problem = cp.Problem(objective, constraints)

        problem_name = f"assign_{n}_{m}"
        problem_dir = f"{temp_dir}/{problem_name}"
        try:
            cpg.generate_code(
                problem,
                code_dir=problem_dir,
                prefix=problem_name,
                solver="ECOS",
                # solver_opts=SOLVER_OPTIONS
            )
        except ModuleNotFoundError:
            pass
        for file in glob(f"{problem_dir}/cpg_module.*"):
            output_path = f"{output_dir}/{problem_name}/{os.path.basename(file)}"
            os.makedirs(os.path.dirname(output_path), exist_ok=True)
            shutil.move(file, output_path)

import glob
import math
import os
import pathlib
import platform
import shutil
import subprocess
import sys
import tempfile

import click
import cvxpy as cp
import numpy as np

from cvxpygen import cpg


def compile_problem(n, m, code_dir):
    x = cp.Variable((n, m), "x")
    w = cp.Parameter((n, m), name="w")
    b = cp.Parameter(m, name="b")

    objective = cp.Minimize(cp.vdot(w, x))
    constraints = [
        cp.sum(x, 0) <= b,
        cp.sum(x, 1) == 1,
        0 <= x,
    ]
    problem = cp.Problem(objective, constraints)

    cpg.generate_code(
        problem,
        code_dir=code_dir,
        prefix=os.path.basename(code_dir),
        wrapper=False,
        solver="ECOS",
    )

    try:
        print(
            subprocess.check_output(
                [sys.executable, "setup.py", "--quiet", "build_ext", "--inplace"],
                cwd=code_dir,
            )
        )
    except subprocess.CalledProcessError as exc:
        print("Status : FAIL", exc.returncode, exc.output)


def cleanup_problem(problem_dir: str) -> None:
    shutil.rmtree(os.path.join(problem_dir, "build"))
    shutil.rmtree(os.path.join(problem_dir, "c"))
    shutil.rmtree(os.path.join(problem_dir, "cpp"))


@click.command()
@click.option("--output-dir", default="phantom/cvxpygen/assign")
@click.option("--prefix", default="assign")
def main(output_dir: str, prefix: str):
    os.makedirs(output_dir, exist_ok=True)
    for log_n in np.arange(3, 7, 0.5):
        n = m = int(2**log_n)
        problem_name = f"{prefix}_{n}_{m}"
        problem_dir = os.path.join(output_dir, problem_name)
        compile_problem(n, m, problem_dir)
        cleanup_problem(problem_dir)


if __name__ == "__main__":
    main()

import os
import shutil

from setuptools.command.build_ext import build_ext
from setuptools import Distribution, Extension

import numpy as np
from Cython.Build import cythonize


def build():
    input_dir = os.path.join("phantom", "cython")
    include_dirs = [np.get_include()]
    extension = Extension(
        name="cy_dijkstra",
        sources=[os.path.join(input_dir, "dijkstra.pyx")],
        include_dirs=include_dirs,
        # language="c++",
        # extra_compile_args=["-std=c++11"],
        # extra_link_args=["-std=c++11"],
    )
    # extension.cython_c_in_temp = True
    extensions = cythonize(
        extension,
        compiler_directives={"binding": True, "language_level": 3},
    )

    distribution = Distribution({"name": "extended", "ext_modules": extensions})

    cmd = build_ext(distribution)
    cmd.ensure_finalized()
    cmd.run()

    # Copy built extensions back to the project
    for output in cmd.get_outputs():
        relative_extension = os.path.relpath(output, cmd.build_lib)
        output_path = os.path.join(input_dir, relative_extension)
        shutil.copyfile(output, output_path)
        mode = os.stat(output_path).st_mode
        mode |= (mode & 0o444) >> 2
        os.chmod(output_path, mode)

    shutil.rmtree("build")


if __name__ == "__main__":
    build()

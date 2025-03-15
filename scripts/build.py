"""
Zips the relevant files and directories so that Bot can be updated
to ladder or tournaments.
TODO: check all files and folders are present before zipping
"""

import os
import pathlib
import platform
import shutil
import sys
import tempfile
import zipfile
from importlib.util import find_spec
from io import BytesIO
from os import path, remove, walk
from typing import Callable
import requests
import subprocess

OUTPUT_DIR = "out"
PYTHON_VERSION = f"{sys.version_info.major}.{sys.version_info.minor}"
EXCLUDE = list[str]()
FILETYPES_TO_IGNORE = list[str]()
ROOT_DIRECTORY = "./"
FETCH_ZIP = dict[str, str]()
ZIP_FILES: list[str] = [
    "run.py",
    "requirements.txt",
]
ZIP_DIRECTORIES: dict[str, str | None] = {
    "src": "src",
    "scripts": "scripts",
    "ares-sc2/src/ares": "lib/ares",
    "ares-sc2/sc2_helper": "lib/sc2_helper",
}
ZIP_MODULES: list[str] = [
    # "ares-sc2",
    "cvxpy",
    "_cvxcore",
    "cvxpygen",
    "sc2",
    "map_analyzer",
    "ecos",
    "_ecos",
    # "scs",
    # "_scs_direct",
    # "osqp",
    # "qdldl",
]

FILETYPES_TO_IGNORE.append(".c")
FILETYPES_TO_IGNORE.append(".pyc")
FILETYPES_TO_IGNORE.append(".pyi")
FILETYPES_TO_IGNORE.append(".pyx")
FILETYPES_TO_IGNORE.append("-darwin.so")
FILETYPES_TO_IGNORE.append(".xz")
if platform.system() == "Windows":
    FILETYPES_TO_IGNORE.append(".so")
    CYTHON_EXTENSION_VERSION = "windows"
else:
    FILETYPES_TO_IGNORE.append(".pyd")
    CYTHON_EXTENSION_VERSION = "ubuntu"

CYTHON_EXTENSION_RELEASE = "https://github.com/AresSC2/cython-extensions-sc2/releases/latest/download"
FETCH_ZIP[f"{CYTHON_EXTENSION_RELEASE}/{CYTHON_EXTENSION_VERSION}-latest_python{PYTHON_VERSION}.zip"] = "lib"

IGNORE_PATTERNS = shutil.ignore_patterns(*["*" + ext for ext in FILETYPES_TO_IGNORE])

def copyfile(src, dst):
    if any(src.endswith(ext) for ext in FILETYPES_TO_IGNORE):
        return
    shutil.copyfile(src, dst)

def copytree(src, dst):
    shutil.copytree(src, dst, dirs_exist_ok=True, ignore=IGNORE_PATTERNS)


if __name__ == "__main__":

    output_dir = OUTPUT_DIR
    if path.exists(output_dir):
        shutil.rmtree(output_dir)
    os.mkdir(output_dir)
    os.mkdir(path.join(output_dir, "lib"))

    # save version
    commit_hash = subprocess.check_output(['git', 'rev-parse', 'HEAD']).decode('ascii').strip()
    with open(path.join(output_dir, "version.txt"), "w") as f:
        f.write(commit_hash)

    # write directories to the zipfile
    for directory, dst in ZIP_DIRECTORIES.items():
        target = path.join(output_dir, dst or directory)
        print(f"Copying {directory=} to {target=}...")
        # os.makedirs(target, exist_ok=True)
        copytree(directory, target)

    # write individual files
    for single_file in ZIP_FILES:
        print(f"Copying {single_file=}...")
        if path.isfile(single_file):
            copyfile(single_file, path.join(output_dir, single_file))
        else:
            print(f"File not found")

    for module in ZIP_MODULES:
        print(f"Copying {module=}...")
        target = path.join(output_dir, "lib")
        spec = find_spec(module)
        module_file = spec.origin or f"{spec.submodule_search_locations[0]}/__init__.py"

        if module_file.endswith((".pyd", ".so")):
            copyfile(module_file, path.join(target, path.basename(module_file)))
        else:
            module_dir = os.path.dirname(module_file)
            module_target = os.path.join(target, module)
            copytree(module_dir, module_target)

    print("Fixing CVXPY import...")
    core_path = path.join(output_dir, "lib", "cvxpy", "cvxcore", "python", "cvxcore.py")
    with open(core_path) as fi:
        src_in = fi.read()
    src_out = src_in.replace("from . import _cvxcore", "import _cvxcore")
    with open(core_path, "w") as fo:
        fo.write(src_out)

    for url, dst in FETCH_ZIP.items():
        print(f"Fetching {url=} to {dst=}...")
        with tempfile.TemporaryDirectory() as tmp:
            r = requests.get(url)
            z = zipfile.ZipFile(BytesIO(r.content))
            z.extractall(tmp)
            copytree(tmp,  path.join(output_dir, dst))

"""
Zips the relevant files and directories so that Bot can be updated
to ladder or tournaments.
TODO: check all files and folders are present before zipping
"""

import glob
import os
import platform
import shutil
import sys
import tempfile
import urllib.request
import zipfile
from importlib.util import find_spec
from io import BytesIO
import subprocess

OUTPUT_DIR = "out"
PYTHON_VERSION = f"{sys.version_info.major}.{sys.version_info.minor}"
EXCLUDE = list[str]()
FILETYPES_TO_IGNORE = list[str]()
INCLUDE_ZIP = list[str]()
FETCH_ZIP = list[str]()
ZIP_ITEMS: dict[str, str] = {
    # os.path.join("scripts", "run_ladder.py"): "run.py",
    # os.path.join("scripts", "run_local.py"): "run_local.py",
    # os.path.join("scripts", "run_test.py"): "run_test.py",
}
ZIP_MODULES: list[str] = [
    "cvxpy",
    "_cvxcore",
    "cvxpygen",
    "sc2",
    "map_analyzer",
    "ecos",
    "_ecos",
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
FETCH_ZIP.append(f"{CYTHON_EXTENSION_RELEASE}/{CYTHON_EXTENSION_VERSION}-latest_python{PYTHON_VERSION}.zip")

IGNORE_PATTERNS = shutil.ignore_patterns(*["*" + ext for ext in FILETYPES_TO_IGNORE])


def copyfile(src, dst):
    if any(src.endswith(ext) for ext in FILETYPES_TO_IGNORE):
        return
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    shutil.copyfile(src, dst)


def copytree(src, dst):
    shutil.copytree(src, dst, dirs_exist_ok=True, ignore=IGNORE_PATTERNS)


if __name__ == "__main__":
    output_dir = OUTPUT_DIR
    if os.path.exists(output_dir):
        shutil.rmtree(output_dir)
    os.mkdir(output_dir)

    subprocess.Popen(["poetry", "build", "--clean", "--format", "wheel", "--output", output_dir]).wait()
    for wheel in glob.glob(os.path.join(output_dir, "*.whl")):
        with zipfile.ZipFile(wheel) as z:
            z.extractall(output_dir)
        os.remove(wheel)

    print("Creating requirements.txt...")
    requirements_path = os.path.join(output_dir, "requirements.txt")
    with open(requirements_path, "wt") as f:
        subprocess.Popen(["poetry", "export", "--without-hashes", "--format=requirements.txt"], stdout=f).wait()

    for wheel in glob.glob(os.path.join("dist", "*.whl")):
        with zipfile.ZipFile(wheel) as z:
            z.extractall(output_dir)

    commit_hash = subprocess.check_output(["git", "rev-parse", "HEAD"]).decode("ascii").strip()
    version_file = "version.txt"
    print(f"Copying {commit_hash=} to {version_file=}...")
    with open(os.path.join(output_dir, version_file), "w") as f:
        f.write(commit_hash)

    print("Copying __init__.py...")
    open(os.path.join(output_dir, "__init__.py"), "a").close()

    print("Copying files...")
    for src, dst in ZIP_ITEMS.items():
        target = os.path.join(output_dir, dst)
        if os.path.isdir(src):
            print(f"Copying directory {src=} to {target=}...")
            copytree(src, target)
        elif os.path.isfile(src):
            print(f"Copying file {src=} to {target=}...")
            copyfile(src, target)
        else:
            print("Not found, skipping.")

    print("Copying modules...")
    for module in ZIP_MODULES:
        print(f"Copying {module=}")
        target = output_dir
        spec = find_spec(module)
        module_file = spec.origin
        print(f"Copying {module_file=} to {target=}...")
        if module_file.endswith((".pyd", ".so")):
            copyfile(module_file, os.path.join(target, os.path.basename(module_file)))
        else:
            copytree(os.path.dirname(module_file), os.path.join(target, module))

    print("Fixing CVXPY import...")
    core_path = os.path.join(output_dir, "cvxpy", "cvxcore", "python", "cvxcore.py")
    with open(core_path) as fi:
        src_in = fi.read()
    src_out = src_in.replace("from . import _cvxcore", "import _cvxcore")
    with open(core_path, "w") as fo:
        fo.write(src_out)

    print("Fetching URLs...")
    for url in FETCH_ZIP:
        target = output_dir
        print(f"Fetching {url=} to {target=}...")
        with tempfile.TemporaryDirectory() as tmp:
            r = urllib.request.urlopen(url).read()
            with zipfile.ZipFile(BytesIO(r)) as z:
                z.extractall(tmp)
            copytree(tmp, target)

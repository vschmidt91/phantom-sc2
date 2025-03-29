"""
Zips the relevant files and directories so that Bot can be updated
to ladder or tournaments.
TODO: check all files and folders are present before zipping
"""

import fnmatch
import glob
import os
import platform
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.request
import zipfile
from importlib.util import find_spec
from io import BytesIO

import click

PYTHON_VERSION = f"{sys.version_info.major}.{sys.version_info.minor}"
IGNORE_GLOBS = list[str]()
FETCH_ZIP = list[str]()
ZIP_MODULES: list[str] = [
    "cvxpy",
    "_cvxcore",
    "cvxpygen",
    "sc2",
    "map_analyzer",
    "ecos",
    "_ecos",
]

IGNORE_GLOBS.append("*.c")
IGNORE_GLOBS.append("*__pycache__")
IGNORE_GLOBS.append("*.pyc")
IGNORE_GLOBS.append("*.pyi")
IGNORE_GLOBS.append("*.pyx")
IGNORE_GLOBS.append("*-darwin.so")
IGNORE_GLOBS.append("*.xz")
IGNORE_GLOBS.append("*.dist-info")
if platform.system() == "Windows":
    IGNORE_GLOBS.append("**/*.so")
    CYTHON_EXTENSION_VERSION = "windows"
else:
    IGNORE_GLOBS.append("*.pyd")
    CYTHON_EXTENSION_VERSION = "ubuntu"

CYTHON_EXTENSION_RELEASE = "https://github.com/AresSC2/cython-extensions-sc2/releases/latest/download"
FETCH_ZIP.append(f"{CYTHON_EXTENSION_RELEASE}/{CYTHON_EXTENSION_VERSION}-latest_python{PYTHON_VERSION}.zip")

IGNORE_PATTERNS = shutil.ignore_patterns(*IGNORE_GLOBS)
IGNORE_REGEXES = [re.compile(fnmatch.translate(p)) for p in IGNORE_GLOBS]


def should_ignore(p):
    return any(r.match(p) for r in IGNORE_REGEXES)


def copyfile(src, dst):
    if should_ignore(src):
        print(f"Skipping {src}")
    else:
        print(f"Copying file {src=} to {dst=}")
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copyfile(src, dst)


def copytree(src, dst):
    if should_ignore(src):
        print(f"Skipping {src}")
    else:
        print(f"Copying directory {src=} to {dst=}")
        shutil.copytree(src, dst, dirs_exist_ok=True, ignore=IGNORE_PATTERNS)


def extract(z: zipfile.ZipFile, dst):
    members = [name for name in z.namelist() if not should_ignore(name)]
    z.extractall(dst, members=members)


@click.command()
@click.argument("output_dir", type=click.Path())
def main(output_dir: str) -> None:
    if os.path.exists(output_dir):
        shutil.rmtree(output_dir)
    os.mkdir(output_dir)

    subprocess.Popen(["poetry", "build", "--clean", "--format", "wheel", "--output", output_dir]).wait()
    for wheel in glob.glob(os.path.join(output_dir, "*.whl")):
        with zipfile.ZipFile(wheel) as z:
            extract(z, output_dir)
        os.remove(wheel)

    print("Creating requirements.txt")
    requirements_path = os.path.join(output_dir, "requirements.txt")
    with open(requirements_path, "wt") as f:
        subprocess.Popen(["poetry", "export", "--without-hashes", "--format=requirements.txt"], stdout=f).wait()

    commit_hash = subprocess.check_output(["git", "rev-parse", "HEAD"]).decode("ascii").strip()
    version_file = "version.txt"
    print(f"Writing {commit_hash=} to {version_file=}")
    with open(os.path.join(output_dir, version_file), "w") as f:
        f.write(commit_hash)

    print("Creating __init__.py")
    open(os.path.join(output_dir, "__init__.py"), "a").close()

    for module in ZIP_MODULES:
        target = output_dir
        spec = find_spec(module)
        module_file = spec.origin
        if module_file.endswith((".pyd", ".so")):
            copyfile(module_file, os.path.join(target, os.path.basename(module_file)))
        else:
            copytree(os.path.dirname(module_file), os.path.join(target, module))

    print("Fixing CVXPY import")
    core_path = os.path.join(output_dir, "cvxpy", "cvxcore", "python", "cvxcore.py")
    with open(core_path) as fi:
        src_in = fi.read()
    src_out = src_in.replace("from . import _cvxcore", "import _cvxcore")
    with open(core_path, "w") as fo:
        fo.write(src_out)

    for url in FETCH_ZIP:
        target = output_dir
        print(f"Fetching {url=} to {target=}")
        with tempfile.TemporaryDirectory() as tmp:
            r = urllib.request.urlopen(url).read()
            with zipfile.ZipFile(BytesIO(r)) as z:
                z.extractall(tmp)
            copytree(tmp, target)


if __name__ == "__main__":
    main()

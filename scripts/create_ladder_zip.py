"""
Zips the relevant files and directories so that Bot can be updated
to ladder or tournaments.
TODO: check all files and folders are present before zipping
"""

import os
import pathlib
import platform
import shutil
import tempfile
import zipfile
from importlib.util import find_spec
from os import path, remove, walk
from typing import Callable
from urllib import request

ZIPFILE_NAME: str = "bot.zip"
EXCLUDE = list[str]()
FILETYPES_TO_IGNORE = list[str]()
ROOT_DIRECTORY = "./"
ZIP_INCLUDE = dict[str, tuple[str, str]]()
ZIP_FILES: list[str] = [
    "ladder.py",
    "run.py",
    "version.txt",
]
ZIP_DIRECTORIES: dict[str, str | None] = {
    "src": None,
    "ares-sc2/src/ares": "lib",
    "ares-sc2/sc2_helper": "lib",
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

if platform.system() == "Windows":
    EXCLUDE.append("map_analyzer\\pickle_gameinfo")
    FILETYPES_TO_IGNORE.extend((".c", ".so", "pyx", "pyi"))
    ZIP_INCLUDE[
        "https://github.com/AresSC2/cython-extensions-sc2/releases/download/v0.5.0/windows-latest_python3.12.zip"
    ] = (
        "cython_extensions",
        "lib",
    )
else:
    EXCLUDE.append("map_analyzer/pickle_gameinfo")
    FILETYPES_TO_IGNORE.extend((".c", ".pyd", "pyx", "pyi"))
    ZIP_INCLUDE[
        "https://github.com/AresSC2/cython-extensions-sc2/releases/download/v0.5.0/ubuntu-latest_python3.12.zip"
    ] = (
        "cython_extensions",
        "lib",
    )


def fix_cvxpy_import(module_dir: str) -> None:
    core_path = pathlib.Path(module_dir) / "cvxcore" / "python" / "cvxcore.py"
    with open(core_path) as fi:
        src_in = fi.read()
    src_out = src_in.replace("from . import _cvxcore", "import _cvxcore")
    with open(core_path, "w") as fo:
        fo.write(src_out)


MODULE_CALLBACKS: dict[str, Callable] = {
    "cvxpy": fix_cvxpy_import,
}


def zip_dir(dir_path, zip_file, prefix: str | None = None):
    """
    Will walk through a directory recursively and add all folders and files to zipfile
    @param dir_path:
    @param zip_file:
    @return:
    """
    base_path = path.join(dir_path, "..")
    for root, _, files in walk(dir_path):
        if any(exclude in root for exclude in EXCLUDE):
            continue
        for file in files:
            if file.lower().endswith(tuple(FILETYPES_TO_IGNORE)):
                continue
            target_path = path.relpath(path.join(root, file), base_path)
            if prefix:
                target_path = path.join(prefix, target_path)
            zip_file.write(
                path.join(root, file),
                target_path,
            )


def zip_module(module_name, zip_file):
    """
    Will determine the installation location of a module and copy it to zipfile
    @param module_name: module to include in the zip
    @param zip_file: output file
    @return:
    """
    spec = find_spec(module_name)
    module_file = spec.origin or f"{spec.submodule_search_locations[0]}/__init__.py"

    if module_file.endswith((".pyd", ".so")):
        zip_file.write(module_file, os.path.join("lib", path.basename(module_file)))
    else:
        module_dir = os.path.dirname(module_file)
        if callback := MODULE_CALLBACKS.get(module_name):
            print(f"Running callback {callback.__name__}")
            with tempfile.TemporaryDirectory() as temp_file:
                temp_dir = os.path.join(temp_file, module_name)
                shutil.copytree(module_dir, temp_dir)
                callback(temp_dir)
                zip_dir(temp_dir, zip_file, "lib")
        else:
            zip_dir(module_dir, zip_file, "lib")


def zip_url(url, zip_file, target, subdir=None):
    data = request.urlopen(url).read()
    with tempfile.TemporaryDirectory() as tmp:
        tmp_zip = f"{tmp}/data.zip"
        with open(tmp_zip, "wb") as f:
            f.write(data)
        src_path = f"{tmp}/out"
        with zipfile.ZipFile(tmp_zip) as f:
            f.extractall(src_path)
        if subdir:
            src_path = path.join(src_path, subdir)
        zip_dir(src_path, zip_file, target)


def zip_files_and_directories(zipfile_name: str) -> None:
    """
    @return:
    """

    path_to_zipfile = path.join(ROOT_DIRECTORY, zipfile_name)
    # if the zip file already exists remove it
    if path.isfile(path_to_zipfile):
        remove(path_to_zipfile)
    # create a new zip file
    zip_file = zipfile.ZipFile(path_to_zipfile, "w", zipfile.ZIP_DEFLATED)

    # write directories to the zipfile
    for directory, dst in ZIP_DIRECTORIES.items():
        print(f"Zipping directory {directory} to {dst}...")
        zip_dir(path.join(ROOT_DIRECTORY, directory), zip_file, dst)

    # write individual files
    for single_file in ZIP_FILES:
        _path: str = path.join(ROOT_DIRECTORY, single_file)
        if path.isfile(_path):
            print(f"Zipping file {single_file}...")
            zip_file.write(_path, single_file)

    for module in ZIP_MODULES:
        print(f"Zipping module {module}...")
        zip_module(module, zip_file)

    for url, (src, dst) in ZIP_INCLUDE.items():
        print(f"Zipping URL {url}/{src} to {dst}...")
        zip_url(url, zip_file, dst, src)

    # close the zip file
    zip_file.close()


if __name__ == "__main__":

    zipfile_name = ZIPFILE_NAME
    print(f"Zipping files and directories to {zipfile_name}...")
    zip_files_and_directories(zipfile_name)
    print("Ladder zip complete.")

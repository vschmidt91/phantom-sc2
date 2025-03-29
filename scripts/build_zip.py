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
from utils import CommandWithConfigFile


@click.command(cls=CommandWithConfigFile("config"))
@click.option("--config")
@click.argument("input-dir", type=click.Path())
@click.option("--output-path", default="bot.zip", type=click.Path())
@click.option("--zip-modules", multiple=True)
@click.option("--zip-archives", multiple=True)
@click.option("--zip-urls", multiple=True)
@click.option("--exclude", multiple=True)
def main(
    config,
    input_dir: str,
    output_path: str,
    zip_modules: list[str],
    zip_archives: list[str],
    zip_urls: list[str],
    exclude: list[str],
) -> None:
    for archive_pattern in zip_archives:
        for archive in glob.glob(os.path.join(input_dir, archive_pattern)):
            print(f"Extracting {archive=} to {input_dir=}")
            with zipfile.ZipFile(archive) as z:
                z.extractall(input_dir)

    print("Creating requirements.txt")
    requirements_path = os.path.join(input_dir, "requirements.txt")
    with open(requirements_path, "wt") as f:
        subprocess.Popen(["poetry", "export", "--without-hashes", "--format=requirements.txt"], stdout=f).wait()

    commit_hash = subprocess.check_output(["git", "rev-parse", "HEAD"]).decode("ascii").strip()
    version_file = "version.txt"
    print(f"Writing {commit_hash=} to {version_file=}")
    with open(os.path.join(input_dir, version_file), "w") as f:
        f.write(commit_hash)

    print("Creating __init__.py")
    open(os.path.join(input_dir, "__init__.py"), "a").close()

    for module in zip_modules:
        target = input_dir
        spec = find_spec(module)
        module_file = spec.origin
        if module_file.endswith((".pyd", ".so")):
            print(f"Copying {module_file=} to {target=}")
            shutil.copyfile(module_file, os.path.join(target, os.path.basename(module_file)))
        else:
            module_dir = os.path.dirname(module_file)
            print(f"Copying {module_dir=} to {target=}")
            shutil.copytree(module_dir, os.path.join(target, module))

    print("Fixing CVXPY import")
    core_path = os.path.join(input_dir, "cvxpy", "cvxcore", "python", "cvxcore.py")
    with open(core_path) as fi:
        src_in = fi.read()
    src_out = src_in.replace("from . import _cvxcore", "import _cvxcore")
    with open(core_path, "w") as fo:
        fo.write(src_out)

    for url in zip_urls:
        target = input_dir
        print(f"Fetching {url=} to {target=}")
        with tempfile.TemporaryDirectory() as tmp:
            r = urllib.request.urlopen(url).read()
            with zipfile.ZipFile(BytesIO(r)) as z:
                z.extractall(tmp)
            shutil.copytree(tmp, target, dirs_exist_ok=True)

    exclude_compiled = [re.compile(fnmatch.translate(p)) for p in exclude]
    with zipfile.ZipFile(output_path, "w", compression=zipfile.ZIP_LZMA) as zf:
        for dirname, subdirs, files in os.walk(input_dir):
            for filename in files:
                filepath = os.path.join(dirname, filename)
                if any(r.match(filepath) for r in exclude_compiled):
                    print(f"Excluding {filepath=}")
                    continue
                dst = os.path.join(os.path.relpath(dirname, input_dir), filename)
                print(f"Zipping {filepath=} to {dst=}")
                zf.write(filepath, dst)


if __name__ == "__main__":
    main()

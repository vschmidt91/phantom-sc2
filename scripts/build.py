import glob
import os
import shutil
import subprocess
import tempfile
import urllib.request
import zipfile
from importlib.util import find_spec
from io import BytesIO

import click
from compile_cython import compile_cython
from utils import CommandWithConfigFile


@click.command(cls=CommandWithConfigFile("config"))
@click.option("--config", type=click.File("rb"))
@click.option("--output-path", type=click.Path())
@click.option("--zip-modules", multiple=True)
@click.option("--zip-urls", multiple=True)
@click.option("--exclude", multiple=True)
def main(
    config,
    output_path: str,
    zip_modules: list[str],
    zip_urls: list[str],
    exclude: list[str],
) -> None:
    compile_cython()

    shutil.rmtree(output_path, ignore_errors=True)
    os.makedirs(output_path, exist_ok=True)

    with tempfile.TemporaryDirectory() as tmp_dir:
        subprocess.Popen(["poetry", "build", "--format", "wheel", "--output", tmp_dir]).wait()
        wheels = glob.glob(os.path.join(tmp_dir, "*.whl"))
        for wheel in wheels:
            print(f"Extracting {wheel=}")
            with zipfile.ZipFile(wheel) as z:
                z.extractall(output_path)

    print("Creating requirements.txt")
    requirements_path = os.path.join(output_path, "requirements.txt")
    with open(requirements_path, "w") as f:
        subprocess.Popen(["poetry", "export", "--without-hashes", "--format=requirements.txt"], stdout=f).wait()

    print("Creating __init__.py")
    open(os.path.join(output_path, "__init__.py"), "a").close()

    commit_hash = subprocess.check_output(["git", "rev-parse", "HEAD"]).decode("ascii").strip()
    version_file = "version.txt"
    print(f"Writing {commit_hash=} to {version_file=}")
    with open(os.path.join(output_path, version_file), "w") as f:
        f.write(commit_hash)

    for module in zip_modules:
        target = output_path
        spec = find_spec(module)
        module_file = spec.origin
        if module_file.endswith((".pyd", ".so")):
            print(f"Copying {module_file=}")
            shutil.copyfile(module_file, os.path.join(target, os.path.basename(module_file)))
        else:
            module_dir = os.path.dirname(module_file)
            print(f"Copying {module_dir=}")
            shutil.copytree(module_dir, os.path.join(target, module))

    print("Fixing CVXPY import")
    core_path = os.path.join(output_path, "cvxpy", "cvxcore", "python", "cvxcore.py")
    with open(core_path) as fi:
        src_in = fi.read()
    src_out = src_in.replace("from . import _cvxcore", "import _cvxcore")
    with open(core_path, "w") as fo:
        fo.write(src_out)

    for url in zip_urls:
        target = output_path
        print(f"Fetching {url=}")
        with tempfile.TemporaryDirectory() as tmp:
            r = urllib.request.urlopen(url).read()
            print(f"Extracting to {target=}")
            with zipfile.ZipFile(BytesIO(r)) as z:
                z.extractall(tmp)
            shutil.copytree(tmp, target, dirs_exist_ok=True)

    for pattern in exclude:
        for path in glob.glob(os.path.join(output_path, pattern), recursive=True):
            print(f"Removing {path=}")
            if os.path.isfile(path):
                os.remove(path)
            elif os.path.isdir(path):
                shutil.rmtree(path)


if __name__ == "__main__":
    main()

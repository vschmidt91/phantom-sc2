"""Copies modules into the current environment.
Used to include requirements into the bot.zip that are not installed on ladder (yet).
"""

import inspect
import importlib
import os
import shutil

MODULES = [
    "river",
]


def copy_module(name: str, path: str) -> None:
    module = importlib.import_module(name)
    module_path = os.path.dirname(inspect.getfile(module))
    module_name = os.path.basename(module_path)
    target_path = os.path.join(path, module_name)
    shutil.copytree(module_path, target_path)


if __name__ == "__main__":
    for m in MODULES:
        copy_module(m, os.getcwd())

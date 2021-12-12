
from string import Template
from dataclasses import dataclass
from typing import List, Any
from zipfile import ZipFile
import os
import zipfile
import subprocess

import src

OUTPUT_PATH = 'publish'
VERSION_PATH = 'templates/version.txt'
EXTENSIONS = { '.py', '.txt', '.json', '.npy' }
COMMON = ['__init__.py', 'requirements.txt', 'version.txt']
TEMPLATES = 'templates'

@dataclass
class BotPackage:
    name: str
    race: str
    package: src
    cls: src
    libs: List[str]

BOTS: List[BotPackage] = [
    BotPackage('SunTzuBot', 'Zerg', 'src.zerg', 'ZergAI', ['src', 'sc2', 'MapAnalyzer', 'data']),
    BotPackage('12PoolBot', 'Zerg', 'src.pool12_allin', 'Pool12AllIn', ['src', 'sc2']),
]

def zip_templates(zip_file: ZipFile, args: Any):
    for root, dirs, files in os.walk(TEMPLATES):
        for path in files:
            if path.endswith('.pyc'):
                continue
            path_abs = os.path.join(root, path)
            with open(path_abs, 'r') as file:
                template = Template(file.read())
            zip_file.writestr(path, template.substitute(args))

def zip_lib(zip_file: ZipFile, dir_name: str):
    for root, dirs, paths in os.walk(dir_name):
        for path in paths:
            if ".pyc" in path:
                continue
            path_abs = os.path.join(root, path)
            path_rel = os.path.join(dir_name, os.path.relpath(path_abs, dir_name))
            zip_file.write(path_abs, path_rel)

if __name__ == '__main__':

    version_path = VERSION_PATH
    version = subprocess.check_output('git rev-parse HEAD', shell=True).decode('utf-8')
    version = version.replace('\n', '')
    with open(version_path, 'w') as version_file:
        version_file.write(version)

    for bot in BOTS:

        path = os.path.join(OUTPUT_PATH, bot.name + '.zip')
        if os.path.exists(path):
            os.remove(path)
        zip_file = ZipFile(path, 'w', zipfile.ZIP_DEFLATED)
        zip_templates(zip_file, bot.__dict__)
        for lib in bot.libs:
            zip_lib(zip_file, lib)
        for file in COMMON:
            zip_file.write(file, file)
        zip_file.close()
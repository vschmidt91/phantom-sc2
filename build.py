
from string import Template
from dataclasses import dataclass
from typing import List, Any
from zipfile import ZipFile
import os
import zipfile
import subprocess

OUTPUT_PATH = 'publish'
VERSION_PATH = 'version.txt'
EXTENSIONS = { '.py', '.txt', '.json', '.npy' }
TEMPLATES_PATH = 'templates'

@dataclass
class BotPackage:
    name: str
    race: str
    package: str
    cls: str
    libs: List[str]

BOTS: List[BotPackage] = [
    BotPackage('Rasputin', 'Zerg', 'src.zerg', 'ZergAI',
    [
        'ladder.py',
        'requirements.txt',
        VERSION_PATH,
        'src\\',
        'sc2\\',
        'MapAnalyzer\\',
        'data\\'
    ]),
    BotPackage('PhantomBot', 'Zerg', 'src.zerg', 'ZergAI',
    [
        'ladder.py',
        'requirements.txt',
        VERSION_PATH,
        'src\\',
        'sc2\\',
        'MapAnalyzer\\',
        'data\\'
    ]),
    BotPackage('12PoolBot', 'Zerg', 'src.pool12_allin', 'Pool12AllIn',
    [
        'ladder.py',
        'requirements.txt',
        'src\\pool12_allin.py',
        'sc2\\'
    ]),
    BotPackage('LingFlood', 'Zerg', 'src.lingflood', 'LingFlood',
    [
        'ladder.py',
        'requirements.txt',
        'src\\lingflood.py',
        'sc2\\'
    ]),
]

def zip_templates(zip_file: ZipFile, args: Any):
    for root, dirs, files in os.walk(TEMPLATES_PATH):
        for path in files:
            if path.endswith('.pyc'):
                continue
            path_abs = os.path.join(root, path)
            with open(path_abs, 'r') as file:
                template = Template(file.read())
            zip_file.writestr(path, template.substitute(args))

def zip_libs(zip_file: ZipFile, libs: List[str]):
    cwd = os.getcwd()
    for root, dirs, paths in os.walk(cwd):
        for path in paths:
            if path.endswith('.pyc'):
                continue
            path_abs = os.path.join(root, path)
            path_rel = os.path.relpath(path_abs, cwd)
            if not any(path_rel.startswith(p) for p in libs):
                continue
            # path_rel = os.path.join(dir_name, os.path.relpath(path_abs, dir_name))
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
        zip_libs(zip_file, bot.libs)
        zip_file.close()
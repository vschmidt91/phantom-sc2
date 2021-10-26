
from datetime import datetime
import sc2
import inspect
import os
import zipfile
import subprocess

OUTPUT_PATH = './publish/SunTzuBot.zip'
VERSION_PATH = './version.txt'

def zipBot(zipFile):
    root = os.getcwd()
    botFiles = (
        f for f in os.listdir(root)
        if ".py" in f or ".txt" in f or ".json" in f
    )
    for file in botFiles:
        zipFile.write(os.path.join(root, file), file)


def zipLibrary(zipFile):
    libraryFile = inspect.getfile(sc2)
    libraryDir = os.path.dirname(libraryFile)
    for root, dirs, files in os.walk(libraryDir):
        for file in files:
            if ".pyc" in file:
                continue
            absPath = os.path.join(root, file)
            relPath = os.path.join("sc2", os.path.relpath(absPath, libraryDir))
            zipFile.write(absPath, relPath)

if __name__ == '__main__':

    path = OUTPUT_PATH
    if os.path.exists(path):
        os.remove(path)

    version_path = VERSION_PATH
    version = subprocess.check_output('git rev-parse HEAD', shell=True).decode('utf-8')
    version = version.replace('\n', '')
    with open(version_path, 'w') as version_file:
        version_file.write(version)

    zipFile = zipfile.ZipFile(path, 'w', zipfile.ZIP_DEFLATED)
    zipBot(zipFile)
    zipLibrary(zipFile)
    zipFile.close()
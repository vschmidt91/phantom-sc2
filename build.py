
from datetime import datetime
import sc2
import inspect
import os
import zipfile

def zipBot(zipFile):
    root = os.getcwd()
    botFiles = [
        f for f in os.listdir(root)
        if ".py" in f or ".txt" in f or ".json" in f
    ]
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
    path = 'publish/SunTzuBot.zip'
    if os.path.exists(path):
        os.remove(path)
    zipFile = zipfile.ZipFile(path, 'w', zipfile.ZIP_DEFLATED)
    zipBot(zipFile)
    zipLibrary(zipFile)
    zipFile.close()
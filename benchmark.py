import os

os.system("py -3.7 -O -m cProfile -o profile_name.prof run.py")
os.system("py -m snakeviz profile_name.prof")
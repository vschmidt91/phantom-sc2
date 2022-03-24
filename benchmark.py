import os

os.system("py -3.9 -O -m cProfile -o profile_name.prof run_local.py")
os.system("py -m snakeviz profile_name.prof")
zip:
	python scripts/compile_cython.py
	python scripts/build.py

check:
	ruff check .
	yamllint -c config/yamllint.yml .
	mypy .

fix:
	ruff check --select I --fix --unsafe-fixes .
	ruff format .

profile:
	snakeviz resources/profiling.prof
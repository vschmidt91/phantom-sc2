zip:
	poetry run python scripts/compile_cython.py
	poetry run python scripts/build.py out

check:
	poetry run ruff check .
	poetry run yamllint -c config/yamllint.yml .
	poetry run mypy .

fix:
	poetry run ruff check --select I --fix --unsafe-fixes .
	poetry run ruff format .

profile:
	poetry run snakeviz resources/profiling.prof
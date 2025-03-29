zip:
	poetry run python scripts/compile_cython.py
	poetry run python scripts/build.py

check:
	poetry run ruff check .
	poetry run mypy .

fix:
	poetry run ruff check --fix --unsafe-fixes .
	poetry run ruff format .

lint: fix check

profile:
	poetry run snakeviz resources/profiling.prof
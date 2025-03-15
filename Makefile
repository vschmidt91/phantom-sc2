check:
	poetry run ruff check src
	poetry run python -m mypy src

fix:
	poetry run ruff format src

profile:
	poetry run python -m snakeviz resources\profiling.prof
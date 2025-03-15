check:
	poetry run ruff check src scripts
	poetry run python -m mypy src

fix:
	poetry run ruff check --fix src scripts
	poetry run ruff format src scripts

profile:
	poetry run python -m snakeviz resources\profiling.prof
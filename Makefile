check:
	poetry run ruff check phantom scripts
# 	poetry run python -m mypy phantom

fix:
	poetry run ruff check --fix phantom scripts
	poetry run ruff format phantom scripts

profile:
	poetry run python -m snakeviz resources\profiling.prof
check:
	poetry run ruff check phantom scripts
	poetry run python -m mypy phantom

fix:
	poetry run ruff check --fix --unsafe-fixes phantom scripts
	poetry run ruff format phantom scripts

lint: fix check

profile:
	poetry run python -m snakeviz resources\profiling.prof
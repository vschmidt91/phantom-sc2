zip:
	poetry run python scripts/build.py --config config/build.toml

check:
	poetry run ruff check
	poetry run mypy .

fix:
	poetry run ruff check --fix --unsafe-fixes
	poetry run ruff format

profile:
	poetry run snakeviz resources/profiling.prof
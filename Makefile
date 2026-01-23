zip:
	poetry run python scripts/build.py --config config/build.toml

check: test
	poetry run ruff check phantom tests
	poetry run mypy phantom tests


fix:
	poetry run ruff check phantom tests --fix --unsafe-fixes
	poetry run ruff format phantom tests

lint: fix check

test:
	poetry run python -m unittest discover tests

profile:
	poetry run snakeviz resources/profiling.prof
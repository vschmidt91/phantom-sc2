zip:
	poetry run python scripts/build.py --config config/build.toml

check: test
	poetry run ruff check
	poetry run mypy .

fix:
	poetry run ruff check --fix --unsafe-fixes
	poetry run ruff format

lint: fix check

test:
	poetry run python -m unittest discover tests

profile:
	poetry run snakeviz resources/profiling.prof
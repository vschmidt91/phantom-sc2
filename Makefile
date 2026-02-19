zip:
	poetry run python scripts/build.py --config config/build.toml

format:
	poetry run ruff format phantom tests

format-check:
	poetry run ruff format phantom tests --check

lint:
	poetry run ruff check phantom tests

typecheck:
	poetry run mypy phantom tests

compile:
	poetry run python -m compileall phantom run.py scripts

fix:
	poetry run ruff check phantom tests --fix --unsafe-fixes
	$(MAKE) format

check: lint format-check typecheck compile

test:
	poetry run python -m unittest discover tests

ci: check test

profile:
	poetry run snakeviz resources/profiling.prof

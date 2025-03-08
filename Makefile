fix:
	poetry run python -m isort src
	poetry run python -m black src

check:
	poetry run python -m isort --check src
	poetry run python -m black --check src
	poetry run python -m flake8 src
	poetry run python -m mypy src

profile:
	poetry run python -m snakeviz resources\profiling.prof
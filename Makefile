fix:
	poetry run python -m isort src scripts
	poetry run python -m black src scripts

check:
	poetry run python -m isort --check src scripts
	poetry run python -m black --check src scripts
	poetry run python -m flake8 src scripts
	poetry run python -m mypy src scripts

profile:
	poetry run python -m snakeviz resources\profiling.prof
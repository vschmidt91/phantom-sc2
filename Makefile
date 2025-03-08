fix:
	python -m isort src
	python -m black src

check:
	python -m isort --check src
	python -m black --check src
	python -m flake8 src
	python -m mypy src

profile:
	python -m snakeviz resources\profiling.prof
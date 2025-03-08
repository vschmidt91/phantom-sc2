fix:
	isort src
	black src

check:
	isort --check src
	black --check src
	flake8 src
	mypy src

profile:
	python -m snakeviz resources\profiling.prof
lint:
	autoflake -i -r src
	isort src
	black -S src
	flake8 src
	mypy src

profile:
	python -m snakeviz resources\profiling.prof
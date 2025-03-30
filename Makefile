zip:
	poetry run python scripts/compile_cython.py
	poetry build --format wheel --output out --clean
	poetry run python scripts/build_zip.py out --config config/build.yml

check:
	poetry run ruff check
	poetry run mypy .

fix:
	poetry run ruff check --fix --unsafe-fixes
	poetry run ruff format

profile:
	poetry run snakeviz resources/profiling.prof
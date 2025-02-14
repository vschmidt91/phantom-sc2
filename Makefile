lint:
	absolufy-imports --application-directories bot
	autoflake -i -r bot
	isort bot
	black -S bot
	flake8 bot
	mypy bot

profile:
	python -m snakeviz .\profiling.prof
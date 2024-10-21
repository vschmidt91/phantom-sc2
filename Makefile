lint:
	autoflake -i -r bot
	isort bot
	black -S bot
	flake8 bot
	mypy bot

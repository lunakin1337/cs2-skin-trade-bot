.PHONY: install run lint test

install:
	pip install -e .

run:
	python -m src.bot.main

lint:
	ruff check src tests

test:
	pytest
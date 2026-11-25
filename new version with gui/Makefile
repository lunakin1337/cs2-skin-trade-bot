.PHONY: install run web migrate lint test

install:
	pip install -e ".[dev]"

run:
	python -m src.bot.main

web:
	python -m src.web_app

migrate:
	python -m src.database.migrations.migrate up

lint:
	ruff check src tests

test:
	pytest

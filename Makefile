.PHONY: install lint format test audit build clean check-all

install:
	pip install -e ".[dev]"

lint:
	ruff check .
	ruff format --check .
	mypy src/

format:
	ruff check --fix .
	ruff format .

test:
	pytest

audit:
	pip-audit

build:
	python -m build
	twine check dist/*

clean:
	rm -rf dist/ build/ *.egg-info htmlcov/ .mypy_cache/ .pytest_cache/ .ruff_cache/

check-all: lint test audit

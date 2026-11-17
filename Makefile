.PHONY: help install install-dev test test-cov lint format security clean build dist upload docs

# Default target
help:
	@echo "Enterprise Memo System - Development Commands"
	@echo ""
	@echo "Available targets:"
	@echo "  install         Install production dependencies"
	@echo "  install-dev     Install development dependencies"
	@echo "  test            Run tests"
	@echo "  test-cov        Run tests with coverage report"
	@echo "  lint            Run linters (flake8, mypy)"
	@echo "  format          Format code with black and isort"
	@echo "  security        Run security checks (bandit, pip-audit)"
	@echo "  clean           Clean build artifacts"
	@echo "  build           Build distribution packages"
	@echo "  dist            Create distribution packages"
	@echo "  upload          Upload to PyPI"
	@echo "  docs            Generate documentation"

# Installation
install:
	pip install -r requirements.txt

install-dev:
	pip install -r requirements.txt
	pip install -r requirements-dev.txt

# Testing
test:
	pytest tests/

test-cov:
	pytest tests/ --cov=. --cov-report=html --cov-report=term-missing

# Code quality
lint:
	flake8 . --count --select=E9,F63,F7,F82 --show-source --statistics
	flake8 . --count --exit-zero --max-complexity=10 --max-line-length=100 --statistics
	# Same invocation as CI: scoped to memo.py and a hard gate (the
	# type debt is paid off; the error count must stay at zero). The
	# old whole-tree `mypy .` could never pass and matched no CI gate.
	mypy memo.py --ignore-missing-imports

format:
	black .
	isort .

# Security
# Same checks as CI: advisory whole-tree Bandit report, a real gate
# over the modules that actually ship (pyproject py-modules), and
# pip-audit over the declared requirements. Replaces `safety check`
# (Safety 3.x requires an account/API key and errors out unaudited)
# and the bare environment-wide `pip-audit`.
security:
	bandit -r . -f json -o bandit-report.json || true
	bandit memo.py memo_api.py config.py memo_enhanced_utils.py memo_errors.py memo_integrity.py memo_performance.py memo_security.py -ll
	pip-audit -r requirements.txt -r requirements-dev.txt

# Cleanup
clean:
	rm -rf build/
	rm -rf dist/
	rm -rf *.egg-info
	rm -rf htmlcov/
	rm -rf .pytest_cache/
	rm -rf .mypy_cache/
	rm -rf .coverage
	find . -type d -name __pycache__ -exec rm -rf {} +
	find . -type f -name '*.pyc' -delete
	find . -type f -name '*.pyo' -delete

# Building
build: clean
	python -m build

dist: build
	@echo "Distribution packages created in dist/"

# Upload to PyPI
upload: dist
	twine check dist/*
	twine upload dist/*

# Documentation
docs:
	pdoc --html --output-dir docs . --force

# Development workflow
dev: install-dev format lint test

# CI/CD simulation
ci: install-dev lint security test-cov

# All checks before commit
pre-commit: format lint security test
	@echo "All pre-commit checks passed!"

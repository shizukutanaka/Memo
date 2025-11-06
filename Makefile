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
	@echo "  security        Run security checks (bandit, safety)"
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
	mypy . --ignore-missing-imports

format:
	black .
	isort .

# Security
security:
	bandit -r . -f txt
	safety check
	pip-audit

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

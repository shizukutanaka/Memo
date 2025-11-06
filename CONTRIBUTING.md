# Contributing to Enterprise Memo System

Thank you for your interest in contributing to the Enterprise Memo System! This document provides guidelines and instructions for contributing to this project.

## Table of Contents

- [Code of Conduct](#code-of-conduct)
- [Getting Started](#getting-started)
- [Development Setup](#development-setup)
- [How to Contribute](#how-to-contribute)
- [Coding Standards](#coding-standards)
- [Testing Requirements](#testing-requirements)
- [Pull Request Process](#pull-request-process)
- [Security Issues](#security-issues)
- [License](#license)

## Code of Conduct

### Our Standards

- **Be respectful**: Treat everyone with respect and professionalism
- **Be inclusive**: Welcome contributors from all backgrounds and experience levels
- **Be constructive**: Provide helpful, actionable feedback
- **Be collaborative**: Work together toward the best solutions
- **Be professional**: Maintain a harassment-free environment

### Unacceptable Behavior

- Harassment, discrimination, or intimidation
- Trolling, insulting comments, or personal attacks
- Publishing others' private information without permission
- Other conduct inappropriate in a professional setting

## Getting Started

### Prerequisites

- Python 3.8 or higher
- SQLite 3.35 or higher (with FTS5 support)
- Git for version control
- Familiarity with Python, SQLite, and command-line tools

### Ways to Contribute

- **Report bugs**: Submit detailed bug reports with reproduction steps
- **Suggest features**: Propose new features with clear use cases
- **Fix issues**: Pick up existing issues from the issue tracker
- **Improve documentation**: Enhance README, guides, or code comments
- **Write tests**: Increase test coverage and reliability
- **Review code**: Provide thoughtful feedback on pull requests

## Development Setup

### 1. Fork and Clone

```bash
# Fork the repository on GitHub, then clone your fork
git clone https://github.com/YOUR_USERNAME/memo.git
cd memo

# Add upstream remote
git remote add upstream https://github.com/ORIGINAL_OWNER/memo.git
```

### 2. Create a Virtual Environment

```bash
# Create virtual environment
python3 -m venv venv

# Activate virtual environment
# On Linux/macOS:
source venv/bin/activate
# On Windows:
venv\Scripts\activate
```

### 3. Install Dependencies

```bash
# Install all dependencies including development tools
pip install -r requirements.txt
pip install -r requirements-dev.txt  # If available

# Or install with development extras
pip install -e ".[dev]"
```

### 4. Verify Installation

```bash
# Run the application to verify setup
python3 memo.py --help

# Run tests (when test suite is available)
pytest tests/
```

## How to Contribute

### Reporting Bugs

When reporting bugs, please include:

1. **Clear title**: Concise summary of the issue
2. **Description**: Detailed explanation of the problem
3. **Steps to reproduce**: Step-by-step instructions
4. **Expected behavior**: What should happen
5. **Actual behavior**: What actually happens
6. **Environment**:
   - Python version (`python3 --version`)
   - SQLite version (`sqlite3 --version`)
   - Operating system and version
   - Relevant configuration settings
7. **Error messages**: Full error output and logs (`~/.memo/personal.log`)
8. **Screenshots**: If applicable

### Suggesting Features

When suggesting features, please include:

1. **Clear title**: Concise feature summary
2. **Problem statement**: What problem does this solve?
3. **Proposed solution**: How should it work?
4. **Alternatives considered**: Other approaches you've thought about
5. **Use cases**: Real-world scenarios where this would be useful
6. **Additional context**: Mockups, examples, or references

### Making Changes

1. **Create a branch**:
   ```bash
   git checkout -b feature/your-feature-name
   # or
   git checkout -b fix/bug-description
   ```

2. **Make your changes**:
   - Write clean, readable code
   - Follow the project's coding standards
   - Add or update tests as needed
   - Update documentation if applicable

3. **Test your changes**:
   ```bash
   # Run all tests
   pytest tests/

   # Run with coverage
   pytest --cov=. tests/

   # Run linting
   flake8 .

   # Run type checking
   mypy .
   ```

4. **Commit your changes**:
   ```bash
   git add .
   git commit -m "feat: add new feature" -m "Detailed description"
   ```

### Commit Message Guidelines

We follow [Conventional Commits](https://www.conventionalcommits.org/):

**Format**: `<type>(<scope>): <subject>`

**Types**:
- `feat`: New feature
- `fix`: Bug fix
- `docs`: Documentation changes
- `style`: Code style changes (formatting, no logic change)
- `refactor`: Code refactoring (no feature change or bug fix)
- `perf`: Performance improvements
- `test`: Adding or updating tests
- `chore`: Maintenance tasks (dependencies, build tools)
- `ci`: CI/CD configuration changes
- `security`: Security-related changes

**Examples**:
```
feat(search): add full-text search with ranking
fix(encryption): resolve key rotation edge case
docs(readme): update installation instructions
perf(database): optimize query with indexes
security(auth): implement rate limiting for login
```

## Coding Standards

### Python Style Guide

We follow [PEP 8](https://pep8.org/) with some modifications:

**Line Length**:
- Maximum 100 characters (not 79)
- Can exceed for URLs, long strings, or complex expressions

**Naming Conventions**:
- `snake_case` for functions, variables, and module names
- `PascalCase` for class names
- `UPPER_CASE` for constants
- Descriptive names over abbreviations

**Code Organization**:
```python
#!/usr/bin/env python3
"""Module docstring describing purpose."""

# Standard library imports
import os
import sys

# Third-party imports
import requests
from cryptography.fernet import Fernet

# Local imports
from config import Config
from memo_errors import ValidationError

# Constants
MAX_RETRIES = 3
DEFAULT_TIMEOUT = 30

# Classes and functions
class MemoSystem:
    """Class docstring."""

    def __init__(self):
        """Constructor docstring."""
        pass
```

**Type Hints**:
```python
def add_memo(
    self,
    content: str,
    category: Optional[str] = None,
    tags: Optional[List[str]] = None
) -> int:
    """Add a new memo and return its ID."""
    pass
```

**Error Handling**:
```python
try:
    result = risky_operation()
except SpecificError as e:
    logger.error(f"Operation failed: {e}")
    raise
finally:
    cleanup_resources()
```

### Documentation Standards

**Module Docstrings**:
```python
"""Module for secure memo encryption and key management.

This module provides encryption utilities using AES-256-GCM for memo content
and Fernet for metadata. Keys are managed through the CredentialManager.
"""
```

**Function Docstrings**:
```python
def search_memos(
    self,
    query: str,
    limit: int = 20,
    category: Optional[str] = None
) -> List[Dict[str, Any]]:
    """Search memos using full-text search.

    Args:
        query: Search query string (supports AND, OR, NOT operators)
        limit: Maximum number of results to return (default: 20)
        category: Filter by specific category (optional)

    Returns:
        List of memo dictionaries with keys: id, content, category, tags,
        created_at, updated_at, priority, status

    Raises:
        ValidationError: If query is empty or invalid
        StorageError: If database query fails

    Example:
        >>> memos = system.search_memos("project AND urgent", limit=10)
        >>> print(len(memos))
        5
    """
```

**Inline Comments**:
- Explain *why*, not *what* (code should be self-explanatory)
- Use for complex logic, non-obvious decisions, or workarounds
- Keep comments up-to-date with code changes

### Security Standards

**Input Validation**:
- Validate all user input before processing
- Use parameterized queries for all database operations
- Sanitize input for display (prevent XSS)
- Implement rate limiting for sensitive operations

**Sensitive Data**:
- Never log passwords, API keys, or encryption keys
- Use environment variables for secrets (never hardcode)
- Encrypt sensitive data at rest and in transit
- Implement secure key management

**Error Messages**:
- Don't expose system internals in user-facing errors
- Log detailed errors securely for debugging
- Provide actionable guidance to users

## Testing Requirements

### Test Coverage

- **Minimum coverage**: 70% for new code
- **Target coverage**: 80%+ for critical paths
- **Critical systems**: 90%+ (encryption, authentication, data integrity)

### Test Types

**Unit Tests**:
```python
import pytest
from memo_system import MemoSystem

def test_add_memo_success():
    """Test adding a memo successfully."""
    system = MemoSystem()
    memo_id = system.add_memo("Test content", category="test")
    assert isinstance(memo_id, int)
    assert memo_id > 0

def test_add_memo_validation_error():
    """Test validation error for empty content."""
    system = MemoSystem()
    with pytest.raises(ValidationError, match="Content cannot be empty"):
        system.add_memo("")
```

**Integration Tests**:
- Test interaction between components
- Verify database operations
- Test encryption/decryption workflows

**Performance Tests**:
- Benchmark critical operations
- Test with large datasets (10,000+ memos)
- Verify query performance

**Security Tests**:
- Test input validation
- Verify encryption is applied
- Test authentication and authorization
- Check for SQL injection vulnerabilities

### Running Tests

```bash
# Run all tests
pytest tests/

# Run with coverage report
pytest --cov=. --cov-report=html tests/

# Run specific test file
pytest tests/test_memo_system.py

# Run tests matching pattern
pytest -k "test_add_memo"

# Run with verbose output
pytest -v tests/
```

## Pull Request Process

### Before Submitting

1. ✅ **Code quality**: Ensure code follows standards
2. ✅ **Tests**: Add tests for new features, update for bug fixes
3. ✅ **Documentation**: Update README, docstrings, or guides
4. ✅ **Linting**: Run `flake8` and fix all issues
5. ✅ **Type checking**: Run `mypy` and resolve type errors
6. ✅ **All tests pass**: Verify locally before pushing
7. ✅ **Commit messages**: Follow conventional commit format
8. ✅ **Branch is up-to-date**: Rebase on latest main/master

### Submitting Pull Request

1. **Push your branch**:
   ```bash
   git push origin feature/your-feature-name
   ```

2. **Create pull request on GitHub**:
   - Clear title summarizing the change
   - Detailed description explaining:
     - What changed and why
     - How it was tested
     - Any breaking changes
     - Related issues (use "Fixes #123" to auto-close)

3. **Pull request template**:
   ```markdown
   ## Description
   Brief description of changes

   ## Type of Change
   - [ ] Bug fix (non-breaking change fixing an issue)
   - [ ] New feature (non-breaking change adding functionality)
   - [ ] Breaking change (fix or feature causing existing functionality to change)
   - [ ] Documentation update

   ## Testing
   - [ ] Unit tests added/updated
   - [ ] Integration tests added/updated
   - [ ] All tests pass locally
   - [ ] Manual testing completed

   ## Checklist
   - [ ] Code follows project style guidelines
   - [ ] Self-review completed
   - [ ] Comments added for complex code
   - [ ] Documentation updated
   - [ ] No new warnings generated
   - [ ] Backward compatibility maintained (or breaking changes documented)

   ## Related Issues
   Fixes #123
   ```

### Review Process

1. **Automated checks**: CI/CD pipeline runs tests and linting
2. **Code review**: Maintainers review code and provide feedback
3. **Feedback addressed**: Make requested changes and push updates
4. **Approval**: Once approved, maintainers will merge

### After Merge

1. **Delete branch**: Clean up your feature branch
2. **Update local repo**:
   ```bash
   git checkout main
   git pull upstream main
   ```

## Security Issues

**DO NOT** report security vulnerabilities through public GitHub issues.

Instead, please report security issues to the maintainers directly through:
- Email (see SECURITY.md for contact information)
- GitHub Security Advisories (private reporting)

See [SECURITY.md](SECURITY.md) for our security policy and responsible disclosure guidelines.

## Development Resources

### Useful Commands

```bash
# Format code with black
black .

# Sort imports
isort .

# Run linter
flake8 .

# Type checking
mypy .

# Check for security issues
bandit -r .

# Generate documentation
pdoc --html --output-dir docs .
```

### Project Structure

```
memo/
├── memo.py                    # Main application entry point
├── memo_system.py             # Core memo system logic
├── config.py                  # Configuration management
├── memo_security.py           # Security features
├── memo_performance.py        # Performance optimizations
├── memo_errors.py             # Error handling
├── memo_integrity.py          # Data integrity
├── billing.py                 # Subscription management
├── tests/                     # Test suite
│   ├── test_memo_system.py
│   └── test_security.py
├── locales/                   # Internationalization
│   ├── en.json
│   └── ja.json
├── requirements.txt           # Production dependencies
├── requirements-dev.txt       # Development dependencies
├── README.md                  # Project documentation
├── LICENSE                    # License file
└── CONTRIBUTING.md            # This file
```

## Getting Help

- **Documentation**: Start with README.md and other guides
- **Issues**: Search existing issues for similar problems
- **Discussions**: Use GitHub Discussions for questions
- **Code review**: Request feedback on work-in-progress PRs

## Recognition

Contributors are recognized in:
- GitHub contributors page
- Release notes (for significant contributions)
- CHANGELOG.md

Thank you for contributing to making the Enterprise Memo System better! 🎉

---

**Last Updated**: 2025-10-31
**Version**: 1.0.0

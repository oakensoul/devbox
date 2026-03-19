# Contributing to devbox

Thank you for your interest in contributing to devbox! This document provides
guidelines and instructions for contributing.

## Development Setup

1. **Clone the repository:**

   ```bash
   git clone https://github.com/oakensoul/devbox.git
   cd devbox
   ```

2. **Create a virtual environment:**

   ```bash
   python3 -m venv .venv
   source .venv/bin/activate
   ```

3. **Install in editable mode with dev dependencies:**

   ```bash
   pip install -e ".[dev]"
   ```

4. **Install pre-commit hooks:**

   ```bash
   pip install pre-commit
   pre-commit install
   ```

5. **Verify your setup:**

   ```bash
   ruff check .
   mypy src/
   pytest
   ```

## Code Standards

- **Linting:** [ruff](https://docs.astral.sh/ruff/) — all configured rules
  must pass with zero warnings.
- **Type checking:** [mypy](https://mypy-lang.org/) in strict mode. All public
  APIs must have type annotations.
- **Testing:** [pytest](https://docs.pytest.org/). New features require tests;
  bug fixes require a regression test.
- **Line length:** 100 characters (configured in `pyproject.toml`).

## Pull Request Process

1. Create a feature branch from `main`.
2. Make your changes, ensuring all checks pass locally:
   ```bash
   ruff check .
   mypy src/
   pytest
   ```
3. Write clear, descriptive commit messages.
4. Open a pull request against `main`.
5. All PRs require code review before merging, even if CI passes.
6. Address any review feedback promptly.

## Reporting Bugs

Open a [GitHub issue](https://github.com/oakensoul/devbox/issues) with:

- Steps to reproduce
- Expected vs. actual behavior
- macOS version and Python version

## Security Issues

Please see [SECURITY.md](SECURITY.md) for reporting vulnerabilities.

## License

By contributing, you agree that your contributions will be licensed under the
AGPL-3.0-or-later license.

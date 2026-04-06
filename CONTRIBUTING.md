# Contributing to devbox

Thank you for your interest in contributing! This guide will help you get
started.

Please review our [Code of Conduct](CODE_OF_CONDUCT.md) before participating.

## Prerequisites

- **Python 3.11** or newer
- **Git**

## Setting Up Your Development Environment

```bash
# Fork and clone the repository
git clone https://github.com/<your-username>/devbox.git
cd devbox

# Install in editable mode with dev dependencies
make install

# Install pre-commit hooks
pip install pre-commit
pre-commit install
```

## Development Workflow

1. **Fork** the repository and create a feature branch from `main`:
   ```bash
   git checkout -b feat/my-feature main
   ```
2. **Make your changes** — write code, add tests, update docs as needed.
3. **Run the full check suite** before pushing:
   ```bash
   make check-all
   ```
4. **Push** your branch and open a **Pull Request** against `main`.

## Code Standards

### Linting and Formatting

- **ruff** is used for both linting and formatting.
- Run `ruff check .` and `ruff format --check .` to verify locally, or rely on
  `make check-all` which runs both.

### Type Checking

- **mypy** is used in strict mode:
  ```bash
  mypy src/
  ```

### Test Coverage

- We target **90% test coverage**.
- Run tests with:
  ```bash
  pytest --cov=devbox --cov-report=term-missing
  ```

## Commit Messages

This project follows
[Conventional Commits](https://www.conventionalcommits.org/en/v1.0.0/):

```
<type>: <short summary>

<optional body>

<optional footer(s)>
```

Common types:

| Type       | Purpose                          |
| ---------- | -------------------------------- |
| `feat`     | New feature                      |
| `fix`      | Bug fix                          |
| `docs`     | Documentation only               |
| `style`    | Formatting, no logic change      |
| `refactor` | Code restructuring, no new feature or fix |
| `test`     | Adding or updating tests         |
| `chore`    | Build, CI, tooling changes       |

## AI Tools and Attribution

We welcome contributions made with the help of AI coding tools. However,
**do not include AI attribution in commits or pull requests**:

- No `Co-Authored-By` trailers referencing AI tools
- No "Generated with", "Powered by", or "Assisted by" text in PR descriptions

CI will automatically reject PRs that contain these patterns.

**This is not an anti-AI policy.** It is a copyright protection measure. This
project is licensed under AGPL-3.0-or-later, where clear copyright ownership
matters for license enforcement. AI co-authorship trailers create legal
ambiguity about who holds copyright over the contributed code. By keeping
attribution exclusively with human contributors, we maintain unambiguous
ownership and protect the integrity of the license.

You are the author of your contributions, regardless of what tools you used to
write them.

## Pull Request Process

1. Fill out the PR template completely.
2. Ensure **CI passes** on all checks.
3. At least **one approval** is required before merging.
4. Keep PRs focused — prefer small, incremental changes over large sweeping
   ones.

## Questions?

Open a
[Discussion](https://github.com/oakensoul/devbox/discussions) or reach out to
the maintainer at **github@oakensoul.com**.

## License

By contributing, you agree that your contributions will be licensed under the
AGPL-3.0-or-later license.

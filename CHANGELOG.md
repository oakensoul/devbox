# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

### Security
- Pin GitHub Actions to full commit SHAs
- Add missing secret patterns to .gitignore
- Enable ruff S (bandit) security linting rules
- Add `--proto =https` to curl invocations in bootstrap.py
- Add concurrency control to CI workflows

### Added
- `devbox refresh <name>` and `devbox refresh --all` to push current dotfiles/config to existing devboxes without destroying state, with `--with-brew` and `--with-globals` opt-in flags for slower full reinstalls (#49)
- SPDX license headers and copyright notices on all source files
- CODE_OF_CONDUCT.md (Contributor Covenant v2.1)
- GitHub issue templates (bug report, feature request)
- GitHub pull request template
- Release workflow with SBOM generation (CycloneDX JSON + XML)
- Makefile with install, lint, format, test, audit, build, clean, check-all targets
- pip-audit dependency auditing in CI
- Build verification (python -m build + twine check) in CI
- Test coverage reporting with pytest-cov
- CI check for AI attribution in commits and PR descriptions
- User bootstrapping: nvm, pyenv, brew extras, npm/pip globals (#10)
- Claude Code auth injection for Anthropic and AWS providers (#11)
- Health checks with SSH connectivity probes and atrophy detection (#15)
- zshrc heartbeat hook for last_seen tracking (#16)
- Sudoers drop-in file validation and setup (#27)
- Password disabling for devbox users via pwpolicy (#28)
- Dry-run mode for create and nuke commands (#18)
- Integration test infrastructure with macOS CI workflow (#17)
- Security and compliance files (#25)

### Changed
- Add project metadata to pyproject.toml (authors, license, classifiers, URLs)
- Add dev dependencies: build, cyclonedx-bom, pip-audit, pytest-cov, twine

## [0.1.0] - 2026-03-18

### Added
- **Milestone 1 — Foundation**: Project structure, naming validation, exception hierarchy, CI pipeline
- **Milestone 2 — Core Modules**: Registry (pydantic CRUD), presets (validation + loading), 1Password wrapper
- **Milestone 3 — Platform & Integrations**: macOS user management (dscl), SSH key lifecycle, GitHub API, iTerm2 profiles, sshd configuration
- **Milestone 4 — Orchestration**: Core create/nuke/list/rebuild with compensation stack, CLI with rich output, LocalProvider

[Unreleased]: https://github.com/oakensoul/devbox/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/oakensoul/devbox/releases/tag/v0.1.0

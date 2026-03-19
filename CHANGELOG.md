# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

### Added
- User bootstrapping: nvm, pyenv, brew extras, npm/pip globals (#10)
- Claude Code auth injection for Anthropic and AWS providers (#11)
- Health checks with SSH connectivity probes and atrophy detection (#15)
- zshrc heartbeat hook for last_seen tracking (#16)
- Sudoers drop-in file validation and setup (#27)
- Password disabling for devbox users via pwpolicy (#28)
- Dry-run mode for create and nuke commands (#18)
- Integration test infrastructure with macOS CI workflow (#17)
- Security and compliance files (#25)

## [0.1.0] - 2026-03-18

### Added
- **Milestone 1 — Foundation**: Project structure, naming validation, exception hierarchy, CI pipeline
- **Milestone 2 — Core Modules**: Registry (pydantic CRUD), presets (validation + loading), 1Password wrapper
- **Milestone 3 — Platform & Integrations**: macOS user management (dscl), SSH key lifecycle, GitHub API, iTerm2 profiles, sshd configuration
- **Milestone 4 — Orchestration**: Core create/nuke/list/rebuild with compensation stack, CLI with rich output, LocalProvider

[Unreleased]: https://github.com/oakensoul/devbox/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/oakensoul/devbox/releases/tag/v0.1.0

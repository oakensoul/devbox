# Devbox — Architecture

## What is Devbox?

Devbox is a CLI + importable Python package for managing disposable SSH-only macOS dev environments. Each devbox is a separate macOS user account — isolated home directory, separate SSH key, dedicated GitHub identity, and its own iTerm2 profile with a distinct visual identity.

Devboxes are **project-scoped, not branch-scoped**. One devbox per project; use git worktrees inside for multi-branch work.

Structured data throughout the system — registry entries, presets, provision results — uses pydantic v2 models for validation and serialization.

---

## Ecosystem Position

```
loadout            ← installs devbox as part of machine setup
devbox             ← this package
aida-devbox-plugin ← thin AIDA skill wrapper around devbox.core
```

The AIDA plugin imports directly from this package:

```python
from devbox.core import create_devbox, list_devboxes
```

---

## User Model

Each Mac user has their own devbox registry — devboxes are scoped to the user that created them:

| Mac User | Devboxes |
|----------|----------|
| `alice` | personal project devboxes |
| `work` | acme work devboxes |

Personal and work devboxes are completely separate — flat naming, scoped by which user created them.

All devbox macOS usernames use the `dx-` prefix. A devbox named `acme-work` becomes macOS user `dx-acme-work`, with home directory `/Users/dx-acme-work`.

---

## Global Config

The parent user's `~/.devbox/config.json` stores global settings:

```json
{
  "parent_github_user": "myuser"
}
```

`parent_github_user` is used to populate `authorized_keys` in each devbox from the GitHub `.keys` endpoint.

---

## CLI Interface

```bash
devbox create <name> --preset=<preset>   # create new devbox
devbox refresh <name>                    # push updated dotfiles/config (preserves state)
devbox rebuild <name>                    # rebuild existing devbox
devbox nuke <name>                       # destroy devbox + clean up everything
devbox list                              # show all devboxes for current user
```

### Connecting to a devbox

```bash
ssh dx-acme-work@localhost
```

### `devbox list` output

```
NAME          PRESET          CREATED      LAST SEEN    STATUS
devbox1       acme-data       2025-03-01   2h ago       ✅ healthy
devbox2       f1-fantasy      2025-01-15   47d ago      ⚠️  atrophied
devbox3       default         2025-03-10   SSH timeout  ❌ unreachable
```

---

## Lifecycle

### `devbox create`

1. Validate preset exists and is valid
2. Create macOS user `dx-<name>` via `dscl`
3. Generate SSH key for the new user
4. Register SSH key with GitHub via API
5. Bootstrap the user: nvm, pyenv, brew extras, pip/npm globals
6. Resolve secrets — any `op://` references in preset `env_vars` are resolved via `op read` and written to `/Users/dx-<name>/.devbox-env` (mode `0600`)
7. Inject Claude Code auth (API key or Bedrock creds) from parent user
8. Create iTerm2 profile (color scheme from preset + badge)
9. Write entry to `~/.devbox/registry.json` with status `ready`

### `devbox nuke`

1. Set registry entry status to `nuking`
2. Remove SSH key from GitHub via API (using stored `github_key_id`)
3. Delete macOS user + home directory via `dscl`
4. Remove iTerm2 profile
5. Remove entry from registry

### `devbox refresh`

SSH into the existing devbox and re-run `loadout update --skip-brew --skip-globals` to pull current dotfiles and preset config. In-devbox state (shell history, uncommitted work, local files) is preserved. Refuses to run on devboxes that aren't in `ready` state.

Flags:

- `--with-brew` — also drop `--skip-brew` (run loadout Brewfile) and reinstall preset `brew_extras`. Slow (15-30 min/box) because the per-devbox `~/.homebrew` prefix has no bottles.
- `--with-globals` — also drop `--skip-globals` and reinstall preset `npm_globals` / `pip_globals`.
- `--all` — iterate every `ready` devbox in the registry. Failures are collected and reported at the end; one failed box does not abort the rest.

### `devbox rebuild`

Nuke + create with the same name and preset.

---

## Error Handling

During `devbox create`, a compensation stack tracks an undo operation for each completed step. If any step fails, the accumulated undos execute in reverse order to roll back the partial creation.

Key properties:

- Each undo is **idempotent** — safe to retry if something goes wrong during cleanup itself.
- A failed undo is **logged but does not block** the remaining undo operations from running.
- On successful rollback, the registry entry is removed entirely so no ghost entries remain.

This keeps the system clean even when creation fails partway through — no orphaned users, dangling GitHub keys, or stale registry entries.

---

## Registry

Each user maintains `~/.devbox/registry.json`:

```json
{
  "version": 1,
  "devboxes": [
    {
      "name": "devbox1",
      "preset": "acme-data",
      "created": "2025-03-12",
      "last_seen": "2025-03-12T10:00:00Z",
      "status": "ready",
      "github_key_id": "12345678"
    }
  ]
}
```

The `status` field tracks the devbox lifecycle state: `creating`, `ready`, or `nuking`.

### Heartbeat

Each devbox user writes a timestamp to `/Users/dx-<name>/.devbox_heartbeat` (chmod 644) via a `.zshrc` hook on every login. `devbox list` reads these heartbeat files and caches the value in the registry's `last_seen` field. This avoids the devbox needing write access to the parent user's registry.

### Atrophy thresholds

- **> 30 days** since `last_seen` → ⚠️ warn, suggest `devbox nuke`
- **SSH timeout** → ❌ unreachable

---

## Presets

Presets live in `~/.dotfiles-private/devbox/presets/<name>.json`:

```json
{
  "version": 1,
  "name": "acme-data",
  "description": "dbt + Snowflake + Python data work",
  "provider": "anthropic-work",
  "aws_profile": "acme-main",
  "github_account": "acme-dev",
  "node_version": "lts",
  "python_version": "3.12",
  "brew_extras": ["python@3.12"],
  "npm_globals": [],
  "pip_globals": ["dbt-core", "dbt-snowflake"],
  "mcp_profile": "work",
  "color_scheme": "nord",
  "env_vars": {
    "SNOWFLAKE_ACCOUNT": "op://Work/Snowflake/account",
    "DBT_PROFILES_DIR": "~/.dbt"
  }
}
```

`env_vars` values may use `op://` references — these are resolved at `devbox create` time via `op read`, and the resolved values are written to `/Users/dx-<name>/.devbox-env` (mode `0600`). The devbox user's `.zshrc` sources this file on login. Plaintext secrets are never stored in the preset or registry.

Since the devbox is disposable and 1Password is the source of truth, secret rotation is handled by nuking the devbox and recreating it.

---

## iTerm2 Profiles

Each devbox gets a complete visual identity — color scheme + badge — created on `devbox create` and removed on `devbox nuke`.

The color scheme is driven by the `color_scheme` field in the preset. The table below provides guidance for choosing values when authoring presets:

### Color conventions

| Context | Scheme | Why |
|---------|--------|-----|
| Production / prod-adjacent | Solarized Dark | Visual warning — be careful |
| Data / dbt work | Nord | Calm, focused |
| Personal projects | Dracula / Catppuccin | Distinct from work |
| Default / scratch | Gruvbox | Neutral fallback |

### Naming

iTerm2 profiles use the `devbox::<name>` convention — e.g. `devbox::acme-work`. The SSH target for that devbox is `dx-acme-work@localhost`.

---

## Claude Code Auth

Devboxes inherit Claude Code auth from the parent user — no browser login needed:

- **Anthropic direct**: API key injected via env var from parent
- **AWS Bedrock**: AWS credentials injected from parent's profile

Provider is specified per preset via the `provider` field.

---

## SSH Keys

- **Inbound (to devbox)**: Populated from parent user's GitHub `.keys` endpoint (configured via `parent_github_user` in `~/.devbox/config.json`) — always current, zero maintenance
- **Outbound (from devbox)**: Generated fresh on `devbox create`, registered with GitHub API, removed on `devbox nuke`

GitHub key ID stored in registry for cleanup on nuke.

---

## Secrets

All secrets via 1Password CLI (`op`). The `onepassword.py` module wraps `op read` calls. Env vars in presets use `op://` references resolved at `devbox create` time — resolved values are written to `/Users/dx-<name>/.devbox-env` (mode `0600`) and sourced by the devbox user's `.zshrc`. 1Password is the source of truth; secret rotation means nuke + recreate.

---

## Package Structure

```
src/devbox/
├── __init__.py
├── cli.py           # Click CLI — thin wrapper around core
├── core.py          # Core logic — importable by AIDA plugin
├── registry.py      # ~/.devbox/registry.json read/write
├── github.py        # GitHub API — SSH key lifecycle
├── iterm2.py        # iTerm2 profile management
├── onepassword.py   # op CLI wrapper
├── presets.py       # Preset loading + validation
├── macos.py         # dscl user management
├── naming.py        # kebab-case validation for devbox/preset names
├── exceptions.py    # Custom exception hierarchy — DevboxError base + subclasses
└── providers/
    ├── __init__.py
    ├── base.py      # Abstract provider interface
    └── local.py     # Local macOS provider (today)
    # future: ecs.py, ec2.py
```

---

## Naming Conventions

kebab-case everywhere: `[a-z0-9-]`, no leading/trailing dashes. Validated by `naming.py`.

| Thing | Convention | Example |
|-------|-----------|---------|
| Devbox names | kebab-case | `acme-work`, `f1-experiment` |
| macOS usernames | `dx-<name>` | `dx-acme-work`, `dx-f1-experiment` |
| Preset names | kebab-case | `acme-data`, `personal-python` |
| iTerm2 profiles | `devbox::<name>` | `devbox::acme-work` |

---

## Platform Support

macOS only — relies on `dscl` for user management, iTerm2 for profiles, and the virtual framebuffer model for the `work` user.

A scoped sudoers drop-in at `/etc/sudoers.d/devbox` restricts NOPASSWD access to `dscl` and `createhomedir` commands matching the `dx-*` prefix only. This limits privilege escalation to the minimum required for devbox user management.

A future provider abstraction (`providers/`) is designed to support ECS/EC2 devboxes without changing the CLI interface.

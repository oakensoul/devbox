# devbox

CLI and library for managing disposable SSH-only macOS dev environments.

Devbox creates isolated macOS user accounts, generates SSH keys, registers them
with GitHub, and sets up iTerm2 profiles — giving you throwaway sandboxes you
can SSH into, rebuild, or nuke in seconds.

## Installation

```bash
pip install -e .
```

## Usage

```bash
# Create a devbox from a preset
devbox create mybox --preset=my-preset

# List all devboxes
devbox list

# Tear down and recreate
devbox rebuild mybox

# Push current dotfiles/preset config to an existing devbox (preserves state)
devbox refresh mybox
devbox refresh --all
devbox refresh mybox --with-globals  # also reinstall npm/pip globals

# Permanently destroy
devbox nuke mybox
```

### `refresh` vs `rebuild`

- **`refresh`** SSHes into the existing devbox, re-runs `loadout update`
  to pull the latest dotfiles, and reinstalls the preset's `brew_extras`.
  Shell history, uncommitted work, and local files are preserved. The
  devbox must be in `ready` state (run `devbox list` to check);
  refreshing a `creating`/`nuking` box is refused.
- **Edited a preset?** Plain `refresh` picks up dotfile-level changes
  (loadout orgs, env vars) and `brew_extras` automatically. For
  `npm_globals` / `pip_globals`, pass `--with-globals`. Changes to the
  loadout Brewfile itself aren't picked up by refresh — `rebuild` the
  devbox for that (the per-devbox `~/.homebrew` prefix has no bottles and
  compiles from source, 30+ min).
- **`rebuild`** nukes and recreates the devbox from scratch. Destroys all
  in-devbox state. Use when bootstrap itself changed, the loadout
  Brewfile changed, or the box is irrecoverably broken.

## Presets

Preset files live in `~/.dotfiles-private/devbox/presets/<name>.json` and
define the toolchain, GitHub account, provider, and environment variables for
each devbox type.

## As a library

```python
from devbox.core import create_devbox, list_devboxes

entry = create_devbox("mybox", preset="my-preset")
boxes = list_devboxes()
```

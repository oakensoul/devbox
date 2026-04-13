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
devbox refresh mybox --with-brew --with-globals  # also reinstall brew/npm/pip (slow)

# Permanently destroy
devbox nuke mybox
```

### `refresh` vs `rebuild`

- **`refresh`** SSHes into the existing devbox and re-runs `loadout update`,
  pulling the latest dotfiles and preset config. Shell history, uncommitted
  work, and local files are preserved. Fast (~30s/box). Use this whenever
  dotfiles or preset config has changed.
- **`refresh --with-brew` / `--with-globals`** additionally reinstall the
  preset's `brew_extras` / `npm_globals` / `pip_globals` and run the loadout
  Brewfile. Slow (15-30 min/box) because the per-devbox `~/.homebrew` prefix
  has no bottles.
- **`rebuild`** nukes and recreates the devbox from scratch. Destroys all
  in-devbox state. Use when bootstrap itself changed, or when the box is
  irrecoverably broken.

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

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
  pulling the latest dotfiles. Shell history, uncommitted work, and local
  files are preserved. Fast (~30s/box). The devbox must be in `ready` state
  (run `devbox list` to check); refreshing a `creating`/`nuking` box is
  refused.
- **Edited a preset?** Plain `refresh` is enough for *dotfile* preset fields
  (loadout orgs, env vars, etc.). To pick up changes to `brew_extras`, run
  `refresh --with-brew`. For `npm_globals`/`pip_globals`, use
  `refresh --with-globals`. These are slow (15-30 min/box) because the
  per-devbox `~/.homebrew` prefix has no bottles and compiles from source.
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

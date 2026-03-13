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
devbox create mybox --preset=splash-data

# List all devboxes
devbox list

# Tear down and recreate
devbox rebuild mybox

# Permanently destroy
devbox nuke mybox
```

## Presets

Preset files live in `~/.dotfiles-private/devbox/presets/<name>.json` and
define the toolchain, GitHub account, provider, and environment variables for
each devbox type.

## As a library

```python
from devbox.core import create_devbox, list_devboxes

entry = create_devbox("mybox", preset="splash-data")
boxes = list_devboxes()
```

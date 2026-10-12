"""Persistent user settings for E-SHELL

Stores data in JSON at ~/.config/e-shell/settings.json 
( somewhat like init.lua for nvim or other config files)

Usage: 
    import settings 
    settings.get("editor_usage")

"""

import copy
import json
import os
from pathlib import Path

DEFAULTS = {
    "default_editor": None,
    "editor_usage": {},
}


# gets the ~/.config to save the settings.json as it contains user data which is only helpful 
# for systems value
def _path():
    base = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
    return base / "e-shell" / "settings.json"


def load():
    try:
        data = json.loads(_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = {}

    if not isinstance(data, dict):
        data = {}

    merged = copy.deepcopy(DEFAULTS)
    merged.update(data)
    return merged

# saving the settings.json | precautious of IO/OS errors
def save(data):
    path = _path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = path.with_suffix(".tmp")
        temp_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        temp_path.replace(path)
    except OSError:
        pass  


def get(key, default=None):
    value = load().get(key)
    if value is None:
        value = copy.deepcopy(DEFAULTS.get(key, default))
    return value

def set(key, value):
    data = load()
    data[key] = value
    save(data)

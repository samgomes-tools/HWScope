"""Preferências do usuário em ~/.config/hwscope/settings.json."""
from __future__ import annotations

import os


def settings_path():
    base = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
    return os.path.join(base, "hwscope", "settings.json")


def load_settings():
    import json
    try:
        with open(settings_path()) as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def save_settings(**kw):
    import json
    st = load_settings()
    st.update(kw)
    try:
        os.makedirs(os.path.dirname(settings_path()), exist_ok=True)
        with open(settings_path(), "w") as f:
            json.dump(st, f, indent=1)
    except OSError:
        pass

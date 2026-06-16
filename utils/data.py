"""
utils/data.py — JSON-based persistent storage helpers.
All data files live in the /data directory.
"""

import json
import os
from config import Config

_CACHE: dict[str, dict] = {}

def _path(filename: str) -> str:
    os.makedirs(Config.DATA_DIR, exist_ok=True)
    return os.path.join(Config.DATA_DIR, filename)

def load(filename: str) -> dict:
    """Load JSON file, returning {} on missing."""
    if filename in _CACHE:
        return _CACHE[filename]
    fp = _path(filename)
    if not os.path.exists(fp):
        _CACHE[filename] = {}
        return {}
    with open(fp, "r", encoding="utf-8") as f:
        data = json.load(f)
    _CACHE[filename] = data
    return data

def save(filename: str, data: dict) -> None:
    """Persist data to JSON file."""
    _CACHE[filename] = data
    with open(_path(filename), "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

def guild_data(filename: str, guild_id: int) -> dict:
    """Return guild-specific sub-dict, creating it if missing."""
    data = load(filename)
    key = str(guild_id)
    if key not in data:
        data[key] = {}
    return data[key]

def user_data(filename: str, guild_id: int, user_id: int) -> dict:
    """Return user-specific sub-dict within a guild, creating if missing."""
    data = load(filename)
    gk = str(guild_id)
    uk = str(user_id)
    data.setdefault(gk, {}).setdefault(uk, {})
    return data[gk][uk]

def set_user(filename: str, guild_id: int, user_id: int, value: dict) -> None:
    """Overwrite a user entry and persist."""
    data = load(filename)
    data.setdefault(str(guild_id), {})[str(user_id)] = value
    save(filename, data)

def set_guild(filename: str, guild_id: int, value: dict) -> None:
    """Overwrite a guild entry and persist."""
    data = load(filename)
    data[str(guild_id)] = value
    save(filename, data)

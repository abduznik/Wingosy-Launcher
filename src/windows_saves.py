import json
import logging
from pathlib import Path

WINDOWS_SAVES_FILE = Path.home() / ".wingosy" / "windows_saves.json"

def load_windows_saves():
    """Load Windows save configurations from JSON."""
    if not WINDOWS_SAVES_FILE.exists():
        return {}
    try:
        with open(WINDOWS_SAVES_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        logging.error(f"Failed to load windows_saves.json: {e}")
        return {}

def save_windows_saves(data):
    """Save Windows save configurations to JSON."""
    WINDOWS_SAVES_FILE.parent.mkdir(parents=True, exist_ok=True)
    try:
        with open(WINDOWS_SAVES_FILE, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=4)
    except Exception as e:
        logging.error(f"Failed to save windows_saves.json: {e}")

def get_windows_save(rom_id):
    """Return the configured save data for a ROM ID."""
    data = load_windows_saves()
    return data.get(str(rom_id))

def get_save_dir(rom_id):
    """Return the configured save directory for a ROM ID."""
    entry = get_windows_save(rom_id)
    return entry.get("save_dir") if entry else None

def set_windows_save(rom_id, name, save_dir=None, default_exe=None):
    """Set or update the save/exe configuration for a ROM ID."""
    data = load_windows_saves()
    rid_str = str(rom_id)
    if rid_str not in data:
        data[rid_str] = {"name": name}
    
    if save_dir is not None:
        data[rid_str]["save_dir"] = save_dir
    if default_exe is not None:
        data[rid_str]["default_exe"] = default_exe
        
    save_windows_saves(data)

def remove_windows_save(rom_id):
    """Remove the save configuration for a ROM ID."""
    data = load_windows_saves()
    if str(rom_id) in data:
        del data[str(rom_id)]
        save_windows_saves(data)

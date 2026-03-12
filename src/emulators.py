import json
import os
import logging
from pathlib import Path

DEFAULT_EMULATORS = [
    {
        "id": "retroarch",
        "name": "Multi-Console (RetroArch)",
        "executable_path": "",
        "launch_args": ["-L", "{core_path}", "{rom_path}"],
        "platform_slugs": ["multi", "nes", "snes", "n64", "gb", "gbc", "gba", "genesis", "mastersystem", "segacd", "gamegear", "atari2600", "psx", "psp"],
        "save_resolution": {
            "mode": "retroarch",
            "srm_dir": "",
            "state_dir": ""
        },
        "user_defined": False,
        "sync_enabled": True,
        "conflict_behavior": "ask"
    },
    {
        "id": "eden",
        "name": "Switch (Eden)",
        "executable_path": "",
        "launch_args": ["{rom_path}"],
        "platform_slugs": ["switch", "nintendo-switch"],
        "save_resolution": {
            "mode": "switch",
            "path": ""
        },
        "user_defined": False,
        "sync_enabled": True,
        "conflict_behavior": "ask"
    },
    {
        "id": "rpcs3",
        "name": "PlayStation 3",
        "executable_path": "",
        "launch_args": ["{rom_path}"],
        "platform_slugs": ["ps3", "playstation-3", "playstation3"],
        "save_resolution": {
            "mode": "ps3",
            "path": ""
        },
        "user_defined": False,
        "sync_enabled": True,
        "conflict_behavior": "ask"
    },
    {
        "id": "dolphin",
        "name": "GameCube / Wii",
        "executable_path": "",
        "launch_args": ["{rom_path}"],
        "platform_slugs": ["gc", "ngc", "wii", "gamecube", "nintendo-gamecube", "nintendo-wii", "wii-u-vc"],
        "save_resolution": {
            "mode": "dolphin",
            "path": ""
        },
        "user_defined": False,
        "sync_enabled": True,
        "conflict_behavior": "ask"
    },
    {
        "id": "pcsx2",
        "name": "PlayStation 2",
        "executable_path": "",
        "launch_args": ["{rom_path}"],
        "platform_slugs": ["ps2", "playstation-2", "playstation2"],
        "save_resolution": {
            "mode": "folder",
            "path": ""
        },
        "user_defined": False,
        "sync_enabled": True,
        "conflict_behavior": "ask"
    },
    {
        "id": "cemu",
        "name": "Wii U (Cemu)",
        "executable_path": "",
        "launch_args": ["-g", "{rom_path}"],
        "platform_slugs": ["wiiu", "wii-u", "nintendo-wii-u", "nintendo-wiiu"],
        "save_resolution": {
            "mode": "cemu",
            "path": ""
        },
        "user_defined": False,
        "sync_enabled": True,
        "conflict_behavior": "ask"
    },
    {
        "id": "azahar",
        "name": "Nintendo 3DS (Azahar)",
        "executable_path": "",
        "launch_args": ["{rom_path}"],
        "platform_slugs": ["n3ds", "3ds", "nintendo-3ds", "nintendo3ds", "new-nintendo-3ds", "new-nintendo-3ds-xl"],
        "save_resolution": {
            "mode": "folder",
            "path": ""
        },
        "user_defined": False,
        "sync_enabled": True,
        "conflict_behavior": "ask"
    },
    {
        "id": "xemu",
        "name": "Xemu",
        "executable_path": "",
        "launch_args": ["-dvd_path", "{rom_path}"],
        "github": "xemu-project/xemu",
        "platform_slugs": ["xbox"],
        "save_resolution": {
            "mode": "folder",
            "path": ""
        },
        "folder": "xemu",
        "user_defined": False,
        "sync_enabled": True,
        "conflict_behavior": "ask"
    },
    {
        "id": "xenia",
        "name": "Xenia",
        "executable_path": "",
        "launch_args": ["{rom_path}"],
        "url": "https://github.com/xenia-project/release-builds-windows/releases/latest/download/xenia_master.zip",
        "platform_slugs": ["xbox360"],
        "save_resolution": {
            "mode": "folder",
            "path": ""
        },
        "folder": "xenia",
        "user_defined": False,
        "sync_enabled": True,
        "conflict_behavior": "ask"
    },
    {
        "id": "duckstation",
        "name": "DuckStation",
        "executable_path": "",
        "launch_args": ["-batch", "{rom_path}"],
        "github": "stenzek/duckstation",
        "platform_slugs": ["ps", "playstation", "psx"],
        "save_resolution": {
            "mode": "folder",
            "path": ""
        },
        "folder": "duckstation",
        "user_defined": False,
        "sync_enabled": True,
        "conflict_behavior": "ask"
    },
    {
        "id": "melonds",
        "name": "MelonDS",
        "executable_path": "",
        "launch_args": ["{rom_path}"],
        "github": "melonDS-emu/melonDS",
        "platform_slugs": ["nds", "nintendo-ds"],
        "save_resolution": {
            "mode": "file",
            "path": ""
        },
        "folder": "melonds",
        "user_defined": False,
        "sync_enabled": True,
        "conflict_behavior": "ask"
    },
    {
        "id": "windows_native",
        "name": "Windows (Native)",
        "executable_path": "",
        "launch_args": [],
        "platform_slugs": ["windows", "win"],
        "is_native": True,
        "save_resolution": {
            "mode": "windows"
        },
        "user_defined": False,
        "sync_enabled": True,
        "conflict_behavior": "ask"
    }
]

EMULATORS_FILE = Path.home() / ".wingosy" / "emulators.json"

def load_emulators_raw():
    """Load the full emulators.json content."""
    if not EMULATORS_FILE.exists():
        data = {"migration_done": False, "emulators": DEFAULT_EMULATORS}
        save_emulators_raw(data)
        return data
    
    try:
        with open(EMULATORS_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
            
            # Filter out deprecated emulators (Yuzu)
            emus = data.get("emulators", [])
            initial_count = len(emus)
            data["emulators"] = [
                e for e in emus
                if not (
                    e.get("id", "").lower() == "yuzu" or 
                    "yuzu" in e.get("name", "").lower()
                )
            ]
            
            changed = len(data["emulators"]) < initial_count
            if changed:
                logging.info("Removed deprecated entries from emulators")
            
            # Ensure sync_enabled and conflict_behavior exists for all
            for e in data["emulators"]:
                if "sync_enabled" not in e:
                    e["sync_enabled"] = True
                    changed = True
                if "conflict_behavior" not in e:
                    e["conflict_behavior"] = "ask"
                    changed = True

            # Merge any new defaults
            existing_ids = {e.get("id") for e in data["emulators"] if e.get("id")}
            for default_emu in DEFAULT_EMULATORS:
                if default_emu["id"] not in existing_ids:
                    data["emulators"].append(default_emu)
                    changed = True
                    logging.info(f"Added new default emulator: {default_emu['id']}")
            
            if changed:
                save_emulators_raw(data)
                
            return data
    except Exception as e:
        logging.error(f"Failed to load emulators.json: {e}")
    
    return {"migration_done": False, "emulators": DEFAULT_EMULATORS}

def load_emulators():
    """Return only the list of emulator dicts."""
    return load_emulators_raw().get("emulators", DEFAULT_EMULATORS)

def save_emulators_raw(data):
    """Save full content to emulators.json."""
    EMULATORS_FILE.parent.mkdir(parents=True, exist_ok=True)
    try:
        with open(EMULATORS_FILE, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=4)
    except Exception as e:
        logging.error(f"Failed to save emulators.json: {e}")

def save_emulators(emulators_list):
    """Update only the emulators list in the JSON file."""
    data = load_emulators_raw()
    data["emulators"] = emulators_list
    save_emulators_raw(data)

def migrate_old_config(config_manager):
    """Migrate emulator paths from config.json to emulators.json once."""
    data = load_emulators_raw()
    if data.get("migration_done"):
        return

    logging.info("Starting emulator path migration from old config...")
    old_emus = config_manager.get("emulators", {})
    changed = False
    
    # Map old config names/ids to new schema IDs
    id_map = {
        "Multi-Console (RetroArch)": "retroarch",
        "Switch (Eden)": "eden",
        "PlayStation 3": "rpcs3",
        "GameCube / Wii": "dolphin",
        "PlayStation 2": "pcsx2",
        "Wii U (Cemu)": "cemu",
        "Nintendo 3DS (Azahar)": "azahar"
    }

    for old_name, old_data in old_emus.items():
        new_id = id_map.get(old_name)
        path = old_data.get("path")
        if new_id and path:
            for emu in data["emulators"]:
                if emu["id"] == new_id and not emu["executable_path"]:
                    emu["executable_path"] = path
                    logging.info(f"Migrated {new_id} path from old config: {path}")
                    changed = True
                    break
    
    data["migration_done"] = True
    save_emulators_raw(data)
    if changed:
        logging.info("Emulator path migration complete.")

def get_emulator_for_platform(slug):
    """Return the first emulator that supports the given platform slug."""
    all_emus = load_emulators()
    for emu in all_emus:
        if slug in emu.get("platform_slugs", []):
            return emu
    return None

def get_all_emulators():
    """Return the full list of emulators."""
    return load_emulators()

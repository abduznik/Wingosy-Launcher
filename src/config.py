import json
import os
import shutil
import copy
from pathlib import Path

class ConfigManager:
    DEFAULT_CONFIG = {
        "host": "http://localhost:8285",
        "username": "admin",
        "password": "",
        "token": None,
        "auto_track": False,
        "auto_pull_saves": True,
        "device_id": "wingosy-win-default",
        "base_rom_path": str(Path.home() / "Games" / "ROMs"),
        "base_emu_path": str(Path.home() / "Games" / "Emulators"),
        "preferred_emulators": {
            "switch": "Switch (Eden)"
        },
        "emulators": {
            "Switch (Yuzu)": {
                "exe": "yuzu.exe", 
                "type": "folder", 
                "title_id_regex": r"01[0-9a-f]{14}",
                "path": "",
                "config_path": str(Path(os.path.expandvars(r'%APPDATA%\yuzu\config'))),
                "github": "pineapple-emu/pineapple-src",
                "platform_slug": "switch",
                "folder": "yuzu",
                "portable_trigger": "user"
            },
            "Switch (Eden)": {
                "exe": "eden.exe",
                "type": "folder",
                "path": "",
                "config_path": str(Path(os.path.expandvars(r'%APPDATA%\eden\config'))),
                "url": "https://github.com/eden-emulator/Releases/releases/download/v0.2.0-rc1/Eden-Windows-v0.2.0-rc1-amd64-msvc-standard.zip",
                "platform_slug": "switch",
                "folder": "eden",
                "portable_trigger": "user"
            },
            "PlayStation 3": {
                "exe": "rpcs3.exe", 
                "type": "folder", 
                "path": "",
                "config_path": "",
                "github": "RPCS3/rpcs3-binaries-win",
                "platform_slug": "ps3",
                "folder": "rpcs3"
            },
            "Multi-Console (RetroArch)": {
                "exe": "retroarch.exe", 
                "type": "file", 
                "ext": "srm",
                "path": "",
                "config_path": str(Path(os.path.expandvars(r'%APPDATA%\RetroArch\retroarch.cfg'))),
                "url": "https://buildbot.libretro.com/stable/1.22.2/windows/x86_64/RetroArch.7z",
                "platform_slug": "multi",
                "folder": "retroarch"
            },
            "GameCube / Wii": {
                "exe": "Dolphin.exe", 
                "type": "file", 
                "ext": "sav",
                "path": "",
                "config_path": str(Path.home() / "Documents" / "Dolphin Emulator" / "Config"),
                "dolphin_latest": True,
                "platform_slug": "gc",
                "folder": "dolphin",
                "portable_trigger": "portable.txt"
            },
            "PlayStation 2": {
                "exe": "pcsx2-qt.exe", 
                "type": "file", 
                "ext": "ps2",
                "path": "",
                "config_path": str(Path(os.path.expandvars(r'%APPDATA%\PCSX2\config'))),
                "github": "PCSX2/pcsx2",
                "platform_slug": "ps2",
                "folder": "pcsx2",
                "portable_trigger": "portable.txt"
            }
        }
    }

    def __init__(self):
        self.config_dir = Path.home() / ".wingosy"
        self.config_file = self.config_dir / "config.json"
        
        # MIGRATION LOGIC: Be extremely thorough to restore user data
        old_dir = Path.home() / ".argosy"
        if old_dir.exists():
            should_migrate = False
            if not self.config_dir.exists() or not self.config_file.exists():
                should_migrate = True
            else:
                # If .wingosy exists but paths are still defaults, it was a failed rebranding attempt
                try:
                    with open(self.config_file, 'r', encoding='utf-8') as f:
                        current = json.load(f)
                        # Check if critical paths are default or if host is default
                        if "Games" in current.get("base_rom_path", "") or current.get("host") == "http://localhost:8285":
                            should_migrate = True
                except:
                    should_migrate = True

            if should_migrate:
                try:
                    if self.config_dir.exists():
                        shutil.rmtree(self.config_dir)
                    shutil.copytree(old_dir, self.config_dir)
                    print(f"Successfully migrated all settings and library from {old_dir}")
                except Exception as e:
                    print(f"Migration error: {e}")

        # Load fresh copy of default config
        self.data = copy.deepcopy(self.DEFAULT_CONFIG)
        self.load()

    def load(self):
        if self.config_file.exists():
            try:
                with open(self.config_file, 'r', encoding='utf-8') as f:
                    loaded_data = json.load(f)
                    
                    # 1. Restore all top-level settings (Host, Paths, User, etc.)
                    for k, v in loaded_data.items():
                        if k != "emulators":
                            self.data[k] = v
                    
                    # 2. Clean Host URL
                    if self.data["host"]:
                        self.data["host"] = self.data["host"].rstrip('/')

                    # 3. Smart Merge Emulators (Restore paths while allowing metadata updates)
                    loaded_emus = loaded_data.get("emulators", {})
                    for name, current_cfg in self.data["emulators"].items():
                        for old_name, old_data in loaded_emus.items():
                            if old_data.get("exe") == current_cfg["exe"]:
                                # Restore the user's custom emulator path
                                current_cfg["path"] = old_data.get("path", "")
                                break
            except Exception as e:
                print(f"Error loading config: {e}")
        else:
            self.save()

    def save(self):
        self.config_dir.mkdir(parents=True, exist_ok=True)
        try:
            with open(self.config_file, 'w', encoding='utf-8') as f:
                json.dump(self.data, f, indent=4)
        except Exception as e:
            print(f"Error saving config: {e}")

    def get(self, key, default=None):
        return self.data.get(key, default)

    def set(self, key, value):
        self.data[key] = value
        self.save()

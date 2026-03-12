import json
import os
import shutil
import copy
import logging
import base64
import hashlib
import uuid
from pathlib import Path

try:
    import keyring
except ImportError:
    keyring = None

from cryptography.fernet import Fernet

def _get_machine_key() -> bytes:
    """
    Derive a stable Fernet key from machine-specific info.
    Not perfect security but much better than plaintext.
    """
    machine_id = str(uuid.getnode()).encode()
    # Stretch to 32 bytes for Fernet
    key = hashlib.sha256(machine_id).digest()
    return base64.urlsafe_b64encode(key)

def _encrypt_token(token: str) -> str:
    f = Fernet(_get_machine_key())
    return f.encrypt(token.encode()).decode()

def _decrypt_token(encrypted: str) -> str:
    f = Fernet(_get_machine_key())
    return f.decrypt(encrypted.encode()).decode()

EXCLUDED_FROM_CONFIG = {
    "cached_library",
    "cached_platforms",
    "token", # Never save plaintext token
}

class ConfigManager:
    DEFAULT_CONFIG = {
        "host": "http://localhost:8285",
        "username": "admin",
        "auto_track": False,
        "first_run": True,
        "auto_pull_saves": True,
        "cards_per_row": 6,
        "log_level": "INFO",
        "platform_assignments": {},
        "retroarch_save_mode": "srm",
        "device_id": "wingosy-win-default",
        "windows_games_dir": "",
        "windows_sync_enabled": True,
        "windows_conflict_behavior": "ask",
        "conflict_behavior": "ask",
        "sync_interval_seconds": 120,
        "max_save_versions": 5,
        "pcgamingwiki_enabled": True,
        "controller_type": "xinput",
        "base_rom_path": str(Path.home() / "Games" / "ROMs"),
        "base_emu_path": str(Path.home() / "Games" / "Emulators"),
        "preferred_emulators": {
            "switch": "Switch (Eden)"
        },
        "emulators": {
            "Switch (Yuzu)": {
                "exe": "yuzu.exe", 
                "type": "switch", 
                "title_id_regex": r"01[0-9a-f]{14}",
                "path": "",
                "config_path": str(Path(os.path.expandvars(r'%APPDATA%\yuzu\config'))),
                "github": "pineapple-emu/pineapple-src",
                "platform_slug": "switch",
                "platform_slugs": ["switch", "nintendo-switch"],
                "folder": "yuzu",
                "portable_trigger": "user"
            },
            "Switch (Eden)": {
                "exe": "eden.exe",
                "type": "switch",
                "path": "",
                "config_path": str(Path(os.path.expandvars(r'%APPDATA%\eden\config'))),
                "url": "https://github.com/eden-emulator/Releases/releases/download/v0.2.0-rc1/Eden-Windows-v0.2.0-rc1-amd64-msvc-standard.zip",
                "platform_slug": "switch",
                "platform_slugs": ["switch", "nintendo-switch"],
                "folder": "eden",
                "portable_trigger": "user"
            },
            "PlayStation 3": {
                "exe": "rpcs3.exe", 
                "type": "ps3", 
                "path": "",
                "config_path": "",
                "github": "RPCS3/rpcs3-binaries-win",
                "platform_slug": "ps3",
                "platform_slugs": ["ps3", "playstation-3", "playstation3"],
                "folder": "rpcs3",
                "asset_keywords_required": ["windows", "x64"],
                "asset_keywords_exclude": ["installer", "symbols", "debug", "android", "mac", "linux"]
            },
            "Multi-Console (RetroArch)": {
                "exe": "retroarch.exe", 
                "type": "file", 
                "ext": "srm",
                "path": "",
                "config_path": str(Path(os.path.expandvars(r'%APPDATA%\RetroArch\retroarch.cfg'))),
                "url": "https://buildbot.libretro.com/stable/1.22.2/windows/x86_64/RetroArch.7z",
                "platform_slug": "multi",
                "platform_slugs": ["multi"],
                "folder": "retroarch",
                "asset_keywords_required": ["windows", "x64"],
                "asset_keywords_exclude": ["installer", "symbols", "debug", "android", "mac", "linux"]
            },
            "GameCube / Wii": {
                "exe": "Dolphin.exe", 
                "type": "dolphin", 
                "ext": "sav",
                "path": "",
                "config_path": str(Path.home() / "Documents" / "Dolphin Emulator" / "Config"),
                "dolphin_latest": True,
                "platform_slug": "gc",
                "platform_slugs": ["gc", "ngc", "wii", "gamecube", "nintendo-gamecube", "nintendo-wii", "wii-u-vc"],
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
                "platform_slugs": ["ps2", "playstation-2", "playstation2"],
                "folder": "pcsx2",
                "portable_trigger": "portable.txt",
                "asset_keywords_required": ["windows", "x64"],
                "asset_keywords_exclude": ["installer", "symbols", "debug", "android", "mac", "linux"]
            },
            "Wii U (Cemu)": {
                "exe": "Cemu.exe",
                "type": "cemu",
                "path": "",
                "config_path": str(Path(os.path.expandvars(r'%APPDATA%\Cemu'))),
                "url": "https://github.com/cemu-project/Cemu/releases/download/v2.0-60/cemu-2.0-60-windows-x64.zip",
                "platform_slug": "wiiu",
                "platform_slugs": ["wiiu", "wii-u", "nintendo-wii-u", "nintendo-wiiu"],
                "folder": "cemu",
                "portable_trigger": "portable.txt"
            },
            "Nintendo 3DS (Azahar)": {
                "exe": "azahar.exe",
                "type": "folder",
                "path": "",
                "config_path": str(Path(os.path.expandvars(r'%APPDATA%\Azahar\config'))),
                "github": "azahar-emu/azahar",
                "platform_slug": "n3ds",
                "platform_slugs": ["n3ds", "3ds", "nintendo-3ds", "nintendo3ds", "new-nintendo-3ds", "new-nintendo-3ds-xl"],
                "folder": "azahar",
                "asset_keywords_required": ["windows", "msys2"],
                "asset_keywords_exclude": ["msvc", "installer", "symbols", "android", "mac", "linux", "appimage"]
            }
        }
    }

    def __init__(self):
        self.config_dir = Path.home() / ".wingosy"
        self.config_file = self.config_dir / "config.json"
        self._token_memory_only = None
        
        # MIGRATION LOGIC: Be extremely thorough to restore user data
        old_dir = Path.home() / ".argosy"
        if old_dir.exists():
            should_migrate = False
            if not self.config_dir.exists() or not self.config_file.exists():
                should_migrate = True
            else:
                # If .wingosy exists but host is still default, it was a failed rebranding attempt
                try:
                    with open(self.config_file, 'r', encoding='utf-8') as f:
                        current = json.load(f)
                        if current.get("host") == "http://localhost:8285":
                            should_migrate = True
                except:
                    should_migrate = True

            if should_migrate:
                try:
                    if self.config_dir.exists():
                        shutil.rmtree(self.config_dir, ignore_errors=True)
                    shutil.copytree(old_dir, self.config_dir)
                    print(f"Successfully migrated all settings and library from {old_dir}")
                except Exception as e:
                    print(f"Migration error: {e}")

        # Load fresh copy of default config
        self.data = copy.deepcopy(self.DEFAULT_CONFIG)
        self.load()
        
        # Clean up heavy legacy keys from memory immediately
        self.data.pop("cached_library", None)
        self.data.pop("cached_platforms", None)

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
                    if self.data.get("host"):
                        self.data["host"] = self.data["host"].rstrip('/')

                    # 3. Migration: if token exists in loaded_data, move to secure storage
                    if "token" in loaded_data:
                        token = loaded_data["token"]
                        if token:
                            self.save_token(token)
                        
                        # Remove from self.data and save immediately to strip from config.json
                        self.data.pop("token", None)
                        self.save()

                    # 4. Smart Merge Emulators (Restore paths while allowing metadata updates)
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
            # Build filtered dict excluding heavy or sensitive keys
            save_data = {
                k: v for k, v in self.data.items()
                if k not in EXCLUDED_FROM_CONFIG
            }
            
            with open(self.config_file, 'w', encoding='utf-8') as f:
                json.dump(save_data, f, indent=4)
        except Exception as e:
            print(f"Error saving config: {e}")

    def get(self, key, default=None):
        return self.data.get(key, default)

    def set(self, key, value):
        if value is None:
            self.data.pop(key, None)
        else:
            if key == "token":
                self.save_token(value)
                return
            
            self.data[key] = value
        self.save()

    def save_token(self, token: str):
        # 1. Try keyring first (best)
        try:
            if keyring:
                keyring.set_password("wingosy", "auth_token", token)
                # Mark that keyring worked
                self.data.pop("encrypted_token", None)
                self.data.pop("keyring_failed", None)
                self.save()
                return
        except Exception as e:
            logging.warning(f"keyring unavailable: {e}")

        # 2. Fallback: encrypted token in config.json
        try:
            self.data["encrypted_token"] = _encrypt_token(token)
            self.data["keyring_failed"] = True
            self.save()
            logging.warning("Token stored encrypted in config.json (keyring unavailable)")
        except Exception as e:
            logging.error(f"Could not persist token: {e}")
            # 3. Last resort: memory only
            self._token_memory_only = token
            self.data["keyring_failed"] = True

    def load_token(self) -> str | None:
        # 1. Try keyring
        try:
            if keyring:
                token = keyring.get_password("wingosy", "auth_token")
                if token:
                    return token
        except Exception:
            pass

        # 2. Try encrypted fallback in config.json
        encrypted = self.data.get("encrypted_token")
        if encrypted:
            try:
                return _decrypt_token(encrypted)
            except Exception as e:
                logging.error(f"Could not decrypt token: {e}")

        # 3. Memory only or legacy plaintext
        return self._token_memory_only or self.data.get("token")

    def delete_token(self):
        # Clear keyring
        try:
            if keyring:
                keyring.delete_password("wingosy", "auth_token")
        except Exception:
            pass
        # Clear encrypted fallback
        self.data.pop("encrypted_token", None)
        self.data.pop("keyring_failed", None)
        # Clear memory
        self._token_memory_only = None
        self.save()

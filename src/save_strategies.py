"""
Save Strategy Pattern for Wingosy.

To add a new save mode:
1. Create a class inheriting SaveStrategy
2. Set mode_id = "your_mode_name"
3. Implement get_save_files() and restore_save_files()
4. Register it in STRATEGY_REGISTRY

That's it — no other files need changing.
"""

import os
import logging
import shutil
import zipfile
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Optional


class SaveStrategy(ABC):
    """
    Base class for all save strategies.
    Each strategy knows how to:
    - Find local save files for a ROM
    - Restore downloaded saves to the correct location
    """
    
    # Override in subclass
    mode_id: str = ""
    
    def __init__(self, config: dict, emulator: dict):
        self.config   = config
        self.emulator = emulator
    
    @abstractmethod
    def get_save_files(self, rom: dict) -> list[Path]:
        """
        Return list of local save file Paths for this ROM.
        Empty list = no saves.
        """
        ...
    
    @abstractmethod
    def restore_save_files(self, rom: dict, save_data: bytes, filename: str) -> bool:
        """
        Write save_data to the correct local path.
        Return True on success.
        """
        ...
    
    def get_save_dir(self, rom: dict) -> Optional[Path]:
        """
        Optional: return the save directory for this ROM if applicable.
        Override if needed.
        """
        return None

    def _get_rom_stem(self, rom: dict) -> str:
        """Try different possible keys to find the ROM filename stem."""
        for key in ("file_name", "fs_name", "rom_path", "path"):
            val = rom.get(key, "")
            if val:
                return Path(val).stem
        # Last resort: use display name
        return rom.get("name", "")
    
    def _parse_ra_cfg(self, cfg_path: str) -> Optional[Path]:
        """Helper to parse retroarch.cfg for savefile_directory."""
        if not cfg_path or not Path(cfg_path).exists():
            return None
        try:
            with open(cfg_path, 'r', encoding='utf-8', errors='replace') as f:
                for line in f:
                    line = line.strip()
                    if line.startswith("savefile_directory"):
                        parts = line.split("=", 1)
                        if len(parts) == 2:
                            d = parts[1].strip().strip('"')
                            if d and d != "default":
                                return Path(d)
        except Exception as e:
            logging.warning(f"[Strategy] RA cfg parse error at {cfg_path}: {e}")
        return None

    def _get_retroarch_save_dir(self) -> Optional[Path]:
        """Helper for RetroArch strategies with fallbacks."""
        # 1. Try configured retroarch.cfg path from emulator
        ra_cfg = self.emulator.get("config_path", "")
        if ra_cfg:
            res = self._parse_ra_cfg(ra_cfg)
            if res: return res
            
        # 2. Try global config
        ra_cfg_global = self.config.get("retroarch_config", "")
        if ra_cfg_global:
            res = self._parse_ra_cfg(ra_cfg_global)
            if res: return res

        # 3. Try to find retroarch.cfg next to the emulator executable
        exe = self.emulator.get("executable_path", "")
        if exe:
            cfg_next_to_exe = Path(exe).parent / "retroarch.cfg"
            if cfg_next_to_exe.exists():
                res = self._parse_ra_cfg(str(cfg_next_to_exe))
                if res: return res
        
        # 4. Try default RetroArch save locations on Windows
        import sys
        if sys.platform == "win32":
            candidates = [
                Path.home() / "AppData" / "Roaming" / "RetroArch" / "saves",
                Path.home() / "AppData" / "Roaming" / "RetroArch" / "states",
            ]
            for c in candidates:
                if c.exists():
                    return c
                    
        return None


class RetroArchStrategy(SaveStrategy):
    """
    Handles RetroArch .srm save files.
    """
    mode_id = "retroarch"
    
    def get_save_files(self, rom: dict) -> list[Path]:
        save_dir = self._get_retroarch_save_dir()
        rom_stem = self._get_rom_stem(rom)
        
        if not rom_stem:
            logging.warning(f"[RetroArchStrategy] No ROM stem found. Keys: {list(rom.keys())}")
            return []
        
        candidates = []
        if save_dir and save_dir.exists():
            # Check for subfolders or direct files
            for p in save_dir.rglob(f"{rom_stem}.srm"): candidates.append(p)
            for p in save_dir.rglob(f"{rom_stem}.sav"): candidates.append(p)
            for p in save_dir.rglob(f"{rom_stem}.state*"): candidates.append(p)
            
        return candidates
    
    def restore_save_files(self, rom: dict, save_data: bytes, filename: str) -> bool:
        save_dir = self._get_retroarch_save_dir()
        rom_stem = self._get_rom_stem(rom)
        
        if not rom_stem:
            return False
        
        dest_dir = save_dir
        if not dest_dir:
            return False
        
        dest_dir.mkdir(parents=True, exist_ok=True)
        
        dest_name = filename if filename.endswith((".srm", ".sav")) else f"{rom_stem}.srm"
        if ".state" in filename:
            dest_name = filename

        dest = dest_dir / dest_name
        try:
            dest.write_bytes(save_data)
            logging.info(f"[RetroArchStrategy] Restored: {dest}")
            return True
        except Exception as e:
            logging.error(f"[RetroArchStrategy] Write failed: {e}")
            return False
    
    def get_save_dir(self, rom: dict) -> Optional[Path]:
        return self._get_retroarch_save_dir()


class FolderStrategy(SaveStrategy):
    """
    Handles emulators that store saves in a dedicated folder.
    """
    mode_id = "folder"
    
    def _base_dir(self, rom: dict) -> Optional[Path]:
        res = self.emulator.get("save_resolution", {})
        save_dir = res.get("path") or res.get("save_dir") or res.get("srm_dir")
        if not save_dir:
            return None
        return Path(save_dir)
    
    def get_save_files(self, rom: dict) -> list[Path]:
        base = self._base_dir(rom)
        if not base or not base.exists():
            return []
        return [p for p in base.rglob("*") if p.is_file()]
    
    def restore_save_files(self, rom: dict, save_data: bytes, filename: str) -> bool:
        base = self._base_dir(rom)
        if not base:
            return False
        
        base.mkdir(parents=True, exist_ok=True)
        dest = base / filename
        try:
            dest.write_bytes(save_data)
            logging.info(f"[FolderStrategy] Restored: {dest}")
            return True
        except Exception as e:
            logging.error(f"[FolderStrategy] Write failed: {e}")
            return False
    
    def get_save_dir(self, rom: dict) -> Optional[Path]:
        return self._base_dir(rom)


class FileStrategy(SaveStrategy):
    """
    Handles emulators that use a single save file per ROM.
    """
    mode_id = "file"
    
    def _save_path(self, rom: dict) -> Optional[Path]:
        res = self.emulator.get("save_resolution", {})
        save_dir = res.get("path") or res.get("save_dir") or res.get("srm_dir")
        rom_stem = self._get_rom_stem(rom)
        
        if not rom_stem or not save_dir:
            return None
        
        base = Path(save_dir)
        target_ext = res.get("extension")
        if target_ext:
            if not target_ext.startswith("."): target_ext = "." + target_ext
            return base / f"{rom_stem}{target_ext}"

        for ext in (".sav", ".srm", ".save", ".dat"):
            p = base / f"{rom_stem}{ext}"
            if p.exists(): return p
        
        return base / f"{rom_stem}.sav"
    
    def get_save_files(self, rom: dict) -> list[Path]:
        p = self._save_path(rom)
        if p and p.exists():
            return [p]
        return []
    
    def restore_save_files(self, rom: dict, save_data: bytes, filename: str) -> bool:
        p = self._save_path(rom)
        if not p:
            return False
        
        p.parent.mkdir(parents=True, exist_ok=True)
        try:
            p.write_bytes(save_data)
            logging.info(f"[FileStrategy] Restored: {p}")
            return True
        except Exception as e:
            logging.error(f"[FileStrategy] Write failed: {e}")
            return False
    
    def get_save_dir(self, rom: dict) -> Optional[Path]:
        p = self._save_path(rom)
        return p.parent if p else None


class WindowsNativeStrategy(SaveStrategy):
    """
    Handles Windows native games.
    """
    mode_id = "windows"
    
    def get_save_files(self, rom: dict) -> list[Path]:
        from src import windows_saves
        save_dir = windows_saves.get_save_dir(rom.get("id"))
        if not save_dir:
            return []
        p = Path(save_dir)
        if not p.exists():
            return []
        return [f for f in p.rglob("*") if f.is_file()]
    
    def restore_save_files(self, rom: dict, save_data: bytes, filename: str) -> bool:
        from src import windows_saves
        save_dir = windows_saves.get_save_dir(rom.get("id"))
        if not save_dir:
            return False
        dest = Path(save_dir) / filename
        dest.parent.mkdir(parents=True, exist_ok=True)
        try:
            dest.write_bytes(save_data)
            return True
        except Exception as e:
            logging.error(f"[WindowsStrategy] Write failed: {e}")
            return False
    
    def get_save_dir(self, rom: dict) -> Optional[Path]:
        from src import windows_saves
        d = windows_saves.get_save_dir(rom.get("id"))
        return Path(d) if d else None


# ── Registry ─────────────────────────────

STRATEGY_REGISTRY: dict[str, type[SaveStrategy]] = {
    "retroarch": RetroArchStrategy,
    "folder": FolderStrategy,
    "file": FileStrategy,
    "direct_file": FileStrategy,
    "windows": WindowsNativeStrategy,
}

def get_strategy(config: dict, emulator: dict) -> SaveStrategy:
    """
    Return the correct SaveStrategy for an emulator.
    """
    mode = emulator.get("save_resolution", {}).get("mode", "retroarch")
    if emulator.get("id") == "windows_native" or emulator.get("is_native"):
        mode = "windows"
    
    cls = STRATEGY_REGISTRY.get(mode, RetroArchStrategy)
    return cls(config, emulator)

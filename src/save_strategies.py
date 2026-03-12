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
        self.session_start_time = 0.0
        self.rom_path = ""
    
    def set_session_context(self, start_time: float, rom_path: str):
        """Used by complex strategies to filter files by mtime or extract Title IDs."""
        self.session_start_time = start_time
        self.rom_path = rom_path

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

    def _backup_save(self, path: Path):
        """Implement a rotation scheme capped at 3 versions for files or folders."""
        if not path or not path.exists():
            return

        import shutil
        bak  = Path(str(path) + ".bak")
        bak1 = Path(str(path) + ".bak1")
        bak2 = Path(str(path) + ".bak2")

        try:
            # 1. Rotate backups
            if bak2.exists():
                if bak2.is_dir(): shutil.rmtree(bak2)
                else: bak2.unlink()
            
            if bak1.exists():
                bak1.rename(bak2)
            
            if bak.exists():
                bak.rename(bak1)

            # 2. Copy current to .bak
            if path.is_dir():
                shutil.copytree(path, bak, dirs_exist_ok=True)
            else:
                shutil.copy2(path, bak)
            
            logging.info(f"[Strategy] Backup created for {path.name}")
        except Exception as e:
            logging.error(f"[Strategy] Backup failed for {path.name}: {e}")

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
    Handles RetroArch .srm and .state.auto save files.
    Uses direct path construction from the exe location first (fast, reliable),
    then falls back to retroarch.cfg-based resolution.
    """
    mode_id = "retroarch"

    def _get_ra_paths(self, rom: dict):
        """
        Return (srm_path, state_path, save_folder_dir) using the same direct-
        construction logic as the working 0.5.x branch.
        Returns (None, None, None) if the exe is unknown.
        """
        from src.platforms import RETROARCH_CORES, RETROARCH_CORE_SAVE_FOLDERS
        exe = self.emulator.get("executable_path", "")
        if not exe or not Path(exe).exists():
            return None, None, None

        ra_dir = Path(exe).parent
        platform_slug = rom.get("platform_slug", "")
        rom_stem = self._get_rom_stem(rom)
        if not rom_stem:
            return None, None, None

        # PSP: folder-based SAVEDATA
        if platform_slug in ("psp", "playstation-portable"):
            psp_saves = ra_dir / "saves" / "PPSSPP" / "PSP" / "SAVEDATA"
            state = ra_dir / "states" / "PPSSPP" / f"{rom_stem}.state.auto"
            return None, state, psp_saves  # treat srm=None, state=auto, save_dir=psp_saves folder

        core_dll = RETROARCH_CORES.get(platform_slug, "")
        if not core_dll:
            return None, None, None

        core_name = (core_dll.replace(".dll", "").replace(".so", "")
                              .replace("_libretro", ""))
        save_folder = RETROARCH_CORE_SAVE_FOLDERS.get(core_name, core_name)

        srm   = ra_dir / "saves"  / save_folder / f"{rom_stem}.srm"
        state = ra_dir / "states" / save_folder / f"{rom_stem}.state.auto"
        save_dir = ra_dir / "saves" / save_folder
        return srm, state, save_dir

    def get_save_files(self, rom: dict) -> list[Path]:
        rom_stem = self._get_rom_stem(rom)
        if not rom_stem:
            logging.warning(f"[RetroArchStrategy] No ROM stem for {rom.get('name')}")
            return []

        # Fast path — direct construction (no rglob)
        srm, state, save_dir = self._get_ra_paths(rom)
        
        # SPECIAL CASE: PSP (Folder-based)
        platform_slug = rom.get("platform_slug", "")
        if platform_slug in ("psp", "playstation-portable"):
            psp_results = []
            if save_dir and save_dir.is_dir():
                if self.session_start_time > 0:
                    # We are in handle_exit/mid-session sync. 
                    # Scan for the specific GameID folder that was modified during play.
                    changed_dirs = []
                    for d in save_dir.iterdir():
                        if d.is_dir():
                            try:
                                if d.stat().st_mtime > self.session_start_time:
                                    changed_dirs.append(d)
                            except: pass
                    if changed_dirs:
                        # If multiple changed (unlikely), use the most recently modified one
                        changed_dirs.sort(key=lambda x: x.stat().st_mtime, reverse=True)
                        psp_results.append(changed_dirs[0])
                else:
                    # At start of session or if no change detected yet, return the whole SAVEDATA 
                    # so watcher captures the state of the entire folder for comparison.
                    psp_results.append(save_dir)
            
            # Also include auto-state if it exists
            if state and state.exists():
                psp_results.append(state)
                
            if psp_results:
                return psp_results

        if srm is not None or save_dir is not None:
            candidates = []
            if srm is None and save_dir and save_dir.is_dir():
                # Generic folder-based fallback (other cores)
                candidates.append(save_dir)
            else:
                if srm and srm.exists():
                    candidates.append(srm)
                if state and state.exists():
                    candidates.append(state)
            if candidates:
                return candidates

        # Slow fallback — config-based rglob
        fallback_dir = self._get_retroarch_save_dir()
        if not fallback_dir or not fallback_dir.exists():
            return []
        candidates = []
        for p in fallback_dir.rglob(f"{rom_stem}.srm"):   candidates.append(p)
        for p in fallback_dir.rglob(f"{rom_stem}.sav"):   candidates.append(p)
        for p in fallback_dir.rglob(f"{rom_stem}.state.auto"): candidates.append(p)
        return candidates

    def restore_save_files(self, rom: dict, save_data: bytes, filename: str) -> bool:
        srm, state, save_dir = self._get_ra_paths(rom)
        rom_stem = self._get_rom_stem(rom)
        if not rom_stem:
            return False

        # Determine target path based on file type
        if ".state" in filename:
            # Use specific state path if constructed, else fallback to RA save dir
            dest = state or (self._get_retroarch_save_dir() / filename if self._get_retroarch_save_dir() else None)
            if not dest: return False
            
            # Enforce .state.auto for PSP
            platform_slug = rom.get("platform_slug", "")
            if platform_slug in ("psp", "playstation-portable"):
                dest = dest.with_name(f"{rom_stem}.state.auto")
            
            # Backup state file
            self._backup_save(dest)
        else:
            # Save file (.srm, .sav, or PSP SAVEDATA folder content)
            dest_dir = save_dir or self._get_retroarch_save_dir()
            if not dest_dir: return False
            
            # SPECIAL CASE: PSP (Folder-based SAVEDATA)
            platform_slug = rom.get("platform_slug", "")
            if platform_slug in ("psp", "playstation-portable"):
                # For PSP, filename might be content inside a specific GameID folder.
                # However, RomM currently zips the folder. 
                # If we are restoring individual files, we backup the destination first.
                self._backup_save(dest_dir / filename)
            else:
                self._backup_save(dest_dir / (filename if filename.endswith((".srm", ".sav")) else f"{rom_stem}.srm"))

            dest_name = filename if filename.endswith((".srm", ".sav")) else f"{rom_stem}.srm"
            dest = dest_dir / dest_name

        try:
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(save_data)
            logging.info(f"[RetroArchStrategy] Restored: {dest}")
            return True
        except Exception as e:
            logging.error(f"[RetroArchStrategy] Write failed: {e}")
            return False

    def get_save_dir(self, rom: dict) -> Optional[Path]:
        _, _, save_dir = self._get_ra_paths(rom)
        return save_dir or self._get_retroarch_save_dir()


class SwitchStrategy(SaveStrategy):
    """
    Handles Switch (Yuzu/Eden) Title ID based path discovery.
    Ports SQLite database lookup and XCI header parsing from legacy branch.
    """
    mode_id = "switch"

    def _resolve_title_id(self, rom: dict) -> Optional[str]:
        import re
        import sqlite3
        
        emu_dir = Path(self.emulator.get("executable_path", "")).parent
        search_roots = [
            emu_dir / "user",
            Path(os.path.expandvars(r'%APPDATA%\eden')),
            Path(os.path.expandvars(r'%APPDATA%\yuzu')),
        ]
        
        # 1. Try SQLite game_list.db lookup
        title = rom.get("name", "")
        for root in search_roots:
            db_path = root / "cache/game_list/game_list.db"
            if db_path.exists():
                try:
                    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
                    cursor = conn.cursor()
                    # Try to find a table with title_id and name
                    cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
                    for (table,) in cursor.fetchall():
                        cursor.execute(f"PRAGMA table_info({table})")
                        cols = [c[1].lower() for c in cursor.fetchall()]
                        id_col = next((c for c in cols if c in ('title_id', 'program_id', 'id')), None)
                        name_col = next((c for c in cols if 'name' in c or 'title' in c), None)
                        if id_col and name_col:
                            cursor.execute(f"SELECT {id_col} FROM {table} WHERE {name_col} LIKE ? LIMIT 1", (f"%{title}%",))
                            row = cursor.fetchone()
                            if row:
                                tid = hex(row[0])[2:].upper().zfill(16) if isinstance(row[0], int) else str(row[0]).upper().replace('0X', '')
                                if re.match(r'^[0-9A-F]{16}$', tid):
                                    conn.close()
                                    return tid
                    conn.close()
                except Exception: pass

        # 2. Try XCI Header parsing (offset 0x108)
        rom_p = Path(self.rom_path)
        if rom_p.exists() and rom_p.suffix.lower() == ".xci":
            try:
                with open(rom_p, "rb") as f:
                    f.seek(0x108)
                    tid = f.read(8)[::-1].hex().upper()
                    if re.match(r'^01[0-9A-F]{14}$', tid):
                        return tid
            except Exception: pass

        # 3. Last resort: most recently modified 16-char folder
        recent_tid, max_mtime = None, 0
        for root in search_roots:
            save_base = root / "nand/user/save/0000000000000000"
            if not save_base.exists(): continue
            for profile_dir in save_base.iterdir():
                if not profile_dir.is_dir(): continue
                for tid_dir in profile_dir.iterdir():
                    if tid_dir.is_dir() and re.match(r'^01[0-9A-F]{14}$', tid_dir.name):
                        if tid_dir.stat().st_mtime > max_mtime:
                            max_mtime = tid_dir.stat().st_mtime
                            recent_tid = tid_dir.name
        return recent_tid

    def _base_dir(self, rom: dict) -> Optional[Path]:
        tid = self._resolve_title_id(rom)
        if not tid: return None
        
        emu_dir = Path(self.emulator.get("executable_path", "")).parent
        search_roots = [
            emu_dir / "user",
            Path(os.path.expandvars(r'%APPDATA%\eden')),
            Path(os.path.expandvars(r'%APPDATA%\yuzu')),
        ]
        
        for root in search_roots:
            save_base = root / "nand/user/save/0000000000000000"
            if not save_base.exists(): continue
            for profile_dir in save_base.iterdir():
                if not profile_dir.is_dir(): continue
                candidate = profile_dir / tid
                if candidate.exists(): return candidate
        return None

    def get_save_files(self, rom: dict) -> list[Path]:
        base = self._base_dir(rom)
        if not base or not base.exists(): return []
        return [p for p in base.rglob("*") if p.is_file()]

    def restore_save_files(self, rom: dict, save_data: bytes, filename: str) -> bool:
        base = self._base_dir(rom)
        if not base: return False
        self._backup_save(base)
        base.mkdir(parents=True, exist_ok=True)
        (base / filename).write_bytes(save_data)
        return True

    def get_save_dir(self, rom: dict) -> Optional[Path]:
        return self._base_dir(rom)


class DolphinStrategy(SaveStrategy):
    """
    Handles Dolphin GCI Folder mode and Region detection.
    Ports .gci change detection logic from legacy branch.
    """
    mode_id = "dolphin"

    def _get_card_dir(self) -> Optional[Path]:
        emu_dir = Path(self.emulator.get("executable_path", "")).parent
        portable_gc = emu_dir / "User" / "GC"
        documents_gc = Path.home() / "Documents" / "Dolphin Emulator" / "GC"
        gc_base = portable_gc if portable_gc.exists() else documents_gc
        
        # Region detection
        rom_upper = self.rom_path.upper()
        region = "USA"
        if any(r in rom_upper for r in ["EUR", "PAL", "EUROPE"]): region = "EUR"
        elif any(r in rom_upper for r in ["JAP", "JPN", "JAPAN"]): region = "JAP"
        
        return gc_base / region / "Card A"

    def get_save_files(self, rom: dict) -> list[Path]:
        card_dir = self._get_card_dir()
        if not card_dir or not card_dir.exists(): return []
        
        # If we have a session start time, only sync .gci files modified AFTER launch
        if self.session_start_time > 0:
            changed = []
            for gci in card_dir.glob("*.gci"):
                try:
                    if gci.stat().st_mtime > self.session_start_time:
                        changed.append(gci)
                except Exception: pass
            return changed
            
        return [p for p in card_dir.glob("*.gci") if p.is_file()]

    def restore_save_files(self, rom: dict, save_data: bytes, filename: str) -> bool:
        card_dir = self._get_card_dir()
        if not card_dir: return False
        card_dir.mkdir(parents=True, exist_ok=True)
        (card_dir / filename).write_bytes(save_data)
        return True

    def get_save_dir(self, rom: dict) -> Optional[Path]:
        return self._get_card_dir()


class PS3Strategy(SaveStrategy):
    """
    Handles RPCS3 Title ID based savedata mapping.
    """
    mode_id = "ps3"

    def _base_dir(self, rom: dict) -> Optional[Path]:
        import re
        emu_dir = Path(self.emulator.get("executable_path", "")).parent
        save_base = emu_dir / "dev_hdd0/home/00000001/savedata"
        if not save_base.exists():
            save_base = Path(os.path.expandvars(r'%APPDATA%\RPCS3\dev_hdd0\home\00000001\savedata'))
        
        if not save_base.exists(): return None
        
        # Try Title ID from ROM path
        tid_match = re.search(r'([A-Z]{4}\d{5})', self.rom_path)
        if tid_match:
            candidate = save_base / tid_match.group(1).upper()
            if candidate.exists(): return candidate
            
        # Fallback: scan subdirs for PARAM.SFO and use most recent
        subdirs = sorted([d for d in save_base.iterdir() if d.is_dir() and (d / "PARAM.SFO").exists()], 
                         key=lambda x: x.stat().st_mtime, reverse=True)
        if subdirs: return subdirs[0]
        
        return save_base

    def get_save_files(self, rom: dict) -> list[Path]:
        base = self._base_dir(rom)
        if not base or not base.exists(): return []
        return [p for p in base.rglob("*") if p.is_file()]

    def restore_save_files(self, rom: dict, save_data: bytes, filename: str) -> bool:
        base = self._base_dir(rom)
        if not base: return False
        self._backup_save(base)
        base.mkdir(parents=True, exist_ok=True)
        (base / filename).write_bytes(save_data)
        return True

    def get_save_dir(self, rom: dict) -> Optional[Path]:
        return self._base_dir(rom)


class CemuStrategy(SaveStrategy):
    """
    Handles Wii U (Cemu) mlc01 and User ID mapping.
    """
    mode_id = "cemu"

    def _base_dir(self, rom: dict) -> Optional[Path]:
        emu_dir = Path(self.emulator.get("executable_path", "")).parent
        mlc_path = emu_dir / "mlc01"
        if not mlc_path.exists():
            # Try to parse settings.xml for custom mlc_path
            settings_xml = emu_dir / "settings.xml"
            if settings_xml.exists():
                try:
                    import xml.etree.ElementTree as ET
                    mlc_node = ET.parse(settings_xml).getroot().find('.//mlc_path')
                    if mlc_node is not None and mlc_node.text: mlc_path = Path(mlc_node.text)
                except Exception: pass
        
        if not mlc_path or not mlc_path.exists():
            mlc_path = Path(os.path.expandvars(r'%APPDATA%\Cemu\mlc01'))

        save_base = mlc_path / "usr/save/00050000"
        if not save_base.exists(): return None
        
        # Find most recently modified title folder
        title_dirs = sorted([d for d in save_base.iterdir() if d.is_dir()], key=lambda x: x.stat().st_mtime, reverse=True)
        for title_dir in title_dirs:
            candidate = title_dir / "user" / "80000001"
            if candidate.exists(): return candidate
            
        return None

    def get_save_files(self, rom: dict) -> list[Path]:
        base = self._base_dir(rom)
        if not base or not base.exists(): return []
        return [p for p in base.rglob("*") if p.is_file()]

    def restore_save_files(self, rom: dict, save_data: bytes, filename: str) -> bool:
        base = self._base_dir(rom)
        if not base: return False
        self._backup_save(base)
        base.mkdir(parents=True, exist_ok=True)
        (base / filename).write_bytes(save_data)
        return True

    def get_save_dir(self, rom: dict) -> Optional[Path]:
        return self._base_dir(rom)


# Emulator-specific auto-detection hints: id -> list of candidate Path lambdas (tried in order)
_EMU_SAVE_HINTS: dict[str, list] = {
    "pcsx2":   [lambda e: Path(e).parent / "memcards",
                lambda _: Path.home() / "Documents" / "PCSX2" / "memcards"],
    "dolphin": [lambda e: Path(e).parent / "User" / "GC",
                lambda _: Path.home() / "Documents" / "Dolphin Emulator" / "GC"],
    "rpcs3":   [lambda e: Path(e).parent / "dev_hdd0" / "home" / "00000001" / "savedata",
                lambda _: Path.home() / "AppData" / "Roaming" / "rpcs3" / "dev_hdd0" / "home" / "00000001" / "savedata"],
    "eden":    [lambda _: Path.home() / "AppData" / "Roaming" / "eden" / "nand" / "user" / "save",
                lambda _: Path.home() / "AppData" / "Roaming" / "yuzu" / "nand" / "user" / "save"],
    "cemu":    [lambda e: Path(e).parent / "mlc01" / "usr" / "save",
                lambda _: Path.home() / "AppData" / "Roaming" / "Cemu" / "mlc01" / "usr" / "save"],
    "azahar":  [lambda _: Path.home() / "AppData" / "Roaming" / "Azahar" / "user" / "sdmc",
                lambda _: Path.home() / "AppData" / "Roaming" / "azahar" / "user" / "sdmc"],
}


class FolderStrategy(SaveStrategy):
    """
    Handles emulators that store saves in a dedicated folder.
    Falls back to emulator-specific auto-detection when path is not configured.
    """
    mode_id = "folder"

    def _base_dir(self, rom: dict) -> Optional[Path]:
        res = self.emulator.get("save_resolution", {})
        save_dir = res.get("path") or res.get("save_dir") or res.get("srm_dir")
        if save_dir:
            return Path(save_dir)
        # Auto-detect based on emulator id
        emu_id = self.emulator.get("id", "")
        exe = self.emulator.get("executable_path", "")
        for hint in _EMU_SAVE_HINTS.get(emu_id, []):
            try:
                p = hint(exe)
                if p.exists():
                    return p
            except Exception:
                continue
        return None
    
    def get_save_files(self, rom: dict) -> list[Path]:
        base = self._base_dir(rom)
        if not base or not base.exists():
            return []
        return [p for p in base.rglob("*") if p.is_file() and ".bak" not in p.name.lower()]
    
    def restore_save_files(self, rom: dict, save_data: bytes, filename: str) -> bool:
        base = self._base_dir(rom)
        if not base:
            return False
        
        self._backup_save(base)
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
        
        self._backup_save(p)
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
        
        dest_dir = Path(save_dir)
        self._backup_save(dest_dir)
        
        dest = dest_dir / filename
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
    "switch": SwitchStrategy,
    "dolphin": DolphinStrategy,
    "ps3": PS3Strategy,
    "cemu": CemuStrategy,
}

def get_strategy(config: dict, emulator: dict) -> SaveStrategy:
    """
    Return the correct SaveStrategy for an emulator.
    """
    mode = emulator.get("save_resolution", {}).get("mode", "retroarch")
    emu_id = emulator.get("id", "")

    if emu_id == "windows_native" or emulator.get("is_native"):
        mode = "windows"

    # Map specialized emulators to their strategies by ID if mode is generic
    # This ensures specialized Title ID logic is used for PS3, Switch, Dolphin, etc.
    if mode in ("folder", "file", "retroarch"):
        # Explicit mapping for IDs that differ from registry keys
        if emu_id == "eden": mode = "switch"
        elif emu_id == "rpcs3": mode = "ps3"
        elif emu_id in STRATEGY_REGISTRY and emu_id not in ("folder", "file", "retroarch"):
            mode = emu_id

    # Emulators configured as 'file' but with no path should use folder auto-detection
    if mode in ("file", "direct_file"):
        path = emulator.get("save_resolution", {}).get("path", "")
        if not path and emu_id in _EMU_SAVE_HINTS:
            mode = "folder"

    cls = STRATEGY_REGISTRY.get(mode, RetroArchStrategy)
    return cls(config, emulator)

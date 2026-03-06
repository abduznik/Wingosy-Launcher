import time
import psutil
import os
import re
import shutil
import zipfile
import json
import hashlib
from pathlib import Path
from PySide6.QtCore import QThread, Signal
from src.utils import calculate_folder_hash, calculate_file_hash, calculate_zip_content_hash, zip_path
from src.platforms import RETROARCH_PLATFORMS, platform_matches

class WingosyWatcher(QThread):
    log_signal = Signal(str)
    path_detected_signal = Signal(str, str) # emu_display_name, path
    conflict_signal = Signal(str, str, str, str) # title, local_path, temp_dl, rom_id
    notify_signal = Signal(str, str) # title, msg

    def __init__(self, client, config_manager):
        super().__init__()
        self.client = client
        self.config = config_manager
        self.running = True
        self.active_sessions = {}
        self.skip_next_pull_rom_id = None # Flag to prevent double-pull when launching from app
        
        self.tmp_dir = Path.home() / ".wingosy" / "tmp"
        self.tmp_dir.mkdir(parents=True, exist_ok=True)
        
        self.cache_path = Path.home() / ".wingosy" / "sync_cache.json"
        self.sync_cache = {}
        if self.cache_path.exists():
            try:
                with open(self.cache_path, 'r') as f:
                    self.sync_cache = json.load(f)
            except Exception as e:
                print(f"[Watcher] Cache load error: {e}")

    def save_cache(self):
        try:
            with open(self.cache_path, 'w') as f:
                json.dump(self.sync_cache, f)
        except Exception as e:
            print(f"[Watcher] Cache save error: {e}")

    def run(self):
        self.log_signal.emit("🚀 Watcher Active (Process-Specific Mode).")
        while self.running:
            # Only poll processes we are explicitly tracking
            for pid, data in list(self.active_sessions.items()):
                try:
                    # Check if process is still running
                    if not psutil.pid_exists(pid):
                        self.handle_exit(data)
                        del self.active_sessions[pid]
                    else:
                        # Optional: periodically verify it's still the SAME process (unlikely to collide in short term)
                        pass
                except Exception as e:
                    self.log_signal.emit(f"❌ Error monitoring PID {pid}: {e}")
                    del self.active_sessions[pid]
            
            time.sleep(2)

    def _hash_retroarch_game(self, save_path, is_folder=False):
        """
        Hash the SRM + all state files for a RetroArch game.
        For folder-based cores (PSP), hashes the entire folder tree.
        """
        if is_folder:
            from src.utils import calculate_folder_hash
            try:
                return calculate_folder_hash(str(save_path))
            except Exception:
                return None

        srm = Path(save_path)
        core_dir = srm.parent
        stem = srm.stem  # e.g. "Super Punch-Out!! (USA)"
        
        # Collect: the .srm + any .stateN / .state.auto files
        files = []
        if srm.exists():
            files.append(srm)
        for f in sorted(core_dir.glob(f"{stem}.state*")):
            files.append(f)
        
        if not files:
            return None
        
        # Hash all files together
        h = hashlib.sha256()
        for f in files:
            try:
                h.update(f.read_bytes())
            except Exception:
                pass
        return h.hexdigest()

    def _get_folder_mtime(self, path):
        """Return the newest mtime of any file in a folder tree."""
        if not os.path.exists(path):
            return 0
        if os.path.isfile(path):
            return os.path.getmtime(path)
        newest = 0
        for root, dirs, files in os.walk(path):
            for f in files:
                try:
                    t = os.path.getmtime(os.path.join(root, f))
                    if t > newest:
                        newest = t
                except Exception:
                    pass
        return newest

    def track_session(self, proc, emu_display_name, game_data, local_rom_path, emu_path):
        """
        Explicitly track a process launched by the UI.
        """
        try:
            pid = proc.pid
            full_cmd = f"\"{emu_path}\" \"{local_rom_path}\""
            rom_id = game_data['id']
            title = game_data['name']
            platform = game_data.get('platform_slug')

            # 1. Resolve Save Path
            save_path = self.resolve_save_path(emu_display_name, title, full_cmd, emu_path, platform, proc=psutil.Process(pid))
            
            if save_path:
                save_path = str(Path(save_path).resolve())
                folder_platforms = ["switch", "nintendo-switch", "ps3", "playstation-3",
                                    "wii", "nintendo-wii", "wiiu", "wii-u", "nintendo-wii-u",
                                    "n3ds", "3ds", "nintendo-3ds"]
                is_folder = platform in folder_platforms
                if os.path.exists(save_path):
                    is_folder = os.path.isdir(save_path)
                
                # Double-Pull Protection
                should_pull = self.config.get("auto_pull_saves", True)
                if self.skip_next_pull_rom_id == str(rom_id):
                    should_pull = False
                    self.skip_next_pull_rom_id = None

                if should_pull:
                    self.pull_server_save(rom_id, title, save_path, is_folder)
                
                # Track the session with initial state
                is_retroarch = emu_display_name == "Multi-Console (RetroArch)"
                h = self._hash_retroarch_game(save_path, is_folder) if is_retroarch \
                    else (calculate_folder_hash(save_path) if is_folder 
                          else calculate_file_hash(save_path) 
                          if os.path.exists(save_path) else None)

                self.active_sessions[pid] = {
                    'emu': emu_display_name, 
                    'rom_id': rom_id, 
                    'save_path': save_path,
                    'title': title,
                    'initial_hash': h,
                    'initial_mtime': self._get_folder_mtime(save_path),
                    'is_folder': is_folder,
                    'start_time': time.time(),
                    'emu_path': emu_path
                }
                self.log_signal.emit(f"🎮 Tracking {title} on {emu_display_name} (PID: {pid})")
            else:
                self.log_signal.emit(f"⚠️ Identified {title} but could not resolve local save path.")
                
        except Exception as e:
            self.log_signal.emit(f"❌ Error setting up tracking: {e}")

    def pull_server_save(self, rom_id, title, local_path, is_folder, force=False):
        self.log_signal.emit(f"☁️ Checking cloud for {title}...")
        latest_save = self.client.get_latest_save(rom_id)
        if not latest_save: 
            self.log_signal.emit("☁️ No cloud saves found.")
            return

        server_updated_at = latest_save.get('updated_at', '')
        
        # Determine cached updated_at
        rid_str = str(rom_id)
        cached_val = self.sync_cache.get(rid_str)
        cached_updated_at = cached_val.get('updated_at', '') if isinstance(cached_val, dict) else cached_val
        
        # Only skip if timestamp matches AND the local file actually exists
        if not force and cached_updated_at == server_updated_at and os.path.exists(local_path):
            self.log_signal.emit("☁️ Cloud save already up to date.")
            return

        temp_dl = str(self.tmp_dir / f"cloud_check_{rom_id}")
        if self.client.download_save(latest_save, temp_dl):
            is_zip = zipfile.is_zipfile(temp_dl)
                
            if not force and os.path.exists(local_path) and rid_str in self.sync_cache:
                # Save Conflict Detected
                self.log_signal.emit(f"⚠️ Save conflict detected for {title}!")
                self.conflict_signal.emit(title, local_path, temp_dl, rid_str)
                return # Stop here, wait for UI resolution

            self.log_signal.emit(f"📥 Cloud save is different. Updating...")
            
            # Ensure parent dir exists
            os.makedirs(os.path.dirname(local_path), exist_ok=True)

            # Backup
            if os.path.exists(local_path):
                bak_path = str(local_path) + ".bak"
                if os.path.exists(bak_path):
                    if os.path.isdir(bak_path):
                        shutil.rmtree(bak_path, ignore_errors=True)
                    else:
                        try: os.remove(bak_path)
                        except Exception: pass
                
                try:
                    if is_folder:
                        shutil.copytree(local_path, bak_path)
                    else:
                        shutil.copy2(local_path, bak_path)
                except Exception as e:
                    self.log_signal.emit(f"⚠️ Backup failed: {e}")

            # Apply
            try:
                if is_zip:
                    if is_folder:
                        extract_parent = str(Path(local_path).parent)
                        folder_name = Path(local_path).name
                        if os.path.exists(local_path):
                            shutil.rmtree(local_path, ignore_errors=True)
                        os.makedirs(extract_parent, exist_ok=True)
                        with zipfile.ZipFile(temp_dl, 'r') as z:
                            names = z.namelist()
                            has_root = any(n.startswith(folder_name + '/') or 
                                          n.startswith(folder_name + '\\') for n in names)
                            if has_root:
                                z.extractall(extract_parent)
                            else:
                                os.makedirs(local_path, exist_ok=True)
                                z.extractall(local_path)
                    else:
                        with zipfile.ZipFile(temp_dl, 'r') as z:
                            target_member = None
                            for name in z.namelist():
                                if name.endswith(('.ps2', '.srm', '.sav', '.dat', '.sv', '.raw', '.gci')):
                                    target_member = name
                                    break
                            
                            if target_member:
                                with z.open(target_member) as source, open(local_path, 'wb') as target:
                                    shutil.copyfileobj(source, target)
                            else:
                                names = z.namelist()
                                if names:
                                    with z.open(names[0]) as source, open(local_path, 'wb') as target:
                                        shutil.copyfileobj(source, target)
                else:
                    if os.path.isdir(local_path):
                        shutil.rmtree(local_path, ignore_errors=True)
                    shutil.copy2(temp_dl, local_path)
                
                self.sync_cache[rid_str] = server_updated_at
                self.save_cache()
                self.log_signal.emit("✨ Cloud save applied!")
                self.notify_signal.emit(title, "☁️ Cloud save applied")
            except Exception as e:
                self.log_signal.emit(f"❌ Failed to apply save: {e}")
            
            if os.path.exists(temp_dl):
                os.remove(temp_dl)

    def get_game_id_from_rom(self, full_cmd):
        """Extracts GameID from the ROM header directly (GC/Wii)."""
        try:
            m = re.search(r'("[^"]+\.(?:rvz|iso|gcm|wbfs|nfs|ciso|gcz)")', full_cmd)
            if not m: m = re.search(r'(\S+\.(?:rvz|iso|gcm|wbfs|nfs|ciso|gcz))', full_cmd)
            if m:
                path = Path(m.group(1).strip('"'))
                if path.exists():
                    with open(path, 'rb') as f:
                        header = f.read(0x40)
                        if len(header) >= 6:
                            id_str = header[0:6].decode('ascii', errors='ignore')
                            if re.match(r'[A-Z0-9]{6}', id_str):
                                return id_str
                            if len(header) >= 0x16:
                                id_str = header[0x10:0x16].decode('ascii', errors='ignore')
                                if re.match(r'[A-Z0-9]{6}', id_str):
                                    return id_str
        except Exception: pass
        return None

    def resolve_save_path(self, emu_display_name, title, full_cmd, emu_path, platform=None, proc=None):
        try:
            emu_dir = Path(emu_path).parent
            
            # 1. NINTENDO SWITCH
            if "Switch" in emu_display_name or platform == "switch":
                import sqlite3
                title_id = None
                rom_path = None
                m_path = re.search(r'("[^"]+\.(?:xci|nsp|nsz)")', full_cmd)
                if not m_path: m_path = re.search(r'(\S+\.(?:xci|nsp|nsz))', full_cmd)
                if m_path:
                    rom_path = Path(m_path.group(1).strip('"'))

                search_roots = [
                    emu_dir / "user", emu_dir / "data", 
                    Path(os.path.expandvars(r'%APPDATA%\eden')), 
                    Path(os.path.expandvars(r'%APPDATA%\yuzu')), 
                    Path(os.path.expandvars(r'%APPDATA%\sudachi')),
                    Path(os.path.expandvars(r'%APPDATA%\torzu')),
                    Path(os.path.expandvars(r'%LOCALAPPDATA%\yuzu'))
                ]

                emu_lower = emu_display_name.lower()
                prioritized = []
                for root in search_roots:
                    if any(k in root.as_posix().lower() for k in ["eden", "yuzu", "sudachi", "torzu"]) and \
                       any(k in emu_lower for k in ["eden", "yuzu", "sudachi", "torzu"]):
                        for k in ["eden", "yuzu", "sudachi", "torzu"]:
                            if k in root.as_posix().lower() and k in emu_lower:
                                prioritized.append(root); break
                search_roots = prioritized + [r for r in search_roots if r not in prioritized]

                if not title_id:
                    for root in search_roots:
                        db_path = root / "cache/game_list/game_list.db"
                        if db_path.exists():
                            try:
                                conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
                                cursor = conn.cursor()
                                cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
                                tables = [row[0] for row in cursor.fetchall()]
                                for table in tables:
                                    cursor.execute(f"PRAGMA table_info({table})")
                                    cols = [c[1].lower() for c in cursor.fetchall()]
                                    id_col = next((c for c in cols if c in ['title_id', 'program_id', 'id'] or ('id' in c and 'title' in c)), None)
                                    name_col = next((c for c in cols if c in ['name', 'title', 'game_name'] or 'name' in c or 'title' in c), None)
                                    if id_col and name_col:
                                        cursor.execute(f"SELECT {id_col} FROM {table} WHERE {name_col} LIKE ? LIMIT 1", (f"%{title}%",))
                                        row = cursor.fetchone()
                                        if row:
                                            val = row[0]
                                            title_id = hex(val)[2:].upper().zfill(16) if isinstance(val, int) else str(val).upper().replace('0X', '')
                                            if re.match(r'^[0-9A-F]{16}$', title_id): break
                                            else: title_id = None
                                conn.close()
                                if title_id: break
                            except Exception: pass

                if not title_id and rom_path and rom_path.exists() and rom_path.suffix.lower() == ".xci":
                    try:
                        with open(rom_path, "rb") as f:
                            f.seek(0x108)
                            title_id = f.read(8)[::-1].hex().upper()
                            if not re.match(r'^01[0-9A-F]{14}$', title_id): title_id = None
                    except Exception: pass

                if not title_id:
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
                    if recent_tid: title_id = recent_tid

                if title_id:
                    for root in search_roots:
                        save_base = root / "nand/user/save/0000000000000000"
                        if not save_base.exists(): continue
                        for profile_dir in save_base.iterdir():
                            if not profile_dir.is_dir(): continue
                            candidate = profile_dir / title_id
                            if candidate.exists(): return candidate
                        profiles = [d for d in save_base.iterdir() if d.is_dir()]
                        if profiles: return profiles[0] / title_id
                return None

            # 2. GAMECUBE / WII / NGC (DOLPHIN)
            elif "Dolphin" in emu_display_name or platform in ["gc", "wii", "ngc", "gamecube", "nintendo-gamecube", "ngc"]:
                user_dir = Path.home() / "Documents" / "Dolphin Emulator"
                if (emu_dir / "portable.txt").exists(): user_dir = emu_dir / "User"
                elif (emu_dir / "User").exists(): user_dir = emu_dir / "User"
                
                game_id = None
                if proc:
                    try:
                        for f in proc.open_files():
                            p = Path(f.path)
                            if platform == "wii" and "title/00010000" in p.as_posix() and "data" in p.name: return p.parent
                            if platform in ["gc", "ngc"] and (p.suffix.lower() in [".raw", ".gci", ".sav"]): return p
                            if "GameSettings" in p.as_posix() and p.suffix.lower() == ".ini":
                                if len(p.stem) == 6 and re.match(r'[A-Z0-9]{6}', p.stem): game_id = p.stem
                    except Exception: pass

                if not game_id: game_id = self.get_game_id_from_rom(full_cmd)
                
                for region in ["USA", "EUR", "JPN", "KOR", "JAP"]:
                    gci_folder = user_dir / f"GC/{region}/Card A"
                    if not gci_folder.exists(): continue
                    if game_id:
                        for f in gci_folder.glob(f"*{game_id[:4]}*.gci"): return f
                        for f in gci_folder.glob(f"*-{game_id[:4]}-*.gci"): return f
                        for f in gci_folder.glob(f"*{game_id[:3]}*.gci"): return f
                    clean_title = re.sub(r'[^a-z0-9]', '', title.lower())
                    for f in gci_folder.glob("*.gci"):
                        clean_f = re.sub(r'[^a-z0-9]', '', f.stem.lower())
                        if clean_title in clean_f or clean_f in clean_title: return f

                if platform == "wii":
                    nand_base = user_dir / "Wii/title/00010000"
                    if nand_base.exists():
                        subdirs = sorted([d for d in nand_base.iterdir() if d.is_dir()], key=lambda x: x.stat().st_mtime, reverse=True)
                        for d in subdirs:
                            if (d / "data").exists(): return d / "data"
                else:
                    gc_dir = user_dir / "GC"
                    search_paths = [gc_dir / "MemoryCardA.USA.raw", gc_dir / "MemoryCardA.EUR.raw", gc_dir / "MemoryCardA.JPN.raw", gc_dir / "MemoryCardA.raw"]
                    for p in search_paths:
                        if p.exists(): return p
                    return search_paths[0]

            # 3. PLAYSTATION 2
            elif "PlayStation 2" in emu_display_name or platform == "ps2":
                search_paths = [emu_dir / "memcards" / "Mcd001.ps2", Path(os.path.expandvars(r'%APPDATA%\PCSX2\memcards\Mcd001.ps2')), Path.home() / "Documents" / "PCSX2" / "memcards" / "Mcd001.ps2"]
                for p in search_paths:
                    if p.exists(): return p
                return search_paths[0]

            # 3.5 PLAYSTATION 3 (RPCS3)
            elif "PlayStation 3" in emu_display_name or platform == "ps3":
                save_base = emu_dir / "dev_hdd0/home/00000001/savedata"
                if not save_base.exists():
                    save_base = Path(os.path.expandvars(r'%APPDATA%\RPCS3\dev_hdd0\home\00000001\savedata'))
                
                if save_base.exists():
                    tid_match = re.search(r'([A-Z]{4}\d{5})', full_cmd)
                    if tid_match: return save_base / tid_match.group(1).upper()
                    subdirs = sorted([d for d in save_base.iterdir() if d.is_dir() and (d / "PARAM.SFO").exists()], key=lambda x: x.stat().st_mtime, reverse=True)
                    if subdirs: return subdirs[0]
                return save_base

            # 5. WII U (CEMU)
            elif "Cemu" in emu_display_name or platform == "wiiu":
                mlc_path = emu_dir / "mlc01"
                if not mlc_path.exists():
                    settings_xml = emu_dir / "settings.xml"
                    if settings_xml.exists():
                        try:
                            import xml.etree.ElementTree as ET
                            mlc_node = ET.parse(settings_xml).getroot().find('.//mlc_path')
                            if mlc_node is not None and mlc_node.text: mlc_path = Path(mlc_node.text)
                        except Exception: pass
                if not mlc_path or not mlc_path.exists(): mlc_path = Path(os.path.expandvars(r'%APPDATA%\Cemu\mlc01'))
                
                save_base = mlc_path / "usr/save/00050000"
                if save_base.exists():
                    title_dirs = sorted([d for d in save_base.iterdir() if d.is_dir()], key=lambda x: x.stat().st_mtime, reverse=True)
                    for title_dir in title_dirs:
                        candidate = title_dir / "user" / "80000001"
                        if candidate.exists() and any(candidate.iterdir()): return candidate
                    for title_dir in title_dirs:
                        if (title_dir / "user").exists(): return title_dir / "user" / "80000001"
                return None

            # 6. NINTENDO 3DS (CITRA)
            elif any(x in emu_display_name for x in ["Citra", "Azahar", "3DS"]) or platform in ["3ds", "n3ds"]:
                citra_base = Path(os.path.expandvars(r'%APPDATA%\Citra\sdmc\Nintendo 3DS'))
                if citra_base.exists():
                    best, max_mt = None, 0
                    for id1 in citra_base.iterdir():
                        for id2 in id1.iterdir():
                            title_base = id2 / "title/00040000"
                            if not title_base.exists(): continue
                            for tid in title_base.iterdir():
                                candidate = tid / "data/00000001"
                                if candidate.exists() and candidate.stat().st_mtime > max_mt:
                                    max_mt, best = candidate.stat().st_mtime, candidate
                    if best: return best
                return Path(os.path.expandvars(r'%APPDATA%\Citra\sdmc'))

            # 4. RETROARCH
            elif "RetroArch" in emu_display_name or platform == "multi" or platform in RETROARCH_PLATFORMS:
                game_item = next((g for g in self.client.user_games if g['name'] == title), None)
                if not game_item: game_item = {"id": title, "name": title, "platform_slug": platform, "fs_name": title + ".rom"}
                path, is_f = self.get_retroarch_save_path(game_item, {"path": emu_path})
                if path: return Path(path)
        except Exception as e:
            self.log_signal.emit(f"⚠️ Error resolving save path: {e}")
        return None

    def get_retroarch_save_path(self, game, emu_data):
        from src.platforms import RETROARCH_CORES, RETROARCH_CORE_SAVE_FOLDERS, RETROARCH_FOLDER_SAVE_CORES
        ra_exe = emu_data.get("path", "")
        if not ra_exe: return None, False
        
        saves_dir = Path(ra_exe).parent / "saves"
        core_dll = RETROARCH_CORES.get(game.get("platform_slug", ""))
        if not core_dll: return None, False
        
        core_name = core_dll.replace(".dll", "").replace(".so", "").replace("_libretro", "")
        save_folder_name = RETROARCH_CORE_SAVE_FOLDERS.get(core_name, core_name)
        core_saves = saves_dir / save_folder_name
        if not core_saves.exists(): core_saves = saves_dir
        
        rom_name = game.get("fs_name", game.get("name", ""))
        base_name = Path(rom_name).stem
        
        # Standard — point to the ACTUAL .srm path
        if core_name == "ppsspp":
            psp_savedata = saves_dir / "PPSSPP" / "PSP" / "SAVEDATA"
            return str(psp_savedata), True
            
        return str(core_saves / f"{base_name}.srm"), False

    def handle_exit(self, data):
        try:
            self.log_signal.emit(f"🛑 Session Ended: {data['title']}")
            save_path = Path(data['save_path'])
            
            is_retroarch = data.get('emu') == "Multi-Console (RetroArch)"
            if not save_path.exists() and not is_retroarch:
                self.log_signal.emit(f"⚠️ Save file missing on exit: {save_path}. Skipping sync.")
                return
            
            # Capture hash IMMEDIATELY at process exit
            if is_retroarch:
                h_at_exit = self._hash_retroarch_game(str(save_path), data['is_folder'])
            else:
                h_at_exit = calculate_folder_hash(str(save_path)) if data['is_folder'] else calculate_file_hash(str(save_path))
            
            # Give emulator a moment to finish writing buffered files to disk
            time.sleep(3)
            
            if is_retroarch:
                new_h = self._hash_retroarch_game(str(save_path), data['is_folder'])
            else:
                new_h = calculate_folder_hash(str(save_path)) if data['is_folder'] else calculate_file_hash(str(save_path))
            
            initial_h = data.get('initial_hash')
            
            post_mtime = self._get_folder_mtime(str(save_path))
            initial_mtime = data.get('initial_mtime', 0)
            mtime_changed = post_mtime > initial_mtime
            
            # Change detected if final hash differs from initial (during play) 
            # OR final hash differs from at_exit (post-exit flush)
            has_hash_changed = (new_h != initial_h or (h_at_exit is not None and new_h != h_at_exit))

            print(f"[DEBUG] {data['title']} exit: is_folder={data['is_folder']} save_path={save_path} exists={os.path.exists(save_path)} mtime_changed={mtime_changed} hash_changed={has_hash_changed}")

            if not has_hash_changed and not mtime_changed:
                self.log_signal.emit(f"⏭️ No changes in {data['title']}. Skipping sync.")
                return

            self.log_signal.emit(f"📝 Changes detected! Syncing...")
            temp_zip = str(self.tmp_dir / f"sync_{data['rom_id']}.zip")
            try:
                # For RetroArch, we need to zip ALL matching files (SRM + States) or the whole folder
                if is_retroarch:
                    if data['is_folder']:
                        zip_path(str(save_path), temp_zip)
                    else:
                        srm = Path(data['save_path'])
                        core_dir = srm.parent
                        stem = srm.stem
                        with zipfile.ZipFile(temp_zip, 'w', zipfile.ZIP_DEFLATED) as zf:
                            if srm.exists(): zf.write(srm, srm.name)
                            for f in core_dir.glob(f"{stem}.state*"):
                                zf.write(f, f.name)
                else:
                    zip_path(str(save_path), temp_zip)
                
                success, msg = self.client.upload_save(data['rom_id'], data['emu'], temp_zip)
                if success:
                    self.log_signal.emit("✨ Sync Complete!")
                    if str(data['rom_id']) in self.sync_cache:
                        del self.sync_cache[str(data['rom_id'])]
                        self.save_cache()
                else: self.log_signal.emit(f"❌ Sync Failed: {msg}")
            finally:
                if os.path.exists(temp_zip):
                    try: os.remove(temp_zip)
                    except: pass
            
            # Playtime tracking
            try:
                session_minutes = (time.time() - data['start_time']) / 60
                playtime_path = Path.home() / ".wingosy" / "playtime.json"
                playtime_data = {}
                if playtime_path.exists():
                    try:
                        with open(playtime_path, 'r') as f: playtime_data = json.load(f)
                    except: pass
                rid_str = str(data['rom_id'])
                new_total = playtime_data.get(rid_str, 0) + session_minutes
                playtime_data[rid_str] = new_total
                with open(playtime_path, 'w') as f: json.dump(playtime_data, f)
                self.log_signal.emit(f"🕐 Session: {session_minutes:.1f} min | Total: {new_total:.1f} min")
            except Exception as e: print(f"[Watcher] Playtime error: {e}")
        except Exception as e: self.log_signal.emit(f"❌ Error during sync: {e}")

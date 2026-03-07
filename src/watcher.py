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

    def __init__(self, client, config):
        super().__init__()
        self.client = client
        self.config = config
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

    def _hash_retroarch_game(self, srm_path, state_path=None, is_folder=False):
        """
        Hash the SRM + state file independently for change detection.
        For folder-based cores (PSP), hashes the entire folder tree.
        """
        if is_folder:
            from src.utils import calculate_folder_hash
            try:
                return calculate_folder_hash(str(srm_path))
            except Exception:
                return None
        
        h = hashlib.md5()
        found = False
        for p in [srm_path, state_path]:
            if p and Path(p).exists():
                found = True
                with open(p, 'rb') as f:
                    h.update(f.read())
        return h.hexdigest() if found else None

    def _get_folder_mtime(self, path):
        """Return the newest mtime of any file in a folder tree."""
        if not path or not os.path.exists(path):
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

    def _safe_folder_hash(self, folder_path, retries=3, delay=3):
        from src.utils import calculate_folder_hash
        for i in range(retries):
            try:
                if not os.path.exists(folder_path):
                    return None
                return calculate_folder_hash(str(folder_path))
            except (PermissionError, OSError) as e:
                if i < retries - 1:
                    time.sleep(delay)
                else:
                    print(f"[Watcher] Could not hash folder after {retries} attempts: {e}")
                    return None

    def track_session(self, proc, emu_display_name, game_data, local_rom_path, emu_path, skip_pull=False):
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
            res = self.resolve_save_path(emu_display_name, title, full_cmd, emu_path, platform, proc=psutil.Process(pid))
            
            if res:
                save_path, is_folder = res
                save_path = str(Path(save_path).resolve())
                
                # Double-Pull Protection
                should_pull = (self.config.get("auto_pull_saves", True) and not skip_pull)
                if self.skip_next_pull_rom_id == str(rom_id):
                    should_pull = False
                    self.skip_next_pull_rom_id = None

                # Special marker for Dolphin GC card sync
                is_gc_card = (is_folder == "gc_card")
                gc_card_dir = save_path if is_gc_card else None
                
                if is_gc_card:
                    is_folder = False # We upload a zip of files later

                # Tracking both mode for RetroArch
                is_retroarch_game = ("RetroArch" in emu_display_name or platform == "multi" or platform in RETROARCH_PLATFORMS)
                self._pull_is_retroarch = is_retroarch_game

                if emu_display_name == "Multi-Console (RetroArch)":
                    ra_emu_data = {"path": emu_path}
                    save_info = self.get_retroarch_save_path(
                        game_data, ra_emu_data)
                    if save_info is None:
                        self.log_signal.emit(
                            f"⚠️ Could not resolve RetroArch paths for {title}")
                        return
                    save_path   = save_info.get('srm') or ""
                    state_path  = save_info.get('state') or ""
                    is_folder   = False
                    if should_pull:
                        self.pull_server_save(
                            rom_id, title, save_info, is_folder, force=False)
                else:
                    if should_pull:
                        self.pull_server_save(
                            rom_id, title, save_path, is_folder, force=False)
                
                self._pull_is_retroarch = False

                # Resolve paths again if both mode might have returned multiple
                game_item = next((g for g in self.client.user_games if g['name'] == title), None)
                if not game_item: game_item = {"id": rom_id, "name": title, "platform_slug": platform, "fs_name": Path(local_rom_path).name}
                
                both_mode = False
                state_save_path = None
                psp_folder = None
                
                if is_retroarch_game:
                    ra_res = self.get_retroarch_save_path(game_item, {"path": emu_path})
                    if isinstance(ra_res, dict):
                        save_path = str(Path(ra_res['srm']).resolve())
                        state_save_path = str(Path(ra_res['state']).resolve()) if ra_res.get('state') else None
                        both_mode = (self.config.get("retroarch_save_mode") == "both")
                        is_folder = ra_res.get('is_folder', False)
                        psp_folder = ra_res.get('psp_folder')
                
                # Track the session with initial state
                if is_gc_card:
                    h = None
                    init_mtime = time.time() # Key timestamp for GCI detection
                elif psp_folder:
                    # For PSP, defer hashing to avoid permission/non-existence issues at start
                    h = self._safe_folder_hash(psp_folder) if os.path.exists(psp_folder) else None
                    init_mtime = self._get_folder_mtime(psp_folder) if os.path.exists(psp_folder) else time.time()
                    initial_state_mtime = os.path.getmtime(state_path) if state_path and os.path.exists(state_path) else 0
                elif is_retroarch_game:
                    h = self._hash_retroarch_game(save_path, state_save_path, is_folder)
                    init_mtime = max(self._get_folder_mtime(save_path), self._get_folder_mtime(state_save_path))
                else:
                    h = (calculate_folder_hash(save_path) if is_folder 
                          else calculate_file_hash(save_path) 
                          if os.path.exists(save_path) else None)
                    init_mtime = self._get_folder_mtime(save_path)

                srm_p = save_path if str(save_path).endswith('.srm') else (state_save_path if state_save_path and str(state_save_path).endswith('.srm') else None)
                state_p = state_save_path if state_save_path and '.state' in str(state_save_path) else (save_path if '.state' in str(save_path) else None)

                session_data = {
                    'emu': emu_display_name, 
                    'rom_id': rom_id, 
                    'save_path': save_path,
                    'title': title,
                    'initial_hash': h,
                    'initial_mtime': init_mtime,
                    'is_folder': is_folder,
                    'start_time': time.time(),
                    'emu_path': emu_path,
                    'gc_card_dir': gc_card_dir,
                    'both_mode': both_mode,
                    'state_save_path': state_save_path,
                    'srm_path': srm_p,
                    'state_path': state_p,
                    'psp_folder': psp_folder
                }
                self.active_sessions[pid] = session_data
                self.log_signal.emit(f"🎮 Tracking {title} on {emu_display_name} (PID: {pid})")
            else:
                self.log_signal.emit(f"⚠️ Identified {title} but could not resolve local save path.")
                
        except Exception as e:
            self.log_signal.emit(f"❌ Error setting up tracking: {e}")

    def _clean_romm_filename(self, filename: str) -> str:
        """
        Strip RomM's auto-appended timestamp bracket from filename.
        e.g. "Super Punch-Out!! (USA) [2026-03-07 08-45-26-649].state"
             -> "Super Punch-Out!! (USA).state"
        """
        import re
        # Correct regex: Match " [date-like content]" before extension
        cleaned = re.sub(r'\s*\[\d{4}-\d{2}-\d{2}[^\]]+\]', '', filename)
        return cleaned

    def pull_server_save(self, rom_id, title, save_info_or_path,
                         is_folder, force=False):
        
        is_ra_dict = isinstance(save_info_or_path, dict)
        if is_ra_dict:
            srm_path   = save_info_or_path.get('srm')
            state_path = save_info_or_path.get('state')
        else:
            srm_path   = save_info_or_path
            state_path = None

        self.log_signal.emit(f"☁️ Checking cloud for {title}...")

        # Pull SRM / regular save
        latest_save = self.client.get_latest_save(rom_id)
        if latest_save:
            self._apply_cloud_file(
                rom_id, title, latest_save, srm_path,
                is_folder, force, file_type="save"
            )

        # Pull State (RetroArch only)
        if state_path:
            latest_state = self.client.get_latest_state(rom_id)
            if latest_state:
                self._apply_cloud_file(
                    rom_id, title, latest_state, state_path,
                    False, force, file_type="state"
                )

    def _apply_cloud_file(self, rom_id, title, cloud_obj, local_path, is_folder, force, file_type="save"):
        server_updated_at = cloud_obj.get('updated_at', '')
        
        # Determine cached updated_at using new dictionary-based rom_id keys
        cached_val = self.sync_cache.get(str(rom_id), {})
        if isinstance(cached_val, dict):
            cached_updated_at = cached_val.get(f'{file_type}_updated_at', '')
        else:
            # Fallback for old cache format
            cached_updated_at = cached_val if file_type == 'save' else ''

        local_exists = os.path.exists(local_path)

        # Only skip if timestamp matches AND the local file actually exists
        if not force and cached_updated_at == server_updated_at and local_exists:
            self.log_signal.emit(f"☁️ {'SAVE' if file_type=='save' else 'STATE'} already up to date.")
            return

        temp_dl = str(self.tmp_dir / f"cloud_check_{rom_id}_{file_type}")
        
        success = False
        if file_type == "state":
            success = self.client.download_state(cloud_obj, temp_dl)
        else:
            success = self.client.download_save(cloud_obj, temp_dl)

        if success:
            orig_filename = cloud_obj.get('file_name', '') or cloud_obj.get('name', '')
            filename = self._clean_romm_filename(orig_filename)
            
            print(f"[Pull] {file_type} filename before clean={orig_filename}")
            print(f"[Pull] {file_type} filename after clean={filename}")
            
            is_raw_retroarch = filename.lower().endswith(('.srm', '.state'))
            is_zip = zipfile.is_zipfile(temp_dl) if not is_raw_retroarch else False
                
            # Note: Combined key conflict check removed; blocking pull in UI now handles it
            
            self.log_signal.emit(f"📥 Cloud {file_type} is different. Updating...")
            os.makedirs(os.path.dirname(local_path), exist_ok=True)

            # Backup
            if os.path.exists(local_path):
                bak_path = str(local_path) + ".bak"
                try:
                    if is_folder: shutil.copytree(local_path, bak_path)
                    else: shutil.copy2(local_path, bak_path)
                except Exception: pass

            try:
                if is_zip:
                    if is_folder:
                        extract_parent = str(Path(local_path).parent)
                        folder_name = Path(local_path).name
                        if os.path.exists(local_path): shutil.rmtree(local_path, ignore_errors=True)
                        os.makedirs(extract_parent, exist_ok=True)
                        with zipfile.ZipFile(temp_dl, 'r') as z:
                            names = z.namelist()
                            has_root = any(n.startswith(folder_name + '/') or n.startswith(folder_name + '\\') for n in names)
                            if has_root: z.extractall(extract_parent)
                            else: os.makedirs(local_path, exist_ok=True); z.extractall(local_path)
                    else:
                        with zipfile.ZipFile(temp_dl, 'r') as z:
                            names = z.namelist()
                            is_gc_bundle = any(n.endswith('.gci') for n in names)
                            if is_gc_bundle and os.path.isdir(local_path): z.extractall(local_path)
                            else:
                                target_member = next((n for n in names if n.endswith(('.ps2', '.srm', '.sav', '.dat', '.sv', '.raw', '.gci', '.state'))), names[0] if names else None)
                                if target_member:
                                    with z.open(target_member) as source, open(local_path, 'wb') as target: shutil.copyfileobj(source, target)
                elif is_raw_retroarch:
                    dest = Path(local_path)
                    if dest.is_dir(): dest = dest / filename
                    shutil.copy2(temp_dl, str(dest))
                    
                    final_path = dest
                    if (dest.suffix == '.state' and not dest.name.endswith('.state.auto')):
                        auto_path = dest.with_name(dest.name + '.auto')
                        try:
                            if auto_path.exists():
                                if auto_path.is_dir(): shutil.rmtree(auto_path)
                                else: os.remove(auto_path)
                            dest.rename(auto_path)
                            print(f"[Pull] Renamed state -> {auto_path.name}")
                            final_path = auto_path
                        except Exception as e: print(f"[Pull] Failed to rename state: {e}")
                    
                    if file_type == "state":
                        # Add delay for RetroArch
                        import time
                        time.sleep(0.5)
                        print(f"[Pull] State file ready at: {final_path}")
                else:
                    dest = Path(local_path)
                    if dest.is_dir():
                        dest = dest / filename
                        shutil.copy2(temp_dl, str(dest))
                    else:
                        if os.path.isdir(local_path): shutil.rmtree(local_path, ignore_errors=True)
                        shutil.copy2(temp_dl, local_path)
                
                # Update cache using new dictionary structure
                current_entry = self.sync_cache.get(str(rom_id))
                if not isinstance(current_entry, dict):
                    current_entry = {}
                current_entry[f'{file_type}_updated_at'] = server_updated_at
                self.sync_cache[str(rom_id)] = current_entry
                self.save_cache()
                self.log_signal.emit(f"✨ Cloud {file_type} applied!")
            except Exception as e: self.log_signal.emit(f"❌ Failed to apply {file_type}: {e}")
            if os.path.exists(temp_dl): os.remove(temp_dl)

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
                            if candidate.exists(): return str(candidate), True
                        profiles = [d for d in save_base.iterdir() if d.is_dir()]
                        if profiles: return str(profiles[0] / title_id), True
                return None

            # 2. GAMECUBE / WII / NGC (DOLPHIN)
            elif "Dolphin" in emu_display_name or platform in [
                    "gc", "ngc", "wii", "gamecube", "nintendo-gamecube",
                    "nintendo-wii", "wii-u-vc"]:

                emu_dir = Path(emu_path).parent

                # Detect portable vs appdata mode
                portable_gc = emu_dir / "User" / "GC"
                documents_gc = (Path.home() / "Documents" 
                                / "Dolphin Emulator" / "GC")
                gc_base = (portable_gc if portable_gc.exists() 
                           else documents_gc)

                # Detect region from ROM name
                rom_upper = full_cmd.upper()
                if any(r in rom_upper for r in ["EUR", "PAL", "EUROPE"]):
                    region = "EUR"
                elif any(r in rom_upper for r in ["JAP", "JPN", "JAPAN"]):
                    region = "JAP"
                else:
                    region = "USA"

                card_dir = gc_base / region / "Card A"
                print(f"[Dolphin] Card dir: {card_dir} (exists={card_dir.exists()})")
                
                # Use special marker for mtime-based detection
                return str(card_dir), "gc_card"

            # 3. PLAYSTATION 2
            elif "PlayStation 2" in emu_display_name or platform == "ps2":
                search_paths = [emu_dir / "memcards" / "Mcd001.ps2", Path(os.path.expandvars(r'%APPDATA%\PCSX2\memcards\Mcd001.ps2')), Path.home() / "Documents" / "PCSX2" / "memcards" / "Mcd001.ps2"]
                for p in search_paths:
                    if p.exists(): return str(p), False
                return str(search_paths[0]), False

            # 3.5 PLAYSTATION 3 (RPCS3)
            elif "PlayStation 3" in emu_display_name or platform == "ps3":
                save_base = emu_dir / "dev_hdd0/home/00000001/savedata"
                if not save_base.exists():
                    save_base = Path(os.path.expandvars(r'%APPDATA%\RPCS3\dev_hdd0\home\00000001\savedata'))
                
                if save_base.exists():
                    tid_match = re.search(r'([A-Z]{4}\d{5})', full_cmd)
                    if tid_match: return str(save_base / tid_match.group(1).upper()), True
                    subdirs = sorted([d for d in save_base.iterdir() if d.is_dir() and (d / "PARAM.SFO").exists()], key=lambda x: x.stat().st_mtime, reverse=True)
                    if subdirs: return str(subdirs[0]), True
                return str(save_base), True

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
                        if candidate.exists() and any(candidate.iterdir()): return str(candidate), True
                    for title_dir in title_dirs:
                        if (title_dir / "user").exists(): return str(title_dir / "user" / "80000001"), True
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
                    if best: return str(best), True
                return str(Path(os.path.expandvars(r'%APPDATA%\Citra\sdmc'))), True

            # 4. RETROARCH
            elif "RetroArch" in emu_display_name or platform == "multi" or platform in RETROARCH_PLATFORMS:
                game_item = next((g for g in self.client.user_games if g['name'] == title), None)
                if not game_item: game_item = {"id": title, "name": title, "platform_slug": platform, "fs_name": title + ".rom"}
                
                res = self.get_retroarch_save_path(game_item, {"path": emu_path})
                if res['is_folder']:
                    return res['srm'], True
                
                save_mode = self.config.get("retroarch_save_mode", "srm")
                path = res['state'] if save_mode == "state" else res['srm']
                return path, False
        except Exception as e:
            self.log_signal.emit(f"⚠️ Error resolving save path: {e}")
        return None

    def get_retroarch_save_path(self, game, emu_data):
        """
        Returns a dict containing paths for the RetroArch save to sync.
        {
            "srm": str,
            "state": str,
            "is_folder": bool,
            "psp_folder": str or None
        }
        """
        from src.platforms import RETROARCH_CORES, RETROARCH_CORE_SAVE_FOLDERS
        ra_exe = emu_data.get("path", "")
        if not ra_exe:
            return None

        ra_dir = Path(ra_exe).parent
        platform_slug = game.get("platform_slug", "")

        # PSP: always folder-based SAVEDATA
        if platform_slug in ("psp", "playstation-portable"):
            psp_saves = ra_dir / "saves" / "PPSSPP" / "PSP" / "SAVEDATA"
            rom_name = game.get("fs_name", game.get("name", ""))
            base_name = Path(rom_name).stem
            state_path = ra_dir / "states" / "PPSSPP" / f"{base_name}.state.auto"
            return {
                "srm": str(psp_saves),
                "state": str(state_path),
                "is_folder": True,
                "psp_folder": str(psp_saves)
            }

        core_dll = RETROARCH_CORES.get(platform_slug, "")
        if not core_dll:
            return None

        core_name = (core_dll.replace(".dll", "").replace(".so", "")
                              .replace("_libretro", ""))
        save_folder_name = RETROARCH_CORE_SAVE_FOLDERS.get(core_name, core_name)

        rom_name = game.get("fs_name", game.get("name", ""))
        base_name = Path(rom_name).stem

        srm_path = ra_dir / "saves" / save_folder_name / f"{base_name}.srm"
        state_path = ra_dir / "states" / save_folder_name / f"{base_name}.state.auto"

        return {
            "srm": str(srm_path),
            "state": str(state_path),
            "is_folder": False,
            "psp_folder": None
        }

    def handle_exit(self, data):
        try:
            self.log_signal.emit(f"🛑 Session Ended: {data['title']}")
            
            # Special case for Dolphin GC card sync (mtime-based GCI detection)
            gc_card_dir = data.get('gc_card_dir')
            if gc_card_dir:
                session_start = data.get('initial_mtime', 0)
                card_path = Path(gc_card_dir)
                
                # Find .gci files modified AFTER session started
                changed_gcis = []
                if card_path.exists():
                    for gci in card_path.glob("*.gci"):
                        try:
                            if gci.stat().st_mtime > session_start:
                                changed_gcis.append(gci)
                        except Exception:
                            pass
                
                print(f"[Dolphin] Session start: {session_start}")
                print(f"[Dolphin] Changed GCIs: {[f.name for f in changed_gcis]}")
                
                if changed_gcis:
                    self.log_signal.emit(f"📝 {len(changed_gcis)} GCI file(s) changed. Syncing...")
                    temp_zip = str(self.tmp_dir / f"sync_{data['rom_id']}.zip")
                    try:
                        with zipfile.ZipFile(temp_zip, 'w', zipfile.ZIP_DEFLATED) as zf:
                            for gci in changed_gcis:
                                zf.write(str(gci), gci.name)
                        success, msg = self.client.upload_save(data['rom_id'], data['emu'], temp_zip)
                        if success:
                            self.log_signal.emit("✨ Sync Complete!")
                            # Clear cache entry to force re-pull on next launch
                            self.sync_cache.pop(str(data['rom_id']), None)
                            self.save_cache()
                        else:
                            self.log_signal.emit(f"❌ Sync Failed: {msg}")
                    finally:
                        if os.path.exists(temp_zip):
                            try: os.remove(temp_zip)
                            except: pass
                else:
                    self.log_signal.emit(f"⏭️ No changes in {data['title']}. Skipping sync.")
                
                self._update_playtime(data)
                return

            save_path = Path(data['save_path'])
            is_retroarch = data.get('emu') == "Multi-Console (RetroArch)"
            both_mode = data.get('both_mode', False)
            state_save_path = data.get('state_save_path')
            psp_folder = data.get('psp_folder')
            
            if not save_path.exists() and not is_retroarch:
                self.log_signal.emit(f"⚠️ Save file missing on exit: {save_path}. Skipping sync.")
                return
            
            # Capture hash IMMEDIATELY at process exit
            if is_retroarch and data.get('is_folder'):
                h_at_exit = self._safe_folder_hash(data['save_path'])
            elif is_retroarch:
                h_at_exit = self._hash_retroarch_game(str(save_path), data['is_folder'])
            else:
                h_at_exit = calculate_folder_hash(str(save_path)) if data['is_folder'] else calculate_file_hash(str(save_path))
            
            # Give emulator a moment to finish writing buffered files to disk
            time.sleep(3)
            
            if is_retroarch and data.get('is_folder'):
                new_h = self._safe_folder_hash(data['save_path'])
            elif is_retroarch:
                new_h = self._hash_retroarch_game(str(save_path), data['is_folder'])
            else:
                new_h = calculate_folder_hash(str(save_path)) if data['is_folder'] else calculate_file_hash(str(save_path))
            
            initial_h = data.get('initial_hash')
            
            post_mtime = self._get_folder_mtime(str(save_path))
            initial_mtime = data.get('initial_mtime', 0)
            mtime_changed = post_mtime > initial_mtime
            
            # Change detected if final hash differs from initial (during play) 
            # OR final hash differs from at_exit (post-exit flush)
            # OR if we had no initial hash (lazy creation) and now have data
            has_hash_changed = (new_h != initial_h or (h_at_exit is not None and new_h != h_at_exit))
            if initial_h is None and new_h is not None:
                has_hash_changed = True

            psp_folder = data.get('psp_folder')
            state_p = data.get('state_path')
            
            # For PSP: also check if state file changed
            state_mtime_changed = False
            if psp_folder and state_p and os.path.exists(state_p):
                current_state_mtime = os.path.getmtime(state_p)
                state_mtime_changed = (
                    current_state_mtime > data.get('initial_state_mtime', 0))

            if not has_hash_changed and not mtime_changed and not state_mtime_changed:
                self.log_signal.emit(f"⏭️ No changes in {data['title']}. Skipping sync.")
                return
            
            # If ONLY state changed (SAVEDATA unchanged), skip SAVEDATA upload
            savedata_changed = mtime_changed or has_hash_changed

            self.log_signal.emit(f"📝 Changes detected! Syncing...")
            
            if is_retroarch and psp_folder:
                # === PSP Folder Mode: Upload SAVEDATA zip + State file ===
                rom_id = data['rom_id']
                emu = data['emu']
                
                # 1. Upload SAVEDATA Zip
                if savedata_changed:
                    temp_zip = str(self.tmp_dir / f"sync_{rom_id}.zip")
                    try:
                        zip_path(str(psp_folder), temp_zip)
                        success, msg = self.client.upload_save(rom_id, emu, temp_zip, slot="wingosy-srm")
                        if success:
                            self.log_signal.emit("✨ SAVEDATA synced!")
                            entry = self.sync_cache.get(str(rom_id))
                            if isinstance(entry, dict): entry.pop('save_updated_at', None)
                        else: self.log_signal.emit(f"❌ SAVEDATA sync failed: {msg}")
                    finally:
                        if os.path.exists(temp_zip): os.remove(temp_zip)

                # 2. Upload State File if it changed
                if state_p and os.path.exists(state_p) and state_mtime_changed:
                    ok, msg = self.client.upload_state(rom_id, emu, str(state_p), slot="wingosy-state")
                    if ok:
                        self.log_signal.emit("✨ State synced!")
                        entry = self.sync_cache.get(str(rom_id))
                        if isinstance(entry, dict): entry.pop('state_updated_at', None)
                    else: self.log_signal.emit(f"❌ State sync failed: {msg}")
                
                self.save_cache()

            elif is_retroarch and not data['is_folder']:
                # === RetroArch Raw Mode: Upload files directly ===
                rom_id = data['rom_id']
                emu = data['emu']
                srm_p = data.get('srm_path')
                state_p = data.get('state_path')

                # Upload SRM
                if srm_p and Path(srm_p).exists():
                    ok, msg = self.client.upload_save(rom_id, emu, str(srm_p), slot="wingosy-srm", raw=True)
                    if ok: 
                        self.log_signal.emit("✨ SRM synced!")
                        # Remove specific field from new cache format
                        entry = self.sync_cache.get(str(rom_id))
                        if isinstance(entry, dict):
                            entry.pop('save_updated_at', None)
                        else:
                            self.sync_cache.pop(f"{rom_id}:save", None) # Legacy
                    else: self.log_signal.emit(f"❌ SRM sync failed: {msg}")

                # Upload State
                if state_p and Path(state_p).exists():
                    ok, msg = self.client.upload_state(rom_id, emu, str(state_p), slot="wingosy-state")
                    if ok: 
                        self.log_signal.emit("✨ State synced!")
                        # Remove specific field from new cache format
                        entry = self.sync_cache.get(str(rom_id))
                        if isinstance(entry, dict):
                            entry.pop('state_updated_at', None)
                        else:
                            self.sync_cache.pop(f"{rom_id}:state", None) # Legacy
                    else: self.log_signal.emit(f"❌ State sync failed: {msg}")
                
                self.save_cache()
            else:
                # === Standard Zip Mode (Non-RetroArch or PSP) ===
                save_mode = self.config.get("retroarch_save_mode", "srm")
                slot = "wingosy-state" if (is_retroarch and save_mode == "state") else "wingosy-srm" if is_retroarch else "wingosy-windows"

                temp_zip = str(self.tmp_dir / f"sync_{data['rom_id']}.zip")
                try:
                    # For RetroArch (PSP case), we need to zip the whole folder
                    zip_path(str(save_path), temp_zip)
                    
                    success, msg = self.client.upload_save(data['rom_id'], data['emu'], temp_zip, slot=slot)
                    if success:
                        self.log_signal.emit("✨ Sync Complete!")
                        self.sync_cache.pop(str(data['rom_id']), None)
                        self.save_cache()
                    else: self.log_signal.emit(f"❌ Sync Failed: {msg}")
                finally:
                    if os.path.exists(temp_zip):
                        try: os.remove(temp_zip)
                        except: pass
            
            # Playtime tracking
            self._update_playtime(data)
        except Exception as e: self.log_signal.emit(f"❌ Error during sync: {e}")

    def _update_playtime(self, data):
        """Update session and total playtime."""
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

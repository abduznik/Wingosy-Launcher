import time
import psutil
import os
import re
import shutil
import zipfile
import json
from pathlib import Path
from PySide6.QtCore import QThread, Signal
from src.utils import calculate_folder_hash, calculate_file_hash, calculate_zip_content_hash, zip_path

class WingosyWatcher(QThread):
    log_signal = Signal(str)
    path_detected_signal = Signal(str, str) # emu_display_name, path

    def __init__(self, client, config_manager):
        super().__init__()
        self.client = client
        self.config = config_manager
        self.running = True
        self.active_sessions = {}
        self.skip_next_pull_rom_id = None # Flag to prevent double-pull when launching from app
        
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

    def track_session(self, proc, emu_display_name, game_data, local_rom_path, emu_path):
        """
        Explicitly track a process launched by the UI.
        """
        try:
            pid = proc.pid
            full_cmd = f"\"{emu_path}\" \"{local_rom_path}\"".lower()
            rom_id = game_data['id']
            title = game_data['name']
            platform = game_data.get('platform_slug')

            # 1. Resolve Save Path
            save_path = self.resolve_save_path(emu_display_name, title, full_cmd, emu_path, platform, proc=psutil.Process(pid))
            
            if not save_path:
                # Retry once after a short delay in case files aren't open yet
                time.sleep(2)
                save_path = self.resolve_save_path(emu_display_name, title, full_cmd, emu_path, platform, proc=psutil.Process(pid))

            if save_path:
                save_path = str(Path(save_path).resolve())
                is_folder = platform in ["switch", "ps3", "wii"]
                if os.path.exists(save_path):
                    is_folder = os.path.isdir(save_path)
                
                # Double-Pull Protection (already handled by Play button usually, but safe to keep)
                should_pull = self.config.get("auto_pull_saves", True)
                if self.skip_next_pull_rom_id == str(rom_id):
                    should_pull = False
                    self.skip_next_pull_rom_id = None

                if should_pull:
                    self.pull_server_save(rom_id, title, save_path, is_folder)
                
                # Track the session with hash BEFORE playing
                h = None
                if os.path.exists(save_path):
                    try: h = calculate_folder_hash(save_path) if is_folder else calculate_file_hash(save_path)
                    except Exception: pass

                self.active_sessions[pid] = {
                    'emu': emu_display_name, 
                    'rom_id': rom_id, 
                    'save_path': save_path,
                    'title': title,
                    'initial_hash': h,
                    'is_folder': is_folder
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

        save_id = str(latest_save['id'])
        if not force and self.sync_cache.get(str(rom_id)) == save_id:
            self.log_signal.emit(f"☁️ Cloud save ({save_id}) already applied.")
            return

        temp_dl = "cloud_check_file"
        if self.client.download_save(latest_save, temp_dl):
            is_zip = zipfile.is_zipfile(temp_dl)
            if is_zip:
                server_hash = calculate_zip_content_hash(temp_dl)
            else:
                server_hash = calculate_file_hash(temp_dl)
                
            local_hash = None
            if os.path.exists(local_path):
                local_hash = calculate_folder_hash(local_path) if is_folder else calculate_file_hash(local_path)

            if not force and local_hash and server_hash == local_hash:
                self.log_signal.emit("☁️ Local save identical to cloud.")
                self.sync_cache[str(rom_id)] = save_id
                self.save_cache()
                os.remove(temp_dl)
                return

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
                        with zipfile.ZipFile(temp_dl, 'r') as z:
                            z.extractall(Path(local_path).parent)
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
                    shutil.copy2(temp_dl, local_path)
                
                self.sync_cache[str(rom_id)] = save_id
                self.save_cache()
                self.log_signal.emit("✨ Cloud save applied!")
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
                
                # Extract ROM path from command line
                m_path = re.search(r'("[^"]+\.(?:xci|nsp|nsz)")', full_cmd)
                if not m_path: m_path = re.search(r'(\S+\.(?:xci|nsp|nsz))', full_cmd)
                if m_path:
                    rom_path = Path(m_path.group(1).strip('"'))

                search_roots = [
                    emu_dir / "user", 
                    emu_dir / "data", 
                    Path(os.path.expandvars(r'%APPDATA%\eden')), 
                    Path(os.path.expandvars(r'%APPDATA%\yuzu')), 
                    Path(os.path.expandvars(r'%APPDATA%\sudachi')),
                    Path(os.path.expandvars(r'%APPDATA%\torzu')),
                    Path(os.path.expandvars(r'%LOCALAPPDATA%\yuzu'))
                ]

                # Prioritize roots matching current emulator name
                emu_lower = emu_display_name.lower()
                prioritized = []
                for root in search_roots:
                    # Check if emulator name (e.g., "eden", "yuzu") is in the path
                    if any(k in root.as_posix().lower() for k in ["eden", "yuzu", "sudachi", "torzu"]) and \
                       any(k in emu_lower for k in ["eden", "yuzu", "sudachi", "torzu"]):
                        # Try to match specifically (e.g. eden root for eden emu)
                        for k in ["eden", "yuzu", "sudachi", "torzu"]:
                            if k in root.as_posix().lower() and k in emu_lower:
                                prioritized.append(root)
                                break
                
                search_roots = prioritized + [r for r in search_roots if r not in prioritized]

                # --- Method 1: SQLite Game List Cache ---
                if not title_id:
                    for root in search_roots:
                        db_path = root / "cache/game_list/game_list.db"
                        if db_path.exists():
                            try:
                                conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
                                cursor = conn.cursor()
                                query = "SELECT title_id FROM game_list WHERE name LIKE ? LIMIT 1"
                                cursor.execute(query, (f"%{title}%",))
                                row = cursor.fetchone()
                                if row:
                                    title_id = row[0].upper()
                                    if not title_id.startswith("01"): title_id = f"01{title_id}"
                                    self.log_signal.emit(f"🔍 [Switch] Found Title ID in emulator cache: {title_id}")
                                conn.close()
                                if title_id: break
                            except Exception: pass

                # --- Method 2: XCI Header Extraction ---
                if not title_id and rom_path and rom_path.exists() and rom_path.suffix.lower() == ".xci":
                    try:
                        with open(rom_path, "rb") as f:
                            f.seek(0x108)
                            tid_bytes = f.read(8)
                            title_id = tid_bytes[::-1].hex().upper()
                            if re.match(r'^01[0-9A-F]{14}$', title_id):
                                self.log_signal.emit(f"🔍 [Switch] Detected Title ID from XCI header: {title_id}")
                            else: title_id = None
                    except Exception: pass

                # --- Method 3: Fixed Recency Scan ---
                if not title_id:
                    self.log_signal.emit(f"🔍 [Switch] Scanning for recently modified save folders...")
                    recent_tid = None
                    max_mtime = 0
                    for root in search_roots:
                        save_base = root / "nand/user/save/0000000000000000"
                        if not save_base.exists(): continue
                        for profile_dir in save_base.iterdir():
                            if not profile_dir.is_dir(): continue
                            for tid_dir in profile_dir.iterdir():
                                if tid_dir.is_dir() and re.match(r'^01[0-9A-F]{14}$', tid_dir.name):
                                    mtime = tid_dir.stat().st_mtime
                                    if mtime > max_mtime:
                                        max_mtime = mtime
                                        recent_tid = tid_dir.name
                    if recent_tid:
                        title_id = recent_tid
                        self.log_signal.emit(f"✨ [Switch] Matched recent save folder: {title_id}")

                # --- Method 4: Regex fallback ---
                if not title_id:
                    m_tid = re.search(r'01[0-9A-F]{14}', full_cmd, re.IGNORECASE)
                    if m_tid:
                        title_id = m_tid.group(0).upper()
                        self.log_signal.emit(f"🔍 [Switch] Detected Title ID from command line: {title_id}")

                # Final Path Resolution
                if title_id:
                    for root in search_roots:
                        save_base = root / "nand/user/save/0000000000000000"
                        if not save_base.exists(): continue
                        
                        for profile_dir in save_base.iterdir():
                            if not profile_dir.is_dir(): continue
                            candidate = profile_dir / title_id
                            if candidate.exists():
                                self.log_signal.emit(f"✨ [Switch] Found save in: {candidate}")
                                return candidate
                        
                        profiles = [d for d in save_base.iterdir() if d.is_dir()]
                        if profiles:
                            final_path = profiles[0] / title_id
                            self.log_signal.emit(f"✨ [Switch] Targeted save location: {final_path}")
                            return final_path
                
                return None

            # 2. GAMECUBE / WII / NGC (DOLPHIN)
            elif "Dolphin" in emu_display_name or platform in ["gc", "wii", "ngc"]:
                user_dir = Path.home() / "Documents" / "Dolphin Emulator"
                if (emu_dir / "portable.txt").exists() or (emu_dir / "User").exists(): 
                    user_dir = emu_dir / "User"
                
                game_id = None
                if proc:
                    try:
                        for f in proc.open_files():
                            p = Path(f.path)
                            if platform == "wii" and "title/00010000" in p.as_posix() and "data" in p.name:
                                return p.parent
                            if platform in ["gc", "ngc"] and (p.suffix.lower() in [".raw", ".gci", ".sav"]):
                                return p
                            if "GameSettings" in p.as_posix() and p.suffix.lower() == ".ini":
                                if len(p.stem) == 6 and re.match(r'[A-Z0-9]{6}', p.stem):
                                    game_id = p.stem
                    except Exception: pass

                if not game_id:
                    game_id = self.get_game_id_from_rom(full_cmd)
                    
                clean_title = re.sub(r'[^a-z0-9]', '', title.lower())
                
                for region in ["USA", "EUR", "JPN", "KOR", "JAP"]:
                    gci_folder = user_dir / f"GC/{region}/Card A"
                    if not gci_folder.exists(): continue

                    if game_id:
                        short_id = game_id[:4]
                        for f in gci_folder.glob(f"*{short_id}*.gci"): return f
                        for f in gci_folder.glob(f"*-{short_id}-*.gci"): return f
                        very_short_id = game_id[:3]
                        for f in gci_folder.glob(f"*{very_short_id}*.gci"): return f

                    for f in gci_folder.glob("*.gci"):
                        clean_f = re.sub(r'[^a-z0-9]', '', f.stem.lower())
                        if clean_title in clean_f or clean_f in clean_title:
                            return f

                if platform == "wii":
                    nand_base = user_dir / "Wii/title/00010000"
                    if nand_base.exists():
                        subdirs = [d for d in nand_base.iterdir() if d.is_dir()]
                        if subdirs:
                            subdirs.sort(key=lambda x: x.stat().st_mtime, reverse=True)
                            for d in subdirs:
                                if (d / "data").exists(): return d / "data"
                else:
                    gc_dir = user_dir / "GC"
                    search_paths = [gc_dir / "MemoryCardA.USA.raw", gc_dir / "MemoryCardA.EUR.raw", gc_dir / "MemoryCardA.JPN.raw", gc_dir / "MemoryCardA.raw"]
                    for p in search_paths:
                        if p.exists(): return p
                    return search_paths[0] if search_paths[0].exists() else None

            # 3. PLAYSTATION 2
            elif "PlayStation 2" in emu_display_name or platform == "ps2":
                search_paths = [emu_dir / "memcards" / "Mcd001.ps2", Path(os.path.expandvars(r'%APPDATA%\PCSX2\memcards\Mcd001.ps2')), Path.home() / "Documents" / "PCSX2" / "memcards" / "Mcd001.ps2"]
                for p in search_paths:
                    if p.exists(): return p
                return search_paths[0]

            # 4. RETROARCH
            elif "RetroArch" in emu_display_name or platform == "multi":
                rom_name = Path(title).stem.lower()
                for game in self.client.user_games:
                    if game['name'] == title: rom_name = Path(game['fs_name']).stem.lower()
                search_paths = [emu_dir / "saves", Path(os.path.expandvars(r'%APPDATA%\RetroArch\saves'))]
                for p in search_paths:
                    if p.exists():
                        for f in p.glob(f"*{rom_name}*.srm"): return f
                return search_paths[0] / f"{rom_name}.srm"
        except Exception as e:
            self.log_signal.emit(f"⚠️ Error resolving save path: {e}")
            
        return None

    def handle_exit(self, data):
        try:
            self.log_signal.emit(f"🛑 Session Ended: {data['title']}")
            time.sleep(2)
            
            save_path = Path(data['save_path'])
            if not save_path.exists():
                self.log_signal.emit(f"⚠️ Save file missing on exit: {save_path}. Skipping sync.")
                return
                
            if data['is_folder'] and not any(save_path.iterdir()):
                self.log_signal.emit("⚠️ Save folder empty on exit. Skipping sync.")
                return
                
            new_h = calculate_folder_hash(str(save_path)) if data['is_folder'] else calculate_file_hash(str(save_path))
            
            if new_h == data['initial_hash']:
                self.log_signal.emit(f"⏭️ No changes in {data['title']}. Skipping sync.")
                return

            self.log_signal.emit(f"📝 Changes detected! Syncing...")
            temp_zip = f"sync_{data['rom_id']}.zip"
            try:
                zip_path(str(save_path), temp_zip)
                success, msg = self.client.upload_save(data['rom_id'], data['emu'], temp_zip)
                if success:
                    self.log_signal.emit("✨ Sync Complete!")
                    if str(data['rom_id']) in self.sync_cache:
                        del self.sync_cache[str(data['rom_id'])]
                        self.save_cache()
                else:
                    self.log_signal.emit(f"❌ Sync Failed: {msg}")
            finally:
                if os.path.exists(temp_zip):
                    try: os.remove(temp_zip)
                    except Exception: pass
        except Exception as e:
            self.log_signal.emit(f"❌ Error during sync: {e}")

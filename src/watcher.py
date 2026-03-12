import time
import psutil
import os
import re
import shutil
import zipfile
import json
import hashlib
import logging
import traceback
from datetime import datetime, timezone
from pathlib import Path
from PySide6.QtCore import QThread, Signal, QTimer, Slot, Qt, QCoreApplication
from src.utils import calculate_folder_hash, calculate_file_hash, calculate_zip_content_hash, zip_path, extract_strip_root
from src import emulators
from src.save_strategies import get_strategy

class PostSessionSyncThread(QThread):
    done = Signal(str, bool)   # rom_name, success
    log  = Signal(str)         # log message for GUI
    notify = Signal(str, str)  # title, body for tray notification

    def __init__(self, watcher, data, new_m=None, new_h=None):
        super().__init__()
        self.watcher = watcher
        self.data = data
        self.rom_id = data.get('rom_id')
        self.new_m = new_m
        self.new_h = new_h

    def run(self):
        title = self.data.get('title', 'Unknown Game')
        logging.info(f"[SyncThread] run() started for {title}")
        rom_id = str(self.data.get('rom_id'))
        emu_id = self.data.get('emulator', {}).get('id', 'unknown')
        strategy = self.data.get('strategy')
        rom = self.data.get('game_data')

        try:
            logging.info(f"[SyncThread] Starting sync for {title}")
            save_files = strategy.get_save_files(rom)

            if not save_files:
                self.log.emit(f"💤 No saves found for {title}, skipping upload")
                self.done.emit(title, True)
                return

            # Change detection inside thread
            new_h = self.watcher._get_current_hash(strategy, rom)
            new_m = self.watcher._get_max_mtime(strategy, rom)
            init_h = self.data.get('initial_hash')
            init_m = self.data.get('initial_mtime', 0)

            if init_h is not None and new_h == init_h and new_m <= init_m:
                try:
                    all_saves = self.watcher.client.list_all_saves(str(self.rom_id))
                    wingosy_saves = [s for s in all_saves if str(s.get('slot','')).startswith('wingosy-srm')]
                    cloud_missing = len(wingosy_saves) == 0
                except Exception:
                    cloud_missing = False
                
                if not cloud_missing:
                    logging.info(f"[SyncThread] No changes detected in files for {title}, skipping upload")
                    self.log.emit(f"💤 No changes in {title}. Skipping sync.")
                    self.done.emit(title, True)
                    return
                
                self.log.emit(f"☁️ No wingosy cloud save found for {title}, uploading...")

            ok = True  # innocent until proven guilty
            uploaded_count = 0
            # Split save files: .ps2 (zipped together) vs others (individual)
            ps2_files   = [f for f in save_files if not f.is_dir() and f.suffix.lower() == '.ps2' and '.bak' not in f.name.lower()]
            srm_files   = [f for f in save_files if not f.is_dir() and f.suffix.lower() in ('.srm', '.sav') and '.bak' not in f.name.lower()]
            state_files  = [f for f in save_files if not f.is_dir() and '.state' in f.name.lower() and '.bak' not in f.name.lower()]
            folder_files = [f for f in save_files if f.is_dir()]

            ts = time.strftime("_%Y-%m-%d_%H-%M")

            if folder_files:
                # Folder (e.g. PSP SAVEDATA) — zip and upload as save
                save_dir = folder_files[0]
                temp_zip = Path.home() / ".wingosy" / "tmp" / f"upload_{rom_id}.zip"
                temp_zip.parent.mkdir(parents=True, exist_ok=True)
                zip_path(str(save_dir), str(temp_zip))
                
                fname = f"save{ts}.zip"
                slot_name = f"wingosy-srm{ts}"
                logging.info(f"[SyncThread] Uploading folder save: slot={slot_name}, filename={fname}")
                ok2, msg = self.watcher.client.upload_save(rom_id, emu_id, str(temp_zip), slot=slot_name, filename_override=fname)
                if ok2:
                    uploaded_count += 1
                if temp_zip.exists(): temp_zip.unlink()
                ok = ok and ok2

            if ps2_files:
                # PS2 Memory Cards — zip all .ps2 files together and upload as one save
                temp_zip = Path.home() / ".wingosy" / "tmp" / f"ps2_upload_{rom_id}.zip"
                temp_zip.parent.mkdir(parents=True, exist_ok=True)
                with zipfile.ZipFile(temp_zip, 'w', zipfile.ZIP_DEFLATED) as zf:
                    for f in ps2_files:
                        zf.write(f, f.name)
                
                fname = f"memcards{ts}.zip"
                slot_name = f"wingosy-srm{ts}"
                logging.info(f"[SyncThread] Uploading PS2 memcards zip: slot={slot_name}, filename={fname} ({len(ps2_files)} files)")
                ok2, msg = self.watcher.client.upload_save(rom_id, emu_id, str(temp_zip), slot=slot_name, filename_override=fname)
                if ok2:
                    uploaded_count += 1
                if temp_zip.exists(): temp_zip.unlink()
                ok = ok and ok2

            for srm in srm_files:
                fname = f"{srm.stem}{ts}{srm.suffix}"
                slot_name = f"wingosy-srm{ts}"
                logging.info(f"[SyncThread] Uploading SRM: slot={slot_name}, filename={fname}")
                ok2, msg = self.watcher.client.upload_save(rom_id, emu_id, str(srm), slot=slot_name, filename_override=fname)
                if ok2:
                    uploaded_count += 1
                ok = ok and ok2

            for st in state_files:
                fname = f"{st.stem}{ts}{st.suffix}"
                slot_name = f"wingosy-state{ts}"
                logging.info(f"[SyncThread] Uploading state: slot={slot_name}, filename={fname}")
                ok2, msg = self.watcher.client.upload_state(rom_id, emu_id, str(st), slot=slot_name, filename_override=fname)
                if ok2:
                    uploaded_count += 1
                ok = ok and ok2

            # Prune old versions if successful
            if ok and uploaded_count > 0:
                try:
                    limit = self.watcher.config.get("max_save_versions", 5)
                    # Prune saves (only wingosy-srm* slots)
                    saves = self.watcher.client.list_all_saves(rom_id)
                    wingosy_saves = [s for s in saves if str(s.get("slot", "")).startswith("wingosy-srm")]
                    
                    if len(wingosy_saves) > limit:
                        wingosy_saves.sort(key=lambda x: x.get("updated_at", ""), reverse=True)
                        for old in wingosy_saves[limit:]:
                            logging.info(f"[SyncThread] Deleting old save version: {old.get('slot')} (ID: {old['id']})")
                            self.watcher.client.delete_save(old['id'])
                    
                    # Prune states (only wingosy-state* slots)
                    states = self.watcher.client.list_all_states(rom_id)
                    wingosy_states = [s for s in states if str(s.get("slot", "")).startswith("wingosy-state")]
                    
                    if len(wingosy_states) > limit:
                        wingosy_states.sort(key=lambda x: x.get("updated_at", ""), reverse=True)
                        for old in wingosy_states[limit:]:
                            logging.info(f"[SyncThread] Deleting old state version: {old.get('slot')} (ID: {old['id']})")
                            self.watcher.client.delete_state(old['id'])
                except Exception as e:
                    logging.error(f"[SyncThread] Pruning failed: {e}")

            if ok:
                if uploaded_count > 0:
                    self.log.emit(f"✅ Sync complete: {title}")
                    self.notify.emit("Wingosy", f"✅ Saved to cloud: {title}")
                else:
                    self.log.emit(f"💤 No changes to sync for {title}")
            else:
                self.log.emit(f"❌ Sync failed: {title}")
                self.notify.emit("Wingosy", f"❌ Sync failed: {title}")
            
            self.done.emit(title, ok)

        except Exception as e:
            logging.error(f"[SyncThread] Error for {title}: {e}")
            traceback.print_exc()
            self.log.emit(f"❌ Sync error for {title}: {e}")
            self.notify.emit("Wingosy", f"❌ Sync error: {title}")
            self.done.emit(title, False)

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
        self.session_errors = {} # rom_id -> consecutive error count
        self.skip_next_pull_rom_id = None # Flag to prevent double-pull when launching from app
        self._sync_threads = []
        self._active_conflicts = set()

        self.tmp_dir = Path.home() / ".wingosy" / "tmp"
        self.tmp_dir.mkdir(parents=True, exist_ok=True)
        
        self.cache_path = Path.home() / ".wingosy" / "sync_cache.json"
        self.sync_cache = {}
        if self.cache_path.exists():
            try:
                with open(self.cache_path, 'r') as f:
                    self.sync_cache = json.load(f)
            except Exception as e:
                logging.error(f"[Watcher] Cache load error: {e}")

    def save_cache(self):
        try:
            with open(self.cache_path, 'w') as f:
                json.dump(self.sync_cache, f)
        except Exception as e:
            logging.error(f"[Watcher] Cache save error: {e}")

    def run(self):
        logging.info("🚀 Watcher Active (Process-Specific Mode).")
        while self.running:
            for pid, data in list(self.active_sessions.items()):
                try:
                    if not psutil.pid_exists(pid):
                        try:
                            self.handle_exit(data)
                        except Exception as e:
                            logging.error(f"[Watcher] Error in handle_exit for {data.get('title')}:\n{traceback.format_exc()}")
                        del self.active_sessions[pid]
                    else:
                        now = time.time()
                        interval = self.config.get("sync_interval_seconds", 120)
                        if now - data.get("last_sync_time", 0) >= interval:
                            try:
                                self._do_mid_session_sync(data)
                            except Exception as e:
                                logging.error(f"[Watcher] Error in mid-session sync for {data.get('title')}: {e}")
                            data["last_sync_time"] = now
                except Exception as e:
                    logging.error(f"❌ Error monitoring PID {pid}: {e}")
                    del self.active_sessions[pid]
            time.sleep(5)

    def _get_current_hash(self, strategy, rom):
        try:
            files = strategy.get_save_files(rom)
            if not files: return None
            h = hashlib.md5()
            found = False
            for p in sorted(files):
                if not p.exists(): continue
                found = True
                if p.is_dir():
                    # Handle folder-based saves (e.g. PSP)
                    f_hash = calculate_folder_hash(str(p))
                    if f_hash: h.update(f_hash.encode('utf-8'))
                else:
                    with open(p, 'rb') as f:
                        while True:
                            chunk = f.read(8192)
                            if not chunk: break
                            h.update(chunk)
            return h.hexdigest() if found else None
        except Exception as e:
            logging.error(f"[Watcher] Hash calculation failed for {rom.get('name')}: {e}")
            return None

    def _get_max_mtime(self, strategy, rom):
        try:
            files = strategy.get_save_files(rom)
            if not files: return 0
            
            mtimes = []
            for p in files:
                if not p.exists(): continue
                if p.is_dir():
                    # For directories, get max mtime of any file inside
                    for root, _, walk_files in os.walk(p):
                        for f in walk_files:
                            try: mtimes.append(os.path.getmtime(os.path.join(root, f)))
                            except: pass
                    # Also include the directory's own mtime
                    mtimes.append(os.path.getmtime(p))
                else:
                    mtimes.append(os.path.getmtime(p))
            
            return max(mtimes, default=0)
        except Exception as e:
            logging.error(f"[Watcher] MTime check failed for {rom.get('name')}: {e}")
            return 0

    def track_session(self, proc, emu_display_name, game_data, local_rom_path, emu_path, skip_pull=False, windows_save_dir=None):
        try:
            pid = proc.pid
            rom_id = game_data['id']
            title = game_data['name']
            
            logging.debug(f"[Sync] track_session for {title} (ROM ID: {rom_id})")

            all_emus = emulators.load_emulators()
            this_emu = next((e for e in all_emus if e["name"] == emu_display_name or e["id"] == emu_display_name), None)
            
            WINDOWS_PLATFORM_SLUGS = ["windows", "win", "pc", "pc-windows", "windows-games", "win95", "win98"]
            if not this_emu and (windows_save_dir or game_data.get("platform_slug") in WINDOWS_PLATFORM_SLUGS):
                this_emu = {"id": "windows_native", "is_native": True, "name": "Windows (Native)"}

            if not this_emu:
                logging.error(f"[Watcher] Could not find emulator metadata for {emu_display_name}")
                return

            strategy = get_strategy(self.config, this_emu)
            strategy.set_session_context(start_time=time.time(), rom_path=local_rom_path)
            logging.debug(f"[Sync] Strategy: {strategy.__class__.__name__}")
            
            # 1. Pull if needed
            should_pull = (self.config.get("auto_pull_saves", True) and not skip_pull)
            if self.skip_next_pull_rom_id == str(rom_id):
                should_pull = False
                self.skip_next_pull_rom_id = None
            
            if should_pull:
                save_dir = strategy.get_save_dir(game_data)
                if save_dir:
                    self.pull_server_save(rom_id, title, str(save_dir), True, emu_id=this_emu["id"])
                else:
                    files = strategy.get_save_files(game_data)
                    if files:
                        self.pull_server_save(rom_id, title, str(files[0]), False, emu_id=this_emu["id"])

            # 2. Capture initial state
            h = self._get_current_hash(strategy, game_data)
            m = self._get_max_mtime(strategy, game_data)

            session_data = {
                'rom_id': rom_id,
                'title': title,
                'game_data': game_data,
                'strategy': strategy,
                'emulator': this_emu,
                'initial_hash': h,
                'initial_mtime': m,
                'start_time': time.time(),
                'last_sync_time': time.time(),
            }
            self.active_sessions[pid] = session_data
            self.log_signal.emit(f"🎮 Tracking {title} on {this_emu['name']} (PID: {pid})")

        except Exception as e:
            logging.error(f"Error starting session tracking: {e}")

    def handle_exit(self, data):
        title, rom_id, strategy, rom, emu = data['title'], data['rom_id'], data['strategy'], data['game_data'], data['emulator']

        if not emu.get("sync_enabled", True):
            logging.info(f"[Watcher] Sync disabled for {emu['name']}, skipping upload for {title}")
            return

        if rom_id and self.session_errors.get(str(rom_id), 0) >= 5:
            logging.warning(f"[Watcher] Giving up on save sync for {title} after 5 consecutive errors")
            return

        self.log_signal.emit(f"🛑 Session Ended: {title}")
        
        new_h = self._get_current_hash(strategy, rom)
        new_m = self._get_max_mtime(strategy, rom)
        
        cache_entry = self.sync_cache.get(str(rom_id), {})
        cached_mtime = cache_entry.get("save_mtime") or cache_entry.get("save_updated_at")
        if isinstance(cached_mtime, str):
            try:
                cached_mtime = datetime.fromisoformat(cached_mtime).timestamp()
            except Exception:
                cached_mtime = None
        
        logging.debug(f"[Watcher] Exit Sync Check: {title} (ROM ID: {rom_id}) | cached_mtime: {cached_mtime} | new_m: {new_m}")

        if new_h is not None:
            if new_h == data.get('initial_hash'):
                # Even if unchanged locally, sync if cloud has no save or hash differs
                try:
                    all_saves = self.client.list_all_saves(str(rom_id))
                    wingosy_saves = [s for s in all_saves if str(s.get('slot','')).startswith('wingosy-srm')]
                    cloud_missing = len(wingosy_saves) == 0
                except Exception:
                    cloud_missing = False
                
                if not cloud_missing:
                    self.log_signal.emit(f"💤 No changes in {title}. Skipping sync.")
                    self._update_playtime(data)
                    return
                # Cloud missing — upload anyway
                self.log_signal.emit(f"☁️ No wingosy cloud save found for {title}, uploading...")
            should_sync = True
        else:
            # Fallback to mtime check ONLY if hash is unavailable
            if cached_mtime is None:
                should_sync = True
            else:
                should_sync = new_m > cached_mtime

        if not should_sync:
            self.log_signal.emit(f"💤 No changes in {title}. Skipping sync.")
            self._update_playtime(data)
            return

        self.log_signal.emit(f"📤 Syncing {title} in background...")

        # Start background sync thread — upload happens entirely in the thread
        thread = PostSessionSyncThread(self, data, new_m=new_m)
        thread.log.connect(self.log_signal)
        thread.notify.connect(self.notify_signal)
        thread.done.connect(lambda name, ok: self._on_sync_thread_done(str(rom_id), new_m, ok))

        self._sync_threads.append(thread)
        thread.finished.connect(lambda t=thread: self._sync_threads.remove(t) if t in self._sync_threads else None)
        thread.start()
        
        self._update_playtime(data)

    def _on_sync_thread_done(self, rom_id, new_m, success):
        rom_id_str = str(rom_id)
        if success:
            self.session_errors[rom_id_str] = 0
            entry = self.sync_cache.get(rom_id_str, {})
            entry["save_mtime"] = new_m
            entry.pop("save_updated_at", None)
            logging.info(f"[Watcher] Sync success for {rom_id_str}. Cache updated.")
            self.sync_cache[rom_id_str] = entry
            self.save_cache()
        else:
            self.session_errors[rom_id_str] = self.session_errors.get(rom_id_str, 0) + 1

    def _do_mid_session_sync(self, data):
        strategy, rom = data['strategy'], data['game_data']
        rom_id = data['rom_id']
        title = data['title']
        
        new_h = self._get_current_hash(strategy, rom)
        new_m = self._get_max_mtime(strategy, rom)
        
        cache_entry = self.sync_cache.get(str(rom_id), {})
        cached_mtime = cache_entry.get("save_mtime") or cache_entry.get("save_updated_at")
        if isinstance(cached_mtime, str):
            try:
                cached_mtime = datetime.fromisoformat(cached_mtime).timestamp()
            except Exception:
                cached_mtime = None
        
        should_sync = False
        if cached_mtime is None:
            should_sync = True
        else:
            should_sync = new_m > cached_mtime

        if should_sync or (new_h and new_h != data.get('last_mid_sync_hash', data.get('initial_hash'))):
            logging.info(f"🔄 Mid-session changes detected for {title}. Syncing...")
            # Mid-session we still do async via thread — upload happens entirely in the thread
            thread = PostSessionSyncThread(self, data, new_m=new_m, new_h=new_h)
            thread.log.connect(self.log_signal)
            thread.notify.connect(self.notify_signal)
            thread.done.connect(lambda name, ok: self._on_sync_thread_done(str(rom_id), new_m, ok))
            
            self._sync_threads.append(thread)
            thread.finished.connect(lambda t=thread: self._sync_threads.remove(t) if t in self._sync_threads else None)
            thread.start()
            data['last_mid_sync_hash'] = new_h

    def _update_playtime(self, data):
        try:
            elapsed = int(time.time() - data.get('start_time', time.time()))
            if elapsed > 10:
                self.client.update_playtime(data['rom_id'], elapsed)
                logging.info(f"[Watcher] Playtime updated for {data['title']}: {elapsed}s")
        except Exception as e:
            logging.error(f"[Watcher] Playtime update failed: {e}")

    def pull_server_save(self, rom_id, title, local_path, is_folder, force=False, emu_id=None):
        behavior = self.config.get("conflict_behavior", "ask")
        if emu_id:
            all_emus = emulators.load_emulators()
            emu = next((e for e in all_emus if e["id"] == emu_id), None)
            if emu: behavior = emu.get("conflict_behavior", "ask")

        if behavior == "prefer_local" and not force: return

        try:
            latest_save = self.client.get_latest_save(rom_id)
            if latest_save:
                self._apply_cloud_file(rom_id, title, latest_save, local_path, is_folder, force, behavior=behavior)
        except Exception as e:
            logging.error(f"[Watcher] pull_server_save failed for {title}: {e}")

    def _apply_cloud_file(self, rom_id, title, cloud_obj, local_path, is_folder, force, behavior="ask"):
        try:
            server_updated_at = cloud_obj.get('updated_at', '')
            cached_val = self.sync_cache.get(str(rom_id), {})
            cached_ts = cached_val.get('save_updated_at', '') if isinstance(cached_val, dict) else ""

            if not force and cached_ts == server_updated_at and os.path.exists(local_path):
                return

            temp_dl = str(self.tmp_dir / f"cloud_pull_{rom_id}")
            if self.client.download_save(cloud_obj, temp_dl):
                if os.path.exists(local_path) and behavior == "ask" and not force:
                    remote_h = calculate_zip_content_hash(temp_dl) if zipfile.is_zipfile(temp_dl) else calculate_file_hash(temp_dl)
                    local_h = calculate_folder_hash(local_path) if is_folder else calculate_file_hash(local_path)
                    if remote_h == local_h:
                        self.sync_cache[str(rom_id)] = {"save_updated_at": server_updated_at}
                        self.save_cache()
                        return
                    
                    if str(rom_id) in self._active_conflicts:
                        return
                    
                    self._active_conflicts.add(str(rom_id))
                    self.conflict_signal.emit(title, local_path, temp_dl, str(rom_id))
                    return

                if is_folder:
                    os.makedirs(local_path, exist_ok=True)
                    extract_strip_root(temp_dl, local_path)
                else:
                    os.makedirs(os.path.dirname(local_path), exist_ok=True)
                    shutil.copy2(temp_dl, local_path)

                self.sync_cache[str(rom_id)] = {"save_updated_at": server_updated_at}
                self.save_cache()
                self.log_signal.emit(f"✨ Cloud save applied for {title}!")
        except Exception as e:
            logging.error(f"[Watcher] _apply_cloud_file failed: {e}")
        finally:
            if 'temp_dl' in locals() and os.path.exists(temp_dl): os.remove(temp_dl)

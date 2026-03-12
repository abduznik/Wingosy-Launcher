import sys
import os
import requests
import zipfile
import shutil
import subprocess
import time
import logging
import re
from pathlib import Path
from PySide6.QtCore import QThread, Signal
from PySide6.QtGui import QPixmap, QImage

from src.sevenzip import get_7zip_exe

# Try to import py7zr for extraction fallback
try:
    import py7zr
    HAS_PY7ZR = True
except ImportError:
    HAS_PY7ZR = False

from src import pcgamingwiki
from src.utils import extract_strip_root

class LocalDiscoveryWorker(QThread):
    """
    Background worker to robustly find ROMs on disk without freezing the UI.
    Emits rom_discovered(game_id, local_path) for each found ROM.
    """
    rom_discovered = Signal(int, str)
    finished_discovery = Signal()

    def __init__(self, games: list, config_data: dict):
        super().__init__()
        self.games = games
        self.config_data = config_data
        self._is_running = True

    def stop(self):
        self._is_running = False

    def run(self):
        from src.utils import resolve_local_rom_path
        for game in self.games:
            if not self._is_running:
                break
            
            # Skip if already marked as exists (e.g. from a previous partial scan)
            if game.get('_local_exists'):
                continue

            try:
                path = resolve_local_rom_path(game, self.config_data)
                if path and path.exists():
                    self.rom_discovered.emit(game['id'], str(path))
            except Exception as e:
                logging.debug(f"[Discovery] Error resolving {game.get('name')}: {e}")
        
        self.finished_discovery.emit()

class WikiFetcherThread(QThread):
    finished = Signal(list)
    def __init__(self, game_title, windows_games_dir=""):
        super().__init__()
        self.game_title = game_title
        self.win_dir = windows_games_dir
    def run(self):
        try:
            results = pcgamingwiki.fetch_save_locations(self.game_title, self.win_dir)
            self.finished.emit(results)
        except Exception:
            self.finished.emit([])

class ImageFetcher(QThread):
    finished = Signal(int, QPixmap)
    def __init__(self, game_id, url):
        super().__init__()
        self.game_id = game_id
        self.url = url
    def run(self):
        try:
            verify = os.environ.get('REQUESTS_CA_BUNDLE', True)
            r = requests.get(self.url, timeout=15, verify=verify)
            if r.status_code == 200:
                img = QImage()
                if img.loadFromData(r.content):
                    self.finished.emit(self.game_id, QPixmap.fromImage(img))
        except Exception:
            pass

class GameDescriptionFetcher(QThread):
    finished = Signal(str)
    def __init__(self, client, rom_id):
        super().__init__()
        self.client = client
        self.rom_id = rom_id
    def run(self):
        try:
            rom = self.client.get_rom_details(self.rom_id)
            if not rom:
                self.finished.emit("No description available.")
                return

            summary = (
                rom.get("summary") or
                rom.get("description") or
                rom.get("igdb_metadata", {}).get("summary") or
                rom.get("moby_metadata", {}).get("summary") or
                rom.get("ss_metadata", {}).get("summary")
            )

            self.finished.emit(summary or "No description available.")      
        except Exception:
            self.finished.emit("No description available.")

class ExtractionThread(QThread):
    progress  = Signal(int, int) # (current, total)
    finished  = Signal(str)      # target_dir
    error     = Signal(str)
    cancelled = Signal(str)      # target_dir

    def __init__(self, archive_path, target_dir):
        super().__init__()
        self.archive_path = Path(archive_path)
        self.target_dir = Path(target_dir)
        self._cancelled = False

    def cancel(self):
        self._cancelled = True

    def run(self):
        try:
            ext = self.archive_path.suffix.lower()
            
            if ext == ".zip":
                ok = self._extract_zip()
            else:
                exe = get_7zip_exe()
                if exe:
                    ok = self._extract_7z(exe)
                else:
                    ok = self._extract_py7zr()
            
            if not ok:
                return
            
            self._strip_root()
            
            try:
                self.archive_path.unlink()
            except Exception:
                pass
            
            self.finished.emit(str(self.target_dir))
        except Exception as e:
            self.error.emit(str(e))

    def _extract_zip(self) -> bool:
        with zipfile.ZipFile(self.archive_path, 'r') as zf:
            members = zf.namelist()
            total = len(members)
            os.makedirs(self.target_dir, exist_ok=True)
            for i, member in enumerate(members):
                if self._cancelled:
                    self.cancelled.emit(str(self.target_dir))
                    return False
                zf.extract(member, str(self.target_dir))
                self.progress.emit(i + 1, total)
        return True

    def _extract_7z(self, exe_path) -> bool:
        self.target_dir.mkdir(parents=True, exist_ok=True)
        
        cmd = [
            exe_path, "x",
            str(self.archive_path),
            f"-o{str(self.target_dir)}",
            "-y",
            "-bsp1",  # progress to stdout
            "-bso0",  # suppress normal output
        ]
        
        flags = 0
        if hasattr(subprocess, "CREATE_NO_WINDOW"):
            flags = subprocess.CREATE_NO_WINDOW
        
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            creationflags=flags
        )
        
        pct_re = re.compile(r'^\s*(\d{1,3})%')
        last_pct = 0
        
        if proc.stdout:
            for line in proc.stdout:
                if self._cancelled:
                    proc.terminate()
                    proc.wait()
                    self.cancelled.emit(str(self.target_dir))
                    return False
                
                m = pct_re.match(line)
                if m:
                    pct = int(m.group(1))
                    if pct != last_pct:
                        last_pct = pct
                        self.progress.emit(pct, 100)
        
        proc.wait()
        
        if self._cancelled:
            self.cancelled.emit(str(self.target_dir))
            return False
        
        if proc.returncode not in (0, 1):
            raise RuntimeError(f"7z exit code: {proc.returncode}")
        
        self.progress.emit(100, 100)
        return True

    def _extract_py7zr(self) -> bool:
        if not HAS_PY7ZR:
            raise RuntimeError("py7zr not installed and 7z.exe not found")
        
        logging.warning("[Extract] Using py7zr fallback — this may be slow")
        self.progress.emit(0, 0)
        with py7zr.SevenZipFile(self.archive_path, 'r') as z:
            z.extractall(str(self.target_dir))
        if self._cancelled:
            self.cancelled.emit(str(self.target_dir))
            return False
        self.progress.emit(1, 1)
        return True

    def _strip_root(self):
        try:
            contents = list(self.target_dir.iterdir())
            if len(contents) == 1 and contents[0].is_dir():
                inner = contents[0]
                tmp = self.target_dir / "_tmp_extract"
                inner.rename(tmp)
                for item in tmp.iterdir():
                    item.rename(self.target_dir / item.name)
                try:
                    tmp.rmdir()
                except Exception:
                    pass
        except Exception as e:
            logging.warning(f"[Extract] Strip root failed: {e}")

class BaseDownloader(QThread):
    progress = Signal(float, float, float) # downloaded, total, speed
    finished = Signal(bool, str)
    cancelled = Signal()

    def __init__(self):
        super().__init__()
        self._cancelled = False
        self.file_path = None

    def cancel(self):
        self._cancelled = True

    def perform_download(self, url, target_dir):
        try:
            name = url.split('/')[-1].split('?')[0]
            target_path = os.path.join(target_dir, name)
            self.file_path = target_path
            headers = {'User-Agent': 'Mozilla/5.0'} 
            verify = os.environ.get('REQUESTS_CA_BUNDLE', True)
            r = requests.get(url, stream=True, timeout=30, headers=headers, verify=verify)
            r.raise_for_status()

            total = int(r.headers.get('content-length', 0))
            downloaded = 0
            
            self._last_time = time.time()
            self._last_bytes = 0
            
            with open(target_path, 'wb') as f:
                for chunk in r.iter_content(8192):
                    if self._cancelled or self.isInterruptionRequested():
                        f.close()
                        self.cancelled.emit()
                        return False, "Cancelled"
                    if chunk:
                        f.write(chunk)
                        downloaded += len(chunk)
                        
                        now = time.time()
                        elapsed = now - self._last_time
                        if elapsed >= 0.5:
                            speed = (downloaded - self._last_bytes) / elapsed
                            self._last_bytes = downloaded
                            self._last_time = now
                            self.progress.emit(float(downloaded), float(total), float(speed))
                        else:
                            self.progress.emit(float(downloaded), float(total), 0.0)

            return True, target_path
        except Exception as e:
            return False, str(e)

class DirectDownloader(BaseDownloader):
    def __init__(self, url, target_dir):
        super().__init__()
        self.url = url
        self.target_dir = target_dir
    def run(self):
        ok, msg = self.perform_download(self.url, self.target_dir)
        if ok and not self._cancelled:
            self.finished.emit(True, msg)

class DolphinDownloader(BaseDownloader):
    def __init__(self, target_dir):
        super().__init__()
        self.target_dir = target_dir
    def run(self):
        try:
            api_url = "https://dolphin-emu.org/download/list/master/1/?format=json"
            headers = {'User-Agent': 'Mozilla/5.0'}
            verify = os.environ.get('REQUESTS_CA_BUNDLE', True)
            resp = requests.get(api_url, timeout=15, headers=headers, verify=verify)
            if resp.status_code != 200:
                download_url = "https://dl.dolphin-emu.org/releases/2512/dolphin-2512-x64.7z"
            else:
                data = resp.json()
                download_url = data['builds'][0]['artifacts']['win-x64']['url']

            ok, msg = self.perform_download(download_url, self.target_dir)  
            if ok and not self._cancelled:
                self.finished.emit(True, msg)
        except Exception:
            download_url = "https://dl.dolphin-emu.org/releases/2512/dolphin-2512-x64.7z"
            ok, msg = self.perform_download(download_url, self.target_dir)  
            if ok and not self._cancelled:
                self.finished.emit(True, msg)

class GithubDownloader(BaseDownloader):
    def __init__(self, repo, target_dir, required_keywords=None, excluded_keywords=None):
        super().__init__()
        self.repo = repo
        self.target_dir = target_dir
        self.required_keywords = required_keywords or ['win', 'x64', 'windows', 'amd64', 'msvc', 'desktop']
        self.excluded_keywords = excluded_keywords or ['installer', 'symbols', 'debug']

    def run(self):
        try:
            api_url = f"https://api.github.com/repos/{self.repo}/releases/latest"
            headers = {'User-Agent': 'WingosyLauncher'}
            verify = os.environ.get('REQUESTS_CA_BUNDLE', True)
            resp_obj = requests.get(api_url, timeout=15, headers=headers, verify=verify)
            if resp_obj.status_code != 200:
                self.finished.emit(False, f"Repo {self.repo} not found.")   
                return

            resp = resp_obj.json()
            zip_assets = []
            for a in resp.get('assets', []):
                name = a['name'].lower()
                if any(ex in name for ex in self.excluded_keywords): continue
                if not any(name.endswith(ext) for ext in ['.zip', '.7z']): continue
                if any(k in name for k in self.required_keywords): zip_assets.append(a)

            asset = next((a for a in zip_assets if a['name'].lower().endswith('.zip')), None)
            if not asset: asset = next((a for a in zip_assets if a['name'].lower().endswith('.7z')), None)

            if not asset:
                self.finished.emit(False, "No suitable release file found.")
                return

            ok, msg = self.perform_download(asset['browser_download_url'], self.target_dir)
            if ok and not self._cancelled:
                self.finished.emit(True, msg)
        except Exception as e:
            self.finished.emit(False, str(e))

class RomDownloader(QThread):
    progress = Signal(float, float, float) # downloaded, total, speed
    finished = Signal(bool, str)
    cancelled = Signal()

    def __init__(self, client, rom_id, file_name, target_path):
        super().__init__()
        self.client = client
        self.rom_id = rom_id
        self.file_name = file_name
        self.target_path = target_path
        self.file_path = target_path
        self._cancelled = False

    def cancel(self):
        self._cancelled = True

    def run(self):
        self._last_time = time.time()
        self._last_bytes = 0
        
        def cb(d, t, s):
            if not self._cancelled:
                now = time.time()
                elapsed = now - self._last_time
                if elapsed >= 0.5:
                    speed = (d - self._last_bytes) / elapsed
                    self._last_bytes = d
                    self._last_time = now
                    self.progress.emit(float(d), float(t), float(speed))
                else:
                    self.progress.emit(float(d), float(t), 0.0)
        
        success = self.client.download_rom(self.rom_id, self.file_name, self.target_path, cb, thread=self)
        if self._cancelled:
            self.cancelled.emit()
        else:
            self.finished.emit(success, self.target_path)

class BiosDownloader(QThread):
    progress = Signal(float, float, float)
    finished = Signal(bool, str)
    cancelled = Signal()

    def __init__(self, client, fw_item, target_path):
        super().__init__()
        self.client = client
        self.fw = fw_item
        self.target_path = target_path
        self.file_path = target_path
        self._cancelled = False

    def cancel(self):
        self._cancelled = True

    def run(self):
        self._last_time = time.time()
        self._last_bytes = 0
        
        def cb(d, t, s):
            if not self._cancelled:
                now = time.time()
                elapsed = now - self._last_time
                if elapsed >= 0.5:
                    speed = (d - self._last_bytes) / elapsed
                    self._last_bytes = d
                    self._last_time = now
                    self.progress.emit(float(d), float(t), float(speed))
                else:
                    self.progress.emit(float(d), float(t), 0.0)

        success = False
        if self.fw.get('is_rom'):
            success = self.client.download_rom(self.fw['id'], self.fw['file_name'], self.target_path, cb, thread=self)
        else:
            success = self.client.download_firmware(self.fw, self.target_path, cb, thread=self)

        if self._cancelled:
            self.cancelled.emit()
            return

        if success and self.target_path.endswith(('.zip', '.7z')):
            try:
                dest = os.path.dirname(self.target_path)
                if self.target_path.endswith('.zip'):
                    with zipfile.ZipFile(self.target_path, 'r') as z:       
                        z.extractall(dest)
                    try: os.remove(self.target_path)
                    except Exception: pass
                elif self.target_path.endswith('.7z') and HAS_PY7ZR:        
                    with py7zr.SevenZipFile(self.target_path, mode='r') as z:
                        z.extractall(path=dest)
                    try: os.remove(self.target_path)
                    except Exception: pass
            except Exception:
                pass
        self.finished.emit(success, self.target_path)

class UpdaterThread(QThread):
    finished = Signal(bool, str, str)
    def __init__(self, current_version):
        super().__init__()
        self.current_version = current_version
    def run(self):
        try:
            api_url = "https://api.github.com/repos/abduznik/Wingosy-Launcher/releases/latest"
            headers = {'User-Agent': 'Mozilla/5.0'}
            verify = os.environ.get('REQUESTS_CA_BUNDLE', True)
            resp = requests.get(api_url, headers=headers, timeout=10, verify=verify).json()
            latest_version = resp.get("tag_name", "").replace("v", "")      
            if latest_version and latest_version != self.current_version:   
                download_url = ""
                for asset in resp.get("assets", []):
                    if asset["name"].lower().endswith(".exe"):
                        download_url = asset["browser_download_url"]        
                        break
                self.finished.emit(True, latest_version, download_url)      
            else:
                self.finished.emit(False, latest_version, "")
        except Exception:
            self.finished.emit(False, "", "")

class SelfUpdateThread(QThread):
    progress = Signal(int)
    finished = Signal(bool, str)

    def __init__(self, download_url, current_exe_path):
        super().__init__()
        self.download_url = download_url
        self.current_exe_path = current_exe_path

    def run(self):
        temp_exe = self.current_exe_path.parent / "Wingosy_update.exe"      
        try:
            verify = os.environ.get('REQUESTS_CA_BUNDLE', True)
            r = requests.get(self.download_url, stream=True, timeout=60, verify=verify)
            r.raise_for_status()
            total = int(r.headers.get('content-length', 0))
            downloaded = 0
            with open(temp_exe, 'wb') as f:
                for chunk in r.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)
                        downloaded += len(chunk)
                        if total > 0:
                            self.progress.emit(int((downloaded / total) * 100))

            old_exe = self.current_exe_path.parent / "Wingosy_old.exe"      
            if old_exe.exists(): old_exe.unlink()
            os.rename(self.current_exe_path, old_exe)
            os.rename(temp_exe, self.current_exe_path)
            self.finished.emit(True, "Update downloaded successfully.")     
        except Exception as e:
            if temp_exe.exists(): temp_exe.unlink()
            self.finished.emit(False, str(e))

class ConnectionTestThread(QThread):
    finished = Signal(bool, str)
    def __init__(self, client):
        super().__init__()
        self.client = client
    def run(self):
        success, msg = self.client.test_connection()
        self.finished.emit(success, msg)

class CoreDownloadThread(QThread):
    progress = Signal(int, float)
    finished = Signal(bool, str)

    def __init__(self, core_name, cores_dir):
        super().__init__()
        self.core_name = core_name
        self.cores_dir = cores_dir

    def run(self):
        temp_zip = self.cores_dir / f"{self.core_name}.zip"
        extract_temp = self.cores_dir / f"temp_{self.core_name}"
        try:
            os.makedirs(self.cores_dir, exist_ok=True)
            url = f"https://buildbot.libretro.com/nightly/windows/x86_64/latest/{self.core_name}.zip"
            verify = os.environ.get('REQUESTS_CA_BUNDLE', True)
            r = requests.get(url, stream=True, timeout=30, verify=verify)   
            r.raise_for_status()
            total = int(r.headers.get('content-length', 0))
            downloaded = 0
            start = time.time()
            with open(temp_zip, 'wb') as f:
                for chunk in r.iter_content(chunk_size=8192):
                    if self.isInterruptionRequested():
                        f.close()
                        if temp_zip.exists(): temp_zip.unlink()
                        self.finished.emit(False, "Download cancelled.")    
                        return
                    if chunk:
                        f.write(chunk)
                        downloaded += len(chunk)
                        elapsed = time.time() - start
                        speed = downloaded / elapsed if elapsed > 0 else 0  
                        self.progress.emit(int((downloaded / total) * 100) if total > 0 else 0, speed)

            with zipfile.ZipFile(temp_zip, 'r') as z:
                z.extractall(extract_temp)

            found_dll = False
            for dll in Path(extract_temp).rglob("*.dll"):
                shutil.move(str(dll), str(self.cores_dir / dll.name))       
                found_dll = True

            if temp_zip.exists(): temp_zip.unlink()
            if extract_temp.exists(): shutil.rmtree(extract_temp, ignore_errors=True)
            if found_dll:
                self.finished.emit(True, str(self.cores_dir / f"{self.core_name}"))
            else:
                self.finished.emit(False, "No DLL found in core archive")   
        except Exception as e:
            if temp_zip.exists(): temp_zip.unlink()
            if extract_temp.exists(): shutil.rmtree(extract_temp, ignore_errors=True)
            self.finished.emit(False, str(e))

class ConflictResolveThread(QThread):
    finished = Signal(bool)
    def __init__(self, watcher, rom_id, title, local_path, is_folder):      
        super().__init__()
        self.watcher, self.rom_id, self.title, self.local_path, self.is_folder = watcher, rom_id, title, local_path, is_folder
    def run(self):
        try:
            self.watcher.pull_server_save(self.rom_id, self.title, self.local_path, self.is_folder, force=True)
            self.finished.emit(True)
        except Exception:
            self.finished.emit(False)

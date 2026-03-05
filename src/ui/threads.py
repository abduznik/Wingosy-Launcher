import sys
import os
import requests
import zipfile
import shutil
import subprocess
import time
from pathlib import Path
from PySide6.QtCore import QThread, Signal
from PySide6.QtGui import QPixmap, QImage

# Try to import py7zr for extraction
try:
    import py7zr
    HAS_PY7ZR = True
except ImportError:
    HAS_PY7ZR = False

class ImageFetcher(QThread):
    finished = Signal(int, QPixmap)
    def __init__(self, game_id, url):
        super().__init__()
        self.game_id = game_id
        self.url = url
    def run(self):
        try:
            r = requests.get(self.url, timeout=15)
            if r.status_code == 200:
                img = QImage()
                if img.loadFromData(r.content):
                    self.finished.emit(self.game_id, QPixmap.fromImage(img))
        except Exception:
            pass

class BaseDownloader(QThread):
    progress = Signal(int, float)
    finished = Signal(bool, str)
    
    def __init__(self):
        super().__init__()

    def perform_download(self, url, target_dir):
        try:
            name = url.split('/')[-1].split('?')[0]
            target_path = os.path.join(target_dir, name)
            headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'}
            r = requests.get(url, stream=True, timeout=30, headers=headers)
            r.raise_for_status()
            
            total = int(r.headers.get('content-length', 0))
            downloaded = 0
            start = time.time()
            with open(target_path, 'wb') as f:
                for chunk in r.iter_content(1024*1024):
                    if self.isInterruptionRequested():
                        f.close()
                        try: os.remove(target_path)
                        except Exception: pass
                        return False, "Cancelled"
                    if chunk:
                        f.write(chunk)
                        downloaded += len(chunk)
                        elapsed = time.time() - start
                        speed = downloaded / elapsed if elapsed > 0 else 0
                        self.progress.emit(int((downloaded / total) * 100) if total > 0 else 0, speed)
            
            return self.extract_archive(target_path, target_dir)
        except Exception as e:
            return False, str(e)

    def extract_archive(self, file_path, dest_dir):
        try:
            if file_path.endswith('.zip'):
                with zipfile.ZipFile(file_path, 'r') as z:
                    z.extractall(dest_dir)
                try: os.remove(file_path)
                except Exception: pass
                return True, dest_dir
            elif file_path.endswith('.7z'):
                extracted = False
                if HAS_PY7ZR:
                    try:
                        with py7zr.SevenZipFile(file_path, mode='r') as z:
                            z.extractall(path=dest_dir)
                        extracted = True
                    except Exception: pass
                
                if not extracted:
                    try:
                        subprocess.run(['tar', '-xf', file_path, '-C', dest_dir], check=True)
                        extracted = True
                    except Exception: pass
                
                if extracted:
                    try: os.remove(file_path)
                    except Exception: pass
                    return True, dest_dir
                else:
                    return True, file_path + " (Download complete, but extraction failed. Please extract manually.)"
            return True, file_path
        except Exception as e:
            return True, file_path + f" (Extraction failed: {e})"

class DirectDownloader(BaseDownloader):
    def __init__(self, url, target_dir):
        super().__init__()
        self.url = url
        self.target_dir = target_dir
    def run(self):
        ok, msg = self.perform_download(self.url, self.target_dir)
        self.finished.emit(ok, msg)

class DolphinDownloader(BaseDownloader):
    def __init__(self, target_dir):
        super().__init__()
        self.target_dir = target_dir
    def run(self):
        try:
            api_url = "https://dolphin-emu.org/download/list/master/1/?format=json"
            headers = {'User-Agent': 'Mozilla/5.0'}
            resp = requests.get(api_url, timeout=15, headers=headers)
            if resp.status_code != 200:
                download_url = "https://dl.dolphin-emu.org/releases/2512/dolphin-2512-x64.7z"
            else:
                data = resp.json()
                download_url = data['builds'][0]['artifacts']['win-x64']['url']
            
            ok, msg = self.perform_download(download_url, self.target_dir)
            self.finished.emit(ok, msg)
        except Exception:
            download_url = "https://dl.dolphin-emu.org/releases/2512/dolphin-2512-x64.7z"
            ok, msg = self.perform_download(download_url, self.target_dir)
            self.finished.emit(ok, msg)

class GithubDownloader(BaseDownloader):
    def __init__(self, repo, target_dir):
        super().__init__()
        self.repo = repo
        self.target_dir = target_dir
    def run(self):
        try:
            api_url = f"https://api.github.com/repos/{self.repo}/releases/latest"
            headers = {'User-Agent': 'WingosyLauncher'}
            resp_obj = requests.get(api_url, timeout=15, headers=headers)
            if resp_obj.status_code != 200:
                self.finished.emit(False, f"Repo {self.repo} not found.")
                return
                
            resp = resp_obj.json()
            asset = None
            keywords = ['win', 'x64', 'windows', 'amd64', 'qt', 'msvc', 'desktop']
            extensions = ['.zip', '.7z']
            
            for a in resp.get('assets', []):
                name = a['name'].lower()
                if any(k in name for k in keywords) and any(name.endswith(ext) for ext in extensions):
                    if not name.endswith('-symbols.7z') and 'installer' not in name:
                        asset = a
                        break
            
            if not asset:
                for a in resp.get('assets', []):
                    if any(k in a['name'].lower() for k in keywords) and a['name'].endswith(('.zip', '.7z')):
                        asset = a
                        break

            if not asset:
                for a in resp.get('assets', []):
                    if any(k in a['name'].lower() for k in keywords) and a['name'].endswith('.exe'):
                        asset = a
                        break
            
            if not asset:
                self.finished.emit(False, "No suitable release file found.")
                return
            
            ok, msg = self.perform_download(asset['browser_download_url'], self.target_dir)
            self.finished.emit(ok, msg)
        except Exception as e:
            self.finished.emit(False, str(e))

class RomDownloader(QThread):
    progress = Signal(int, float)
    finished = Signal(bool, str)
    def __init__(self, client, rom_id, file_name, target_path):
        super().__init__()
        self.client = client
        self.rom_id = rom_id
        self.file_name = file_name
        self.target_path = target_path
    def run(self):
        def cb(d, t, s):
            self.progress.emit(int((d / t) * 100) if t > 0 else 0, s)
        success = self.client.download_rom(self.rom_id, self.file_name, self.target_path, cb, thread=self)
        self.finished.emit(success, self.target_path)

class BiosDownloader(QThread):
    progress = Signal(int, float)
    finished = Signal(bool, str)
    def __init__(self, client, fw_item, target_path):
        super().__init__()
        self.client = client
        self.fw = fw_item
        self.target_path = target_path
    def run(self):
        def cb(d, t, s):
            self.progress.emit(int((d / t) * 100) if t > 0 else 0, s)
        
        success = False
        if self.fw.get('is_rom'):
            success = self.client.download_rom(self.fw['id'], self.fw['file_name'], self.target_path, cb, thread=self)
        else:
            success = self.client.download_firmware(self.fw, self.target_path, cb, thread=self)
        
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
    finished = Signal(bool, str, str) # update_available, latest_version, download_url
    def __init__(self, current_version):
        super().__init__()
        self.current_version = current_version
    def run(self):
        try:
            api_url = "https://api.github.com/repos/abduznik/Wingosy-Launcher/releases/latest"
            headers = {'User-Agent': 'Mozilla/5.0'}
            resp = requests.get(api_url, headers=headers, timeout=10).json()
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
            r = requests.get(self.download_url, stream=True, timeout=60)
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
            
            # Backup current exe
            old_exe = self.current_exe_path.parent / "Wingosy_old.exe"
            if old_exe.exists():
                old_exe.unlink()
            
            os.rename(self.current_exe_path, old_exe)
            os.rename(temp_exe, self.current_exe_path)
            
            self.finished.emit(True, "Update downloaded successfully.")
        except Exception as e:
            if temp_exe.exists():
                temp_exe.unlink()
            self.finished.emit(False, str(e))

class ConnectionTestThread(QThread):
    finished = Signal(bool, str)
    def __init__(self, client):
        super().__init__()
        self.client = client
    def run(self):
        success, msg = self.client.test_connection()
        self.finished.emit(success, msg)

RETROARCH_BUILDBOT = "https://buildbot.libretro.com/nightly/windows/x86_64/latest/"

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
            url = f"{RETROARCH_BUILDBOT}{self.core_name}.zip"
            
            r = requests.get(url, stream=True, timeout=30)
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
            
            # Extract
            with zipfile.ZipFile(temp_zip, 'r') as z:
                z.extractall(extract_temp)
            
            # Find and move DLLs
            found_dll = False
            for dll in Path(extract_temp).rglob("*.dll"):
                shutil.move(str(dll), str(self.cores_dir / dll.name))
                found_dll = True
            
            # Cleanup
            if temp_zip.exists(): temp_zip.unlink()
            if extract_temp.exists(): shutil.rmtree(extract_temp)
            
            if found_dll:
                self.finished.emit(True, str(self.cores_dir / f"{self.core_name}"))
            else:
                self.finished.emit(False, "No DLL found in core archive")
                
        except Exception as e:
            if temp_zip.exists(): temp_zip.unlink()
            if extract_temp.exists(): shutil.rmtree(extract_temp)
            self.finished.emit(False, str(e))

class ConflictResolveThread(QThread):
    finished = Signal(bool)
    
    def __init__(self, watcher, rom_id, title, local_path, is_folder):
        super().__init__()
        self.watcher = watcher
        self.rom_id = rom_id
        self.title = title
        self.local_path = local_path
        self.is_folder = is_folder
    
    def run(self):
        try:
            self.watcher.pull_server_save(
                self.rom_id, self.title, self.local_path, self.is_folder, force=True
            )
            self.finished.emit(True)
        except Exception:
            self.finished.emit(False)

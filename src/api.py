import os
import time
from pathlib import Path
from urllib.parse import quote

import requests

class RomMClient:
    def __init__(self, host, config=None):
        self.host = host.rstrip('/')
        self.config = config
        self.token = None
        self.user_games = []
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
        }

    def test_connection(self):
        try:
            # Try heartbeat first, then root api
            for endpoint in ["/api/heartbeat", "/api"]:
                try:
                    r = requests.get(f"{self.host}{endpoint}", timeout=5)
                    if r.status_code == 200:
                        return True, "Successfully connected to RomM."
                except: continue
            return False, "Could not reach RomM API."
        except Exception as e:
            return False, str(e)

    def login(self, username, password):
        try:
            url = f"{self.host}/api/token"
            if self.host.startswith("http://"):
                print("[API] Warning: Credentials being sent over unencrypted HTTP connection.")
            
            scope = "me.read me.write platforms.read roms.read assets.read assets.write roms.user.read roms.user.write collections.read collections.write"
            data = {
                "grant_type": "password",
                "username": username,
                "password": password,
                "scope": scope
            }
            r = requests.post(url, data=data, headers=self.headers, timeout=10)
            if r.status_code == 200:
                self.token = r.json()["access_token"]
                return True, self.token
            return False, r.json().get("detail", "Login failed")
        except Exception as e:
            return False, str(e)

    def get_auth_headers(self):
        h = self.headers.copy()
        if self.token:
            h["Authorization"] = f"Bearer {self.token}"
        return h

    def fetch_library(self):
        try:
            url = f"{self.host}/api/roms"
            # Match original working version params
            params = {"page": 1, "page_size": 5000, "size": 1000}
            r = requests.get(url, headers=self.get_auth_headers(), params=params, timeout=15)
            if r.status_code == 200:
                self.user_games = r.json().get("items", [])
                return self.user_games
            elif r.status_code == 401:
                return "REAUTH_REQUIRED"
            print(f"[API] Error fetching library ({r.status_code})")
            return []
        except Exception as e:
            print(f"[API] Exception fetching library: {e}")
            return []

    def get_cover_url(self, game):
        """Returns a valid URL for the game cover, preferring local RomM assets."""
        path = game.get('path_cover_large') or game.get('path_cover_small') 
        if path:
            return path if path.startswith('http') else f"{self.host}{path}"
        url = game.get('url_cover')
        if url:
            if url.startswith('//'):
                return f"https:{url}"
            return url
        # Fallback to direct ID path if all else fails
        return f"{self.host}/api/raw/covers/{game['id']}"

    def download_rom(self, rom_id, file_name, target_path, progress_cb=None, thread=None):
        try:
            # Reverting to the URL structure from the working version
            from urllib.parse import quote
            encoded_name = quote(file_name)
            url = f"{self.host}/api/roms/{rom_id}/content/{encoded_name}"
            
            r = requests.get(url, headers=self.get_auth_headers(), stream=True, timeout=60)
            if r.status_code == 404:
                # Fallback to /download path ONLY if 404
                url = f"{self.host}/api/roms/{rom_id}/download"
                r = requests.get(url, headers=self.get_auth_headers(), stream=True, timeout=60)

            if r.status_code != 200:
                return False

            total = int(r.headers.get('content-length', 0))
            downloaded = 0
            start = time.time()
            with open(target_path, 'wb') as f:
                for chunk in r.iter_content(1024*1024):
                    if thread and thread.isInterruptionRequested():
                        f.close()
                        os.remove(target_path)
                        return False
                    if chunk:
                        f.write(chunk)
                        downloaded += len(chunk)
                        if progress_cb and total > 0:
                            elapsed = time.time() - start
                            speed = downloaded / elapsed if elapsed > 0 else 0
                            progress_cb(downloaded, total, speed)
            return True
        except Exception as e:
            print(f"[API] ROM download error: {e}")
            return False

    def get_latest_save(self, rom_id):
        try:
            # Trying both /api/roms/{id}/saves and /api/saves
            url = f"{self.host}/api/roms/{rom_id}/saves"
            r = requests.get(url, headers=self.get_auth_headers(), timeout=10)
            
            if r.status_code != 200:
                url = f"{self.host}/api/saves"
                r = requests.get(url, headers=self.get_auth_headers(), params={"rom_id": rom_id}, timeout=10)

            if r.status_code == 200:
                data = r.json()
                items = data if isinstance(data, list) else data.get("items", [])
                if items:
                    # Sort by ID descending (newest first)
                    items.sort(key=lambda x: x.get('id', 0), reverse=True)
                    return items[0]
            return None
        except Exception as e:
            print(f"[API] Error getting latest save: {e}")
            return None

    def download_save(self, save_item, target_path, thread=None):
        try:
            path = save_item.get('download_path') or save_item.get('path')
            url = path if path.startswith('http') else f"{self.host}{path}"
            r = requests.get(url, headers=self.get_auth_headers(), stream=True, timeout=30)
            if r.status_code == 200:
                with open(target_path, 'wb') as f:
                    for chunk in r.iter_content(chunk_size=8192):
                        if thread and thread.isInterruptionRequested():
                            f.close()
                            os.remove(target_path)
                            return False
                        if chunk:
                            f.write(chunk)
                return True
            return False
        except Exception as e:
            print(f"[API] Error downloading save: {e}")
            return False

    def upload_save(self, rom_id, emulator, file_path):
        try:
            url = f"{self.host}/api/saves"
            params = {"rom_id": rom_id, "emulator": emulator, "slot": "wingosy-windows"}
            
            with open(file_path, 'rb') as f:
                files = {'saveFile': (os.path.basename(file_path), f, 'application/octet-stream')}
                r = requests.post(url, params=params, headers=self.get_auth_headers(), files=files, timeout=60)
                return r.status_code in [200, 201], r.text
        except Exception as e:
            return False, str(e)

    def get_firmware(self):
        try:
            url = f"{self.host}/api/platforms"
            r = requests.get(url, headers=self.get_auth_headers(), timeout=15)
            if r.status_code == 200:
                platforms = r.json()
                firmware_list = []
                for p in platforms:
                    fws = p.get('firmware', [])
                    for f in fws:
                        f['platform_name'] = p.get('name')
                        f['platform_slug'] = p.get('slug')
                        f['platform_id'] = p.get('id')
                        firmware_list.append(f)
                return firmware_list
            return []
        except Exception as e:
            print(f"[API] Error getting firmware: {e}")
            return []

    def download_firmware(self, fw_item, target_path, progress_cb=None, thread=None):
        try:
            path = fw_item.get('download_path')
            if not path:
                slug = fw_item.get('platform_slug', 'unknown')
                name = fw_item.get('file_name')
                path = f"/api/raw/assets/firmware/{slug}/{name}"

            url = path if path.startswith('http') else f"{self.host}{path}"
            r = requests.get(url, headers=self.get_auth_headers(), stream=True, timeout=60)
            total = int(r.headers.get('content-length', 0))
            downloaded = 0
            start = time.time()
            with open(target_path, 'wb') as f:
                for chunk in r.iter_content(1024*1024):
                    if thread and thread.isInterruptionRequested():
                        f.close()
                        os.remove(target_path)
                        return False
                    if chunk:
                        f.write(chunk)
                        downloaded += len(chunk)
                        if progress_cb:
                            elapsed = time.time() - start
                            speed = downloaded / elapsed if elapsed > 0 else 0
                            progress_cb(downloaded, total, speed)
            return True
        except Exception as e:
            print(f"[API] Error downloading firmware: {e}")
            return False

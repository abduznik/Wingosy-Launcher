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
        self.library_cache_path = Path.home() / ".wingosy" / "library_cache.json"

    def save_library_cache(self, games):
        """Save fetched library to disk for instant startup next time."""
        try:
            self.library_cache_path.parent.mkdir(parents=True, exist_ok=True)
            cache_data = {
                "timestamp": __import__("time").time(),
                "games": games
            }
            with open(self.library_cache_path, 'w', encoding='utf-8') as f:
                import json
                json.dump(cache_data, f)
        except Exception as e:
            print(f"[Cache] Save error: {e}")

    def load_library_cache(self):
        """Load cached library. Returns (games, age_seconds) or (None, 0)."""
        try:
            if not self.library_cache_path.exists():
                return None, 0
            import json, time
            with open(self.library_cache_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            age = time.time() - data.get("timestamp", 0)
            return data.get("games", []), age
        except Exception:
            return None, 0

    def test_connection(self):
        try:
            # Try heartbeat first, then root api
            for endpoint in ["/api/heartbeat", "/api"]:
                try:
                    r = requests.get(f"{self.host}{endpoint}", timeout=5)
                    if r.status_code == 200:
                        return True, "Successfully connected to RomM."
                except (requests.exceptions.ConnectTimeout,
                        requests.exceptions.ConnectionError,
                        requests.exceptions.Timeout,
                        requests.exceptions.RequestException):
                    continue
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
            try:
                r = requests.post(url, data=data, headers=self.headers, timeout=10)
            except (requests.exceptions.ConnectTimeout,
                    requests.exceptions.ConnectionError,
                    requests.exceptions.Timeout,
                    requests.exceptions.RequestException) as e:
                print(f"[API] Network error in login: {e}")
                return False, f"Could not reach server: {e}"

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
        url = f"{self.host}/api/roms"
        all_items = []
        limit = 50
        offset = 0
        total = None

        while True:
            params = {"limit": limit, "offset": offset}
            try:
                r = requests.get(url, headers=self.get_auth_headers(),
                                params=params, timeout=30)
            except (requests.exceptions.ConnectTimeout,
                    requests.exceptions.ConnectionError,
                    requests.exceptions.Timeout,
                    requests.exceptions.RequestException) as e:
                print(f"[API] Network error in fetch_library: {e}")
                return []

            if r.status_code == 401:
                return "REAUTH_REQUIRED"
            if r.status_code != 200:
                break

            data = r.json()
            items = (data.get("items", []) if isinstance(data, dict)
                     else data if isinstance(data, list) else [])

            if total is None:
                total = (data.get("total") or data.get("count") or 0
                         if isinstance(data, dict) else 0)

            if not items:
                break

            all_items.extend(items)

            if total and len(all_items) >= total:
                break

            offset += limit

        print(f"[Library] Fetched {len(all_items)} games "
              f"in {offset // limit + 1} page(s)")
        self.user_games = all_items
        self.save_library_cache(all_items)
        if self.config:
            self.config.set("cached_library", all_items)
        return all_items

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
            
            try:
                r = requests.get(url, headers=self.get_auth_headers(), stream=True, timeout=60)
                if r.status_code == 404:
                    # Fallback to /download path ONLY if 404
                    url = f"{self.host}/api/roms/{rom_id}/download"
                    r = requests.get(url, headers=self.get_auth_headers(), stream=True, timeout=60)
            except (requests.exceptions.ConnectTimeout,
                    requests.exceptions.ConnectionError,
                    requests.exceptions.Timeout,
                    requests.exceptions.RequestException) as e:
                print(f"[API] Network error in download_rom: {e}")
                return False

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
            r = requests.get(
                f"{self.host}/api/saves",
                params={"rom_id": rom_id},
                headers=self.get_auth_headers(),
                timeout=10
            )
            if r.status_code != 200:
                return None
            items = r.json()
            if not isinstance(items, list):
                items = items.get("items", [])
            if not items:
                return None
            return sorted(items,
                key=lambda x: x.get("updated_at", ""),
                reverse=True)[0]
        except Exception as e:
            print(f"[API] get_latest_save error: {e}")
            return None

    def get_latest_state(self, rom_id):
        try:
            r = requests.get(
                f"{self.host}/api/states",
                params={"rom_id": rom_id},
                headers=self.get_auth_headers(),
                timeout=10
            )
            if r.status_code != 200:
                return None
            items = r.json()
            if not isinstance(items, list):
                items = items.get("items", [])
            if not items:
                return None
            return sorted(items,
                key=lambda x: x.get("updated_at", ""),
                reverse=True)[0]
        except Exception as e:
            print(f"[API] get_latest_state error: {e}")
            return None

    def download_save(self, save_item, target_path, thread=None):
        try:
            path = save_item.get('download_path') or save_item.get('path')
            url = path if path.startswith('http') else f"{self.host}{path}"
            try:
                r = requests.get(url, headers=self.get_auth_headers(), stream=True, timeout=30)
            except (requests.exceptions.ConnectTimeout,
                    requests.exceptions.ConnectionError,
                    requests.exceptions.Timeout,
                    requests.exceptions.RequestException) as e:
                print(f"[API] Network error in download_save: {e}")
                return False

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

    def download_state(self, state_obj, dest_path):
        try:
            dl_path = state_obj.get('download_path') or \
                      state_obj.get('file_path') or \
                      f"/api/states/{state_obj['id']}/download"
            url = dl_path if dl_path.startswith('http') \
                  else f"{self.host}{dl_path}"
            r = requests.get(url, headers=self.get_auth_headers(),
                           stream=True, timeout=60)
            with open(dest_path, 'wb') as f:
                for chunk in r.iter_content(65536):
                    if chunk: f.write(chunk)
            return True
        except Exception as e:
            print(f"[API] download_state error: {e}")
            return False

    def upload_save(self, rom_id, emulator, file_path, slot="wingosy-windows", raw=False):
        try:
            url = f"{self.host}/api/saves"
            params = {"rom_id": rom_id, "emulator": emulator, "slot": slot}
            filename = os.path.basename(file_path)
            
            with open(file_path, 'rb') as f:
                files = {'saveFile': (filename, f, 'application/octet-stream')}
                try:
                    r = requests.post(url, params=params, headers=self.get_auth_headers(), files=files, timeout=60)
                except (requests.exceptions.ConnectTimeout,
                        requests.exceptions.ConnectionError,
                        requests.exceptions.Timeout,
                        requests.exceptions.RequestException) as e:
                    print(f"[API] Network error in upload_save: {e}")
                    return False, str(e)
                print(f"[API] upload_save -> {r.status_code}: {r.text[:200]}")
                return r.status_code in [200, 201], r.text
        except Exception as e:
            print(f"[API] upload_save error: {e}")
            return False, str(e)

    def upload_state(self, rom_id, emulator, file_path,
                     slot="wingosy-state"):
        try:
            from pathlib import Path
            filename = Path(file_path).name
            
            # Strip .auto suffix — RomM wants .state not .state.auto
            if filename.endswith('.auto'):
                filename = filename[:-5]
            
            # Strip RomM timestamp brackets if somehow present
            import re
            filename = re.sub(
                r'\s*\[[^\]]*\d{4}-\d{2}-\d{2}[^\]]*\]', '', filename)
            
            url = f"{self.host}/api/states"
            params = {
                "rom_id": rom_id,
                "emulator": emulator,
            }
            
            with open(file_path, 'rb') as f:
                files = {'stateFile': (filename, f,
                                       'application/octet-stream')}
                r = requests.post(
                    url,
                    params=params,
                    headers=self.get_auth_headers(),
                    files=files,
                    timeout=60
                )
                print(f"[API] upload_state -> {r.status_code}: "
                      f"{r.text[:300]}")
                return r.status_code in [200, 201], r.text
        except Exception as e:
            print(f"[API] upload_state error: {e}")
            return False, str(e)

    def get_firmware(self):
        try:
            url = f"{self.host}/api/platforms"
            try:
                r = requests.get(url, headers=self.get_auth_headers(), timeout=15)
            except (requests.exceptions.ConnectTimeout,
                    requests.exceptions.ConnectionError,
                    requests.exceptions.Timeout,
                    requests.exceptions.RequestException) as e:
                print(f"[API] Network error in get_firmware: {e}")
                return []

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
            try:
                r = requests.get(url, headers=self.get_auth_headers(), stream=True, timeout=60)
            except (requests.exceptions.ConnectTimeout,
                    requests.exceptions.ConnectionError,
                    requests.exceptions.Timeout,
                    requests.exceptions.RequestException) as e:
                print(f"[API] Network error in download_firmware: {e}")
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
                        if progress_cb:
                            elapsed = time.time() - start
                            speed = downloaded / elapsed if elapsed > 0 else 0
                            progress_cb(downloaded, total, speed)
            return True
        except Exception as e:
            print(f"[API] Error downloading firmware: {e}")
            return False

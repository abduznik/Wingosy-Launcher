import os
import time
import sys
import json
from pathlib import Path
from urllib.parse import quote

import requests
import logging

try:
    import keyring
except ImportError:
    keyring = None

def _get_certifi_path():
    """Get certifi CA bundle path, handling PyInstaller."""
    # Check env var first (set by main.py before imports)
    env_path = os.environ.get('REQUESTS_CA_BUNDLE')
    if env_path and os.path.exists(env_path):
        return env_path
    try:
        import certifi
        path = certifi.where()
        os.environ['REQUESTS_CA_BUNDLE'] = path
        os.environ['SSL_CERT_FILE'] = path
        return path
    except Exception:
        return True  # Let requests find it automatically

CERTIFI_PATH = _get_certifi_path()
REQUEST_TIMEOUT = (10, 30) # (connect, read)

class RomMClient:
    def __init__(self, host, config=None):
        self.host = host.rstrip('/')
        self.config = config
        self.token = self._load_token()
        self.user_games = []
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
        }
        self.library_cache_path = Path.home() / ".wingosy" / "library_cache.json"

    def _load_token(self):
        """Retrieve token via config manager (keyring with encrypted fallback)."""
        if self.config:
            return self.config.load_token()
        
        # Fallback for when config is not available (rare)
        if keyring:
            try:
                return keyring.get_password("wingosy", "auth_token")
            except Exception as e:
                logging.warning(f"Keyring retrieval error: {e}")
        return None

    def logout(self):
        """Clear the auth token from memory and secure storage."""
        self.token = None
        if self.config:
            self.config.delete_token()
        elif keyring:
            try:
                keyring.delete_password("wingosy", "auth_token")
                logging.info("Logged out: removed token from keyring")
            except Exception as e:
                logging.warning(f"Failed to remove token from keyring: {e}")

    def save_library_cache(self, games):
        """Save fetched library to disk for instant startup next time."""
        try:
            self.library_cache_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.library_cache_path, 'w', encoding='utf-8') as f:
                json.dump(games, f)
        except Exception as e:
            print(f"[Cache] Save error: {e}")

    def load_library_cache(self):
        """Load cached library. Returns (games, age_seconds) or (None, 0)."""
        try:
            if not self.library_cache_path.exists():
                return None, 0
            with open(self.library_cache_path, 'r', encoding='utf-8') as f:
                games = json.load(f)
            # We no longer track age in the simplified list format, return 0
            return games, 0
        except Exception:
            return None, 0

    def test_connection(self, host_override=None, retry_callback=None):
        host = (host_override or self.host).rstrip('/')
        try:
            # Try heartbeat first, then roms list as a connectivity test
            for endpoint in ["/api/heartbeat", "/api/roms?limit=1&offset=0"]:
                try:
                    # Stage 1: Fast attempt
                    try:
                        r = requests.get(f"{host}{endpoint}", 
                                         headers=self.get_auth_headers(),
                                         timeout=REQUEST_TIMEOUT, 
                                         verify=CERTIFI_PATH)
                    except requests.exceptions.Timeout:
                        # Stage 2: Slow attempt for cold starts
                        if retry_callback:
                            retry_callback()
                        r = requests.get(f"{host}{endpoint}", 
                                         headers=self.get_auth_headers(),
                                         timeout=(300, 300), 
                                         verify=CERTIFI_PATH)

                    if r.status_code == 200:
                        return True, "Connected successfully."
                    if r.status_code in [401, 403]:
                        return False, "Connected but authentication failed. Check credentials."
                except (requests.exceptions.ConnectTimeout,
                        requests.exceptions.ConnectionError):
                    return False, "Could not reach host. Check URL and port."
                except requests.exceptions.ReadTimeout:
                    return False, "Server took too long to respond. It might be overloaded."
                except Exception:
                    continue
            return False, "Could not reach RomM API. Check your URL."
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
                # Login usually shouldn't be cold-started but we'll use standard timeout
                r = requests.post(url, data=data, headers=self.headers, 
                                  timeout=REQUEST_TIMEOUT, verify=CERTIFI_PATH)
            except requests.exceptions.Timeout:
                # If login hangs, retry once with longer timeout
                r = requests.post(url, data=data, headers=self.headers, 
                                  timeout=(60, 60), verify=CERTIFI_PATH)
            except (requests.exceptions.ConnectTimeout,
                    requests.exceptions.ConnectionError,
                    requests.exceptions.Timeout,
                    requests.exceptions.RequestException) as e:
                print(f"[API] Network error in login: {e}")
                return False, f"Could not reach server: {e}"

            if r.status_code == 200:
                self.token = r.json()["access_token"]
                
                # Save via config manager (keyring with encrypted fallback)
                if self.config:
                    self.config.save_token(self.token)
                elif keyring:
                    try:
                        keyring.set_password("wingosy", "auth_token", self.token)
                    except Exception as e:
                        logging.warning(f"Failed to save token to keyring: {e}")
                
                return True, self.token
            return False, r.json().get("detail", "Login failed")
        except Exception as e:
            return False, str(e)

    def get_auth_headers(self):
        h = self.headers.copy()
        if self.token:
            h["Authorization"] = f"Bearer {self.token}"
        return h

    def fetch_library(self, retry_callback=None, page_callback=None):
        """
        Fetch all games from RomM in parallel for speed.
        Emits pages progressively via page_callback if provided.
        """
        import concurrent.futures
        url = f"{self.host}/api/roms"
        limit = 100 
        all_items = []
        
        # Use a session for connection pooling
        session = requests.Session()
        adapter = requests.adapters.HTTPAdapter(pool_connections=10, pool_maxsize=10)
        session.mount("http://", adapter)
        session.mount("https://", adapter)

        def _fetch_page(offset, retry=True):
            params = {"limit": limit, "offset": offset}
            try:
                try:
                    # Stage 1: Fast attempt
                    r = session.get(url, headers=self.get_auth_headers(),
                                    params=params, timeout=REQUEST_TIMEOUT, verify=CERTIFI_PATH)
                except requests.exceptions.Timeout:
                    # Stage 2: Slow attempt
                    if retry_callback:
                        retry_callback()
                    r = session.get(url, headers=self.get_auth_headers(),
                                    params=params, timeout=(300, 300), verify=CERTIFI_PATH)
                
                if r.status_code == 401:
                    return "REAUTH_REQUIRED"
                if r.status_code != 200:
                    return None
                
                data = r.json()
                items = (data.get("items", []) if isinstance(data, dict)
                         else data if isinstance(data, list) else [])
                total = (data.get("total") or data.get("count") or 0
                         if isinstance(data, dict) else len(items))
                return {"items": items, "total": total}
            except Exception as e:
                if retry:
                    print(f"[API] Retry page offset {offset} due to error: {e}")
                    return _fetch_page(offset, retry=False)
                print(f"[API] Network error at offset {offset}: {e}")
                return None

        first_page = _fetch_page(0)
        if first_page is None:
            return None
        if first_page == "REAUTH_REQUIRED":
            return "REAUTH_REQUIRED"
        
        items = first_page["items"]
        total = first_page["total"]
        all_items.extend(items)
        if page_callback:
            page_callback(items, total)

        if total > limit:
            remaining_offsets = list(range(limit, total, limit))
            print(f"[Library] Parallel fetch started for {len(remaining_offsets)} remaining pages...")
            
            with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
                future_to_offset = {executor.submit(_fetch_page, offset): offset for offset in remaining_offsets}
                for future in concurrent.futures.as_completed(future_to_offset):
                    page_res = future.result()
                    if page_res and isinstance(page_res, dict):
                        page_items = page_res["items"]
                        all_items.extend(page_items)
                        if page_callback:
                            page_callback(page_items, total)

        # Aggregate and cache
        self.user_games = all_items
        self.save_library_cache(all_items)
        
        # We no longer save cached_library to config.json explicitly here
        # self.config.set("cached_library", all_items) is removed to avoid UI stutter
        
        print(f"[Library] Parallel fetch complete: {len(all_items)} games.")
        return all_items

    def get_rom_details(self, rom_id):
        """Fetch detailed information for a single ROM."""
        url = f"{self.host}/api/roms/{rom_id}"
        try:
            r = requests.get(url, headers=self.get_auth_headers(), 
                             timeout=REQUEST_TIMEOUT, verify=CERTIFI_PATH)
            if r.status_code == 200:
                rom_data = r.json()
                logging.debug(f"ROM detail raw for {rom_id}: {json.dumps(rom_data, indent=2)}")
                return rom_data
            return None
        except Exception as e:
            print(f"[API] Error fetching ROM details for {rom_id}: {e}")
            return None

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
            encoded_name = quote(file_name)
            url = f"{self.host}/api/roms/{rom_id}/content/{encoded_name}"
            
            try:
                r = requests.get(url, headers=self.get_auth_headers(), stream=True, 
                                 timeout=REQUEST_TIMEOUT, verify=CERTIFI_PATH)
                if r.status_code == 404:
                    # Fallback to /download path ONLY if 404
                    url = f"{self.host}/api/roms/{rom_id}/download"
                    r = requests.get(url, headers=self.get_auth_headers(), stream=True, 
                                     timeout=REQUEST_TIMEOUT, verify=CERTIFI_PATH)
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
        items = self.list_all_saves(rom_id)
        if not items: return None
        return sorted(items, key=lambda x: x.get("updated_at", ""), reverse=True)[0]

    def list_all_saves(self, rom_id):
        try:
            r = requests.get(
                f"{self.host}/api/saves",
                params={"rom_id": rom_id},
                headers=self.get_auth_headers(),
                timeout=REQUEST_TIMEOUT,
                verify=CERTIFI_PATH
            )
            if r.status_code != 200: return []
            items = r.json()
            return items if isinstance(items, list) else items.get("items", [])
        except Exception as e:
            print(f"[API] list_all_saves error: {e}")
            return []

    def delete_save(self, save_id):
        try:
            url = f"{self.host}/api/saves/{save_id}"
            r = requests.delete(url, headers=self.get_auth_headers(), 
                                timeout=REQUEST_TIMEOUT, verify=CERTIFI_PATH)
            return r.status_code in [200, 204]
        except Exception as e:
            print(f"[API] delete_save error: {e}")
            return False

    def get_latest_state(self, rom_id):
        items = self.list_all_states(rom_id)
        if not items: return None
        return sorted(items, key=lambda x: x.get("updated_at", ""), reverse=True)[0]

    def list_all_states(self, rom_id):
        try:
            r = requests.get(
                f"{self.host}/api/states",
                params={"rom_id": rom_id},
                headers=self.get_auth_headers(),
                timeout=REQUEST_TIMEOUT,
                verify=CERTIFI_PATH
            )
            if r.status_code != 200: return []
            items = r.json()
            return items if isinstance(items, list) else items.get("items", [])
        except Exception as e:
            print(f"[API] list_all_states error: {e}")
            return []

    def delete_state(self, state_id):
        try:
            url = f"{self.host}/api/states/{state_id}"
            r = requests.delete(url, headers=self.get_auth_headers(), 
                                timeout=REQUEST_TIMEOUT, verify=CERTIFI_PATH)
            return r.status_code in [200, 204]
        except Exception as e:
            print(f"[API] delete_state error: {e}")
            return False

    def download_save(self, save_item, target_path, thread=None):
        try:
            path = save_item.get('download_path') or save_item.get('path')
            url = path if path.startswith('http') else f"{self.host}{path}"
            try:
                r = requests.get(url, headers=self.get_auth_headers(), stream=True, 
                                 timeout=REQUEST_TIMEOUT, verify=CERTIFI_PATH)
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
                           stream=True, timeout=60, verify=CERTIFI_PATH)
            with open(dest_path, 'wb') as f:
                for chunk in r.iter_content(65536):
                    if chunk: f.write(chunk)
            return True
        except Exception as e:
            print(f"[API] download_state error: {e}")
            return False

    def upload_save(self, rom_id, emulator, file_obj, slot="wingosy-windows", raw=False, filename_override=None):
        try:
            url = f"{self.host}/api/saves"
            params = {"rom_id": rom_id, "emulator": emulator, "slot": slot}
            
            # file_obj can be a path string or a file-like object
            if isinstance(file_obj, str):
                f = open(file_obj, 'rb')
                close_after = True
                filename = filename_override or os.path.basename(file_obj)
            else:
                f = file_obj
                close_after = False
                filename = filename_override or "save.zip"
            
            # Strip .auto suffix 
            if filename.endswith('.auto'):
                filename = filename[:-5]
            
            try:
                files = {'saveFile': (filename, f, 'application/octet-stream')}
                r = requests.post(url, params=params, headers=self.get_auth_headers(),
                                  files=files, timeout=(10, 120), verify=CERTIFI_PATH)
                print(f"[API] upload_save -> {r.status_code}: {r.text[:200]}")
                return r.status_code in [200, 201], r.text
            finally:
                if close_after: f.close()
        except Exception as e:
            print(f"[API] upload_save error: {e}")
            return False, str(e)

    def upload_state(self, rom_id, emulator, file_obj, slot="wingosy-state", filename_override=None):
        try:
            from pathlib import Path
            
            if isinstance(file_obj, str):
                f = open(file_obj, 'rb')
                close_after = True
                filename = filename_override or Path(file_obj).name
            else:
                f = file_obj
                close_after = False
                filename = filename_override or "state.state"
            
            # Strip .auto suffix 
            if filename.endswith('.auto'):
                filename = filename[:-5]
            
            # Strip RomM timestamp brackets 
            import re
            filename = re.sub(
                r'\s*\[[^\]]*\d{4}-\d{2}-\d{2}[^\]]*\]', '', filename)
            
            url = f"{self.host}/api/states"
            params = {
                "rom_id": rom_id,
                "emulator": emulator,
                "slot": slot
            }
            
            try:
                files = {'stateFile': (filename, f, 'application/octet-stream')}
                r = requests.post(url, params=params, headers=self.get_auth_headers(),
                                  files=files, timeout=(10, 120), verify=CERTIFI_PATH)
                print(f"[API] upload_state -> {r.status_code}: {r.text[:300]}")
                return r.status_code in [200, 201], r.text
            finally:
                if close_after: f.close()
        except Exception as e:
            print(f"[API] upload_state error: {e}")
            return False, str(e)

    def get_firmware(self):
        try:
            url = f"{self.host}/api/platforms"
            try:
                r = requests.get(url, headers=self.get_auth_headers(), 
                                 timeout=REQUEST_TIMEOUT, verify=CERTIFI_PATH)
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
                r = requests.get(url, headers=self.get_auth_headers(), stream=True, 
                                 timeout=60, verify=CERTIFI_PATH)
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

"""
DummyRomMClient — a fake RomMClient for testing and demo mode.
Generates up to 5000 fake games covering every platform slug in 
src/platforms.py so pagination, platform filtering, and emulator 
matching can all be stress-tested without a real RomM server.
"""
import random
import string
import time
from src.platforms import RETROARCH_PLATFORMS

# All known platform slugs — includes dedicated emulator platforms too
ALL_PLATFORM_SLUGS = RETROARCH_PLATFORMS + [
    "switch", "nintendo-switch",
    "ps2", "playstation-2",
    "ps3", "playstation-3",
    "gc", "ngc", "wii", "nintendo-wii",
    "wiiu", "wii-u",
    "n3ds", "3ds", "nintendo-3ds",
    "xbox", "microsoft-xbox",
    "xbox360", "xbox-360",
    "ps4", "playstation-4",
    "pc", "windows",
]

PLATFORM_DISPLAY_NAMES = {
    "switch": "Nintendo Switch",
    "nintendo-switch": "Nintendo Switch",
    "ps2": "PlayStation 2",
    "playstation-2": "PlayStation 2",
    "ps3": "PlayStation 3",
    "playstation-3": "PlayStation 3",
    "gc": "GameCube",
    "ngc": "GameCube",
    "wii": "Wii",
    "nintendo-wii": "Wii",
    "wiiu": "Wii U",
    "wii-u": "Wii U",
    "n3ds": "Nintendo 3DS",
    "3ds": "Nintendo 3DS",
    "nintendo-3ds": "Nintendo 3DS",
    "nes": "Nintendo Entertainment System",
    "nintendo-entertainment-system": "NES",
    "snes": "Super Nintendo",
    "n64": "Nintendo 64",
    "gba": "Game Boy Advance",
    "gbc": "Game Boy Color",
    "gb": "Game Boy",
    "nds": "Nintendo DS",
    "psx": "PlayStation",
    "ps1": "PlayStation",
    "playstation": "PlayStation",
    "psp": "PlayStation Portable",
    "genesis": "Sega Genesis",
    "megadrive": "Sega Mega Drive",
    "segacd": "Sega CD",
    "sega-cd": "Sega CD",
    "saturn": "Sega Saturn",
    "dreamcast": "Dreamcast",
    "gamegear": "Game Gear",
    "mastersystem": "Sega Master System",
    "32x": "Sega 32X",
    "arcade": "Arcade",
    "neogeo": "Neo Geo",
    "pcengine": "PC Engine",
    "atari2600": "Atari 2600",
    "atari7800": "Atari 7800",
    "lynx": "Atari Lynx",
    "jaguar": "Atari Jaguar",
    "xbox": "Xbox",
    "xbox360": "Xbox 360",
    "ps4": "PlayStation 4",
    "3do": "3DO",
    "wonderswan": "WonderSwan",
    "msx": "MSX",
    "c64": "Commodore 64",
    "dos": "DOS",
    "amiga": "Amiga",
}

ROM_EXTENSIONS = {
    "switch": ".nsp", "nintendo-switch": ".nsp",
    "ps2": ".iso", "playstation-2": ".iso",
    "ps3": ".iso", "playstation-3": ".iso",
    "gc": ".rvz", "ngc": ".rvz",
    "wii": ".rvz", "nintendo-wii": ".rvz",
    "wiiu": ".wua", "wii-u": ".wua",
    "n3ds": ".3ds", "3ds": ".3ds", "nintendo-3ds": ".3ds",
    "nes": ".nes", "snes": ".sfc", "n64": ".z64",
    "gba": ".gba", "gbc": ".gbc", "gb": ".gb",
    "nds": ".nds", "psx": ".bin", "ps1": ".bin",
    "psp": ".iso", "genesis": ".md", "megadrive": ".md",
    "segacd": ".bin", "saturn": ".bin", "dreamcast": ".cdi",
    "gamegear": ".gg", "mastersystem": ".sms", "32x": ".32x",
    "arcade": ".zip", "atari2600": ".a26", "atari7800": ".a78",
    "lynx": ".lnx", "jaguar": ".j64", "3do": ".iso",
    "wonderswan": ".ws", "msx": ".rom", "c64": ".d64",
    "dos": ".exe", "amiga": ".adf",
}

FAKE_GAME_NAMES = [
    "Super Adventure Quest", "Mega Blast Force", "Dragon Warriors",
    "Cosmic Defender", "Shadow Strike", "Legend of the Ancients",
    "Turbo Racing Championship", "Mystery Island", "Space Pirates",
    "Battle Arena", "Crystal Chronicles", "Dark Realms",
    "Epic Journey", "Final Countdown", "Galaxy Warriors",
    "Hero's Path", "Iron Fortress", "Jungle Expedition",
    "Kingdom Hearts Faker", "Lost Temple", "Mech Warriors",
    "Night Stalker", "Ocean Adventure", "Power Surge",
    "Quest for Glory", "Rapid Fire", "Steel City",
    "Thunder Strike", "Ultimate Challenge", "Vortex",
    "Warrior's Code", "Xenon Force", "Yellow Submarine",
    "Zero Hour", "Alien Invasion", "Bio Hazard",
    "Cyber Punk City", "Death Race", "Electric Dreams",
    "Fury Road", "Ghost Recon Fake", "Hyper Drive",
]

_next_id = 1000

def _random_string(length=8):
    return ''.join(random.choices(string.ascii_lowercase, k=length))

def generate_fake_games(count=5000):
    """Generate count fake game entries covering all platform slugs."""
    global _next_id
    games = []
    slugs = ALL_PLATFORM_SLUGS
    
    for i in range(count):
        slug = slugs[i % len(slugs)]
        ext = ROM_EXTENSIONS.get(slug, ".bin")
        base_name = random.choice(FAKE_GAME_NAMES)
        # Add suffix to make names unique
        name = f"{base_name} {_random_string(4).upper()}"
        fs_name = f"{name}{ext}".replace(" ", "_").replace(":", "")
        
        games.append({
            "id": _next_id,
            "name": name,
            "fs_name": fs_name,
            "platform_slug": slug,
            "platform_display_name": PLATFORM_DISPLAY_NAMES.get(slug, slug.upper()),
            "path_cover_large": None,
            "path_cover_small": None,
            "url_cover": None,
            "files": [{"file_name": fs_name}],
            "updated_at": "2025-01-01T00:00:00",
        })
        _next_id += 1
    
    return games


class DummyRomMClient:
    """
    Drop-in replacement for RomMClient that returns fake data.
    All method signatures match src/api.py exactly.
    Set game_count to control library size for stress testing.
    """
    def __init__(self, host="http://dummy", config=None, game_count=None):
        self.host = host
        self.config = config
        self.GAME_COUNT = game_count if game_count is not None else 5000
        self.token = "dummy-token"
        self.user_games = []
        print(f"[DummyClient] Initialized with {self.GAME_COUNT} fake games")

    def test_connection(self):
        return True, "Dummy connection OK"

    def login(self, username, password):
        self.token = "dummy-token"
        return True, self.token

    def logout(self):
        self.token = None

    def get_auth_headers(self):
        return {"Authorization": "Bearer dummy-token"}

    def fetch_library(self):
        """Simulate paginated fetch with slight delay to test async loading."""
        print(f"[DummyClient] Generating {self.GAME_COUNT} fake games...")
        time.sleep(0.5)  # simulate network delay
        self.user_games = generate_fake_games(self.GAME_COUNT)
        print(f"[DummyClient] Library ready: {len(self.user_games)} games")
        return self.user_games

    def save_library_cache(self, games):
        pass

    def load_library_cache(self):
        return None, 0

    def fetch_library_page(self, limit=50, offset=0):
        """
        Simulate a single paginated RomM API response.
        Returns dict matching real RomM API shape:
        {"items": [...], "total": N}
        Used by tests to verify pagination logic.
        """
        if not self.user_games:
            self.user_games = generate_fake_games(self.GAME_COUNT)
        page_items = self.user_games[offset:offset + limit]
        return {
            "items": page_items,
            "total": len(self.user_games)
        }

    def get_cover_url(self, game):
        return None  # no covers in dummy mode

    def download_rom(self, rom_id, file_name, target_path,
                     progress_cb=None, thread=None):
        print(f"[DummyClient] Fake ROM download: {file_name}")
        time.sleep(1)
        return True

    def get_latest_save(self, rom_id):
        return None  # no cloud saves in dummy mode

    def get_latest_state(self, rom_id):
        return None

    def get_save_by_slot(self, rom_id, slot):
        return None

    def get_state_by_slot(self, rom_id, slot):
        return None

    def download_save(self, save_item, target_path, thread=None):
        return True

    def download_state(self, state_obj, dest_path):
        return True

    def upload_save(self, rom_id, emulator, file_path, 

                    slot="wingosy-windows", raw=False):
        print(f"[DummyClient] Fake save upload for rom_id={rom_id} (raw={raw})")
        return True, "dummy upload ok"

    def upload_state(self, rom_id, emulator, file_path,
                     slot="wingosy-state"):
        print(f"[DummyClient] Fake state upload for rom_id={rom_id}")
        return True, "dummy upload ok"

    def get_firmware(self):
        return []

    def get_rom_details(self, rom_id):
        return {
            "id": rom_id,
            "name": f"Dummy Game {rom_id}",
            "platform_display_name": "SNES",
            "igdb_metadata": {"summary": "A long and detailed dummy summary for this game."},
            "files": [{"file_name": "game.sfc", "file_size_bytes": 1024*1024}]
        }

    def download_firmware(self, fw_item, target_path,
                          progress_cb=None, thread=None):
        return False

    def update_playtime(self, rom_id, seconds):
        print(f"[DummyClient] Updated playtime for rom_id={rom_id}: {seconds}s")
        return True

    def list_all_saves(self, rom_id):
        return []

    def list_all_states(self, rom_id):
        return []

    def delete_save(self, save_id):
        return True

    def delete_state(self, state_id):
        return True

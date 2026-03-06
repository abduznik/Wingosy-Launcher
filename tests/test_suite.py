"""
Wingosy Test Suite
Run with: pytest tests/ -v
Run with logs: pytest tests/ -v -s
"""
import pytest
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.platforms import (RETROARCH_PLATFORMS, RETROARCH_CORES,
                            platform_matches)
from src.config import ConfigManager
from tests.dummy import (DummyRomMClient, generate_fake_games,
                          ALL_PLATFORM_SLUGS)
from src.utils import read_retroarch_cfg, write_retroarch_cfg_values


# ── Imports ──────────────────────────────────────────────────────────────

class TestImports:
    def test_api_imports(self):
        from src.api import RomMClient
        assert RomMClient

    def test_config_imports(self):
        from src.config import ConfigManager
        assert ConfigManager

    def test_watcher_imports(self):
        from src.watcher import WingosyWatcher
        assert WingosyWatcher

    def test_platforms_imports(self):
        from src.platforms import (RETROARCH_PLATFORMS, RETROARCH_CORES,
                                   platform_matches)
        assert RETROARCH_PLATFORMS
        assert RETROARCH_CORES
        assert callable(platform_matches)

    def test_utils_imports(self):
        from src.utils import zip_path, calculate_file_hash
        assert callable(zip_path)
        assert callable(calculate_file_hash)


# ── Platforms ─────────────────────────────────────────────────────────────

class TestPlatforms:
    def test_no_duplicate_slugs_in_retroarch_platforms(self):
        dupes = [s for s in RETROARCH_PLATFORMS
                 if RETROARCH_PLATFORMS.count(s) > 1]
        assert dupes == [], f"Duplicate slugs found: {set(dupes)}"

    def test_all_retroarch_cores_have_dll_extension(self):
        for slug, dll in RETROARCH_CORES.items():
            assert dll.endswith("_libretro.dll"), (
                f"Core for {slug} doesn't end with _libretro.dll: {dll}")

    def test_every_core_slug_is_in_platforms_list(self):
        missing = [s for s in RETROARCH_CORES
                   if s not in RETROARCH_PLATFORMS]
        assert missing == [], (
            f"Slugs in RETROARCH_CORES but not RETROARCH_PLATFORMS: {missing}")

    def test_platform_matches_basic(self):
        emu = {"platform_slug": "gc",
               "platform_slugs": ["gc", "ngc", "wii", "gamecube"]}
        assert platform_matches("gc", emu)
        assert platform_matches("ngc", emu)
        assert platform_matches("wii", emu)
        assert not platform_matches("ps2", emu)
        assert not platform_matches(None, emu)
        assert not platform_matches("", emu)

    def test_platform_matches_fallback_to_single_slug(self):
        emu = {"platform_slug": "ps2"}
        assert platform_matches("ps2", emu)
        assert not platform_matches("ps3", emu)

    def test_key_platforms_covered(self):
        """Ensure the platforms users actually reported missing are covered."""
        required = ["nes", "wii", "wiiu", "n3ds", "segacd", "sega-cd",
                    "xbox", "genesis", "snes", "gba", "psx", "dreamcast"]
        all_known = set(RETROARCH_PLATFORMS + ALL_PLATFORM_SLUGS)
        missing = [p for p in required if p not in all_known]
        assert missing == [], f"Required platforms missing: {missing}"


# ── Config ────────────────────────────────────────────────────────────────

class TestConfig:
    def setup_method(self):
        # Force a fresh default config for testing
        self.config = ConfigManager()
        self.config.data = self.config.DEFAULT_CONFIG.copy()

    def test_all_emulators_have_exe(self):
        for name, data in self.config.get("emulators").items():
            assert "exe" in data, f"Emulator {name} missing 'exe'"
            assert data["exe"].endswith(".exe"), (
                f"Emulator {name} exe doesn't end in .exe: {data['exe']}")

    def test_all_emulators_have_platform_slug(self):
        for name, data in self.config.get("emulators").items():
            assert "platform_slug" in data, (
                f"Emulator {name} missing 'platform_slug'")

    def test_all_emulators_have_platform_slugs_list(self):
        for name, data in self.config.get("emulators").items():
            assert "platform_slugs" in data, (
                f"Emulator {name} missing 'platform_slugs' list — "
                f"add it to DEFAULT_CONFIG in config.py")

    def test_all_emulators_have_folder(self):
        for name, data in self.config.get("emulators").items():
            assert "folder" in data, f"Emulator {name} missing 'folder'"

    def test_default_paths_are_empty_strings(self):
        """Emulator paths should be empty by default, not hardcoded."""
        for name, data in self.config.get("emulators").items():
            assert data.get("path") == "", (
                f"Emulator {name} has non-empty default path: "
                f"{data.get('path')} — paths should default to ''")

    def test_host_has_no_trailing_slash(self):
        host = self.config.get("host", "")
        assert not host.endswith("/"), f"Host has trailing slash: {host}"

    def test_required_top_level_keys(self):
        required = ["host", "username", "emulators", "base_rom_path",
                    "base_emu_path", "auto_pull_saves"]
        for key in required:
            assert self.config.get(key) is not None, (
                f"Config missing required key: {key}")


# ── Dummy Client ──────────────────────────────────────────────────────────

class TestDummyClient:
    def setup_method(self):
        # Initialize with specific count for testing
        self.client = DummyRomMClient(game_count=100)

    def test_fetch_library_returns_list(self):
        result = self.client.fetch_library()
        assert isinstance(result, list)

    def test_fetch_library_returns_correct_count(self):
        result = self.client.fetch_library()
        assert len(result) == 100

    def test_game_has_required_fields(self):
        games = self.client.fetch_library()
        required_fields = ["id", "name", "fs_name", "platform_slug",
                           "platform_display_name", "files"]
        for field in required_fields:
            assert field in games[0], f"Game missing field: {field}"

    def test_all_platform_slugs_represented(self):
        """5000 games should cover every platform slug at least once."""
        DummyRomMClient.GAME_COUNT = 5000
        client = DummyRomMClient()
        games = client.fetch_library()
        found_slugs = set(g["platform_slug"] for g in games)
        missing = [s for s in ALL_PLATFORM_SLUGS if s not in found_slugs]
        assert missing == [], f"Platform slugs not in generated games: {missing}"

    def test_stress_5000_games(self):
        """5000 games should generate without error or memory issues."""
        DummyRomMClient.GAME_COUNT = 5000
        client = DummyRomMClient()
        games = client.fetch_library()
        assert len(games) == 5000

    def test_login_always_succeeds(self):
        ok, token = self.client.login("any", "any")
        assert ok is True
        assert token is not None

    def test_get_latest_save_returns_none(self):
        assert self.client.get_latest_save(123) is None

    def test_upload_save_returns_success(self):
        ok, msg = self.client.upload_save(123, "TestEmu", "fake_path.zip")
        assert ok is True

    def test_pagination_matches_romm_api_shape(self):
        """Verify dummy pagination response matches real RomM API shape."""
        DummyRomMClient.GAME_COUNT = 200
        client = DummyRomMClient()
        client.user_games = generate_fake_games(200)

        # Page 1
        page1 = client.fetch_library_page(limit=50, offset=0)
        assert "items" in page1, "Response missing 'items' key"
        assert "total" in page1, "Response missing 'total' key"
        assert len(page1["items"]) == 50
        assert page1["total"] == 200

        # Page 2
        page2 = client.fetch_library_page(limit=50, offset=50)
        assert len(page2["items"]) == 50

        # Last page
        page4 = client.fetch_library_page(limit=50, offset=150)
        assert len(page4["items"]) == 50

        # Beyond end
        page5 = client.fetch_library_page(limit=50, offset=200)
        assert len(page5["items"]) == 0

        # Items are different across pages
        page1_ids = set(g["id"] for g in page1["items"])
        page2_ids = set(g["id"] for g in page2["items"])
        assert page1_ids.isdisjoint(page2_ids), (
            "Pages contain duplicate games — pagination is broken")

    def test_offset_pagination_fetches_all_games(self):
        """
        Simulate what api.py fetch_library does with offset pagination.
        Verify the loop correctly fetches all games across all pages.
        """
        DummyRomMClient.GAME_COUNT = 153  # odd number to test partial last page
        client = DummyRomMClient()
        client.user_games = generate_fake_games(153)

        # Simulate the api.py fetch loop
        all_items = []
        limit = 50
        offset = 0
        total = None

        while True:
            response = client.fetch_library_page(limit=limit, offset=offset)
            items = response.get("items", [])
            if total is None:
                total = response.get("total", 0)
            if not items:
                break
            all_items.extend(items)
            if total and len(all_items) >= total:
                break
            offset += limit

        assert len(all_items) == 153, (
            f"Expected 153 games, got {len(all_items)} — "
            f"pagination loop is broken")
        
        # Verify no duplicates
        all_ids = [g["id"] for g in all_items]
        assert len(all_ids) == len(set(all_ids)), (
            "Duplicate games in paginated result")


# ── Watcher Save Path Logic ───────────────────────────────────────────────

class TestSavePathResolution:
    """
    These tests verify that resolve_save_path returns something (not None)
    for every supported emulator when the save file/folder exists.
    We mock the filesystem using tmp_path so no real files are needed.
    """

    def setup_method(self):
        DummyRomMClient.GAME_COUNT = 10
        client = DummyRomMClient()
        config = ConfigManager()
        from src.watcher import WingosyWatcher
        # Create watcher without starting the thread
        self.watcher = WingosyWatcher.__new__(WingosyWatcher)
        self.watcher.client = client
        self.watcher.config = config
        import signal
        from pathlib import Path
        from PySide6.QtCore import Signal
        # Minimal signal stub
        class FakeSignal:
            def emit(self, *a): pass
            def connect(self, *a): pass
        self.watcher.log_signal = FakeSignal()

    def test_ps2_save_path_returns_something(self, tmp_path):
        """PS2 should always return a path even if file doesn't exist."""
        result = self.watcher.resolve_save_path(
            "PlayStation 2", "Test Game",
            f'"C:/emus/pcsx2.exe" "C:/roms/test.iso"',
            "C:/emus/pcsx2.exe", "ps2"
        )
        assert result is not None, "PS2 save path returned None"

    def test_gamecube_save_path_returns_something(self, tmp_path):
        """GC should return a path (memory card) even on first launch."""
        result = self.watcher.resolve_save_path(
            "GameCube / Wii", "Test Game",
            f'"C:/emus/Dolphin.exe" "C:/roms/test.rvz"',
            "C:/emus/Dolphin.exe", "gc"
        )
        assert result is not None, "GameCube save path returned None"

    def test_retroarch_save_path_returns_something(self):
        """RetroArch should always return a .srm path."""
        result = self.watcher.resolve_save_path(
            "Multi-Console (RetroArch)", "Super Mario World",
            '"C:/emus/retroarch.exe" "C:/roms/smw.sfc"',
            "C:/emus/retroarch.exe", "snes"
        )
        assert result is not None, "RetroArch save path returned None"
        assert str(result).endswith(".srm"), (
            f"RetroArch save path should be .srm, got: {result}")


# ── API Contract ──────────────────────────────────────────────────────────

class TestAPIContract:
    """
    Verify that DummyRomMClient and RomMClient have the same public methods
    so the dummy is always a valid drop-in replacement.
    """
    def test_dummy_has_all_real_client_methods(self):
        from src.api import RomMClient
        real_methods = {m for m in dir(RomMClient)
                       if not m.startswith("_")}
        dummy_methods = {m for m in dir(DummyRomMClient)
                        if not m.startswith("_")}
        missing = real_methods - dummy_methods
        assert missing == set(), (
            f"DummyRomMClient is missing methods from RomMClient: {missing}\n"
            f"Add these to tests/dummy.py to keep the dummy in sync.")

class TestRetroArchCfg:
    def test_read_retroarch_cfg_parses_values(self, tmp_path):
        cfg = tmp_path / "retroarch.cfg"
        cfg.write_text(
            'savestate_auto_save = "false"\n'
            'savestate_auto_load = "true"\n'
            'video_fullscreen = "false"\n',
            encoding='utf-8'
        )
        result = read_retroarch_cfg(str(cfg))
        assert result["savestate_auto_save"] == "false"
        assert result["savestate_auto_load"] == "true"
        assert result["video_fullscreen"] == "false"

    def test_read_retroarch_cfg_missing_file(self, tmp_path):
        result = read_retroarch_cfg(str(tmp_path / "missing.cfg"))
        assert result == {}

    def test_write_retroarch_cfg_updates_existing_key(self, tmp_path):
        cfg = tmp_path / "retroarch.cfg"
        cfg.write_text('savestate_auto_save = "false"\n'
                       'video_fullscreen = "false"\n',
                       encoding='utf-8')
        ok = write_retroarch_cfg_values(str(cfg), 
            {"savestate_auto_save": "true"})
        assert ok is True
        result = read_retroarch_cfg(str(cfg))
        assert result["savestate_auto_save"] == "true"
        assert result["video_fullscreen"] == "false"  # unchanged

    def test_write_retroarch_cfg_appends_new_key(self, tmp_path):
        cfg = tmp_path / "retroarch.cfg"
        cfg.write_text('video_fullscreen = "false"\n', encoding='utf-8')
        write_retroarch_cfg_values(str(cfg),
            {"savestate_auto_save": "true"})
        result = read_retroarch_cfg(str(cfg))
        assert result["savestate_auto_save"] == "true"
        assert result["video_fullscreen"] == "false"

    def test_retroarch_save_path_snes(self):
        """SRM path resolves correctly for SNES game."""
        from src.platforms import RETROARCH_CORES
        from src.watcher import WingosyWatcher
        # Minimal fake emu_data
        emu_data = {"path": "F:/EMULATORS/retroarch/"
                            "RetroArch-Win64/retroarch.exe"}
        game = {"fs_name": "SuperMarioWorld.sfc",
                "platform_slug": "snes"}
        w = WingosyWatcher.__new__(WingosyWatcher)
        path, is_folder = w.get_retroarch_save_path(game, emu_data)
        assert path is not None
        assert "Snes9x" in path or "snes" in path.lower()
        assert path.endswith(".srm")
        assert is_folder is False

    def test_retroarch_save_path_psp(self):
        """PSP save resolves to SAVEDATA folder."""
        emu_data = {"path": "F:/EMULATORS/retroarch/"
                            "RetroArch-Win64/retroarch.exe"}
        game = {"fs_name": "Persona3.iso",
                "platform_slug": "psp"}
        from src.watcher import WingosyWatcher
        w = WingosyWatcher.__new__(WingosyWatcher)
        path, is_folder = w.get_retroarch_save_path(game, emu_data)
        assert path is not None
        assert "PPSSPP" in path
        assert "SAVEDATA" in path
        assert is_folder is True

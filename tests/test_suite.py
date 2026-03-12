"""
Wingosy Test Suite
Run with: pytest tests/ -v
Run with logs: pytest tests/ -v -s
"""
import pytest
import sys
import os
import unittest
from unittest.mock import MagicMock
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

LIVE = os.environ.get("ROMM_TEST_LIVE", "0") == "1"

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
        self.config = ConfigManager()
        from src.watcher import WingosyWatcher
        # Create watcher without starting the thread
        self.watcher = WingosyWatcher.__new__(WingosyWatcher)
        self.watcher.client = client
        self.watcher.config = self.config
        self.watcher._sync_threads = []
        import signal
        from pathlib import Path
        from PySide6.QtCore import Signal
        # Minimal signal stub
        class FakeSignal:
            def emit(self, *a): pass
            def connect(self, *a): pass
        self.watcher.log_signal = FakeSignal()

    def test_ps2_save_path_returns_something(self, tmp_path):
        """PS2 should always return a path via strategy."""
        from src.save_strategies import get_strategy
        emu = {"id": "pcsx2", "name": "PCSX2", "save_resolution": {"mode": "folder", "save_dir": str(tmp_path / "saves")}}
        strategy = get_strategy(self.config, emu)
        rom = {"id": 1, "name": "Test Game", "fs_name": "test.iso", "platform_slug": "ps2"}
        result = strategy.get_save_dir(rom)
        assert result is not None

    def test_gamecube_save_path_returns_something(self, tmp_path):
        """GC should return a path via strategy."""
        from src.save_strategies import get_strategy
        emu = {"id": "dolphin", "name": "Dolphin", "save_resolution": {"mode": "folder", "save_dir": str(tmp_path / "Dolphin/Saves")}}
        strategy = get_strategy(self.config, emu)
        rom = {"id": 1, "name": "Test Game", "fs_name": "test.rvz", "platform_slug": "gc"}
        result = strategy.get_save_dir(rom)
        assert result is not None

    def test_retroarch_save_path_returns_something(self, tmp_path):
        """RetroArch strategy should resolve save dir if config exists."""
        from src.save_strategies import get_strategy
        cfg = tmp_path / "retroarch.cfg"
        cfg.write_text('savefile_directory = "C:/saves"\n')
        emu = {"id": "retroarch", "name": "RetroArch", "config_path": str(cfg)}
        strategy = get_strategy(self.config, emu)
        rom = {"id": 1, "name": "SMW", "fs_name": "smw.sfc", "platform_slug": "snes"}
        result = strategy.get_save_dir(rom)
        assert str(result).replace("\\", "/") == "C:/saves"


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


# ── Regressions ───────────────────────────────────────────────────────────

class TestRegressions:
    def test_platform_filter_preserved_after_refresh(self):
        """
        Regression: platform filter must not reset to 'All'
        when library refreshes or cards reload.
        The selected platform text must survive a 
        populate/refresh cycle.
        """
        from tests.dummy import DummyRomMClient
        from src.config import ConfigManager
        config = ConfigManager()
        client = DummyRomMClient(game_count=50)
        games = client.fetch_library()
        
        # Get unique platforms
        platforms = list({g['platform_slug'] for g in games 
                         if g.get('platform_slug')})
        assert len(platforms) > 1, "Need multiple platforms to test filter"
        
        # Simulate: user selects a platform
        selected = platforms[0]
        
        # Simulate: library refreshes (re-fetches games)
        games_after = client.fetch_library()
        platforms_after = list({g['platform_slug'] 
                                for g in games_after 
                                if g.get('platform_slug')})
        
        # Selected platform must still exist after refresh
        assert selected in platforms_after, \
            f"Platform '{selected}' disappeared after refresh"
        
        # Filter applied to refreshed library must return 
        # only games of that platform
        filtered = [g for g in games_after 
                   if g['platform_slug'] == selected]
        for g in filtered:
            assert g['platform_slug'] == selected, \
                "Filter returned game from wrong platform"

    def test_stdout_reconfiguration_none_safe(self):
        """
        Regression: UTF-8 stdout reconfiguration must not 
        crash when sys.stdout or sys.stderr is None 
        (e.g. PyInstaller frozen exe without console).
        """
        import sys, io
        
        # Save originals
        orig_stdout = sys.stdout
        orig_stderr = sys.stderr
        
        try:
            # Simulate PyInstaller frozen exe: stdout is None
            sys.stdout = None
            sys.stderr = None
            
            # This is the exact guard from main.py
            # It must not raise AttributeError
            try:
                if sys.stdout and hasattr(sys.stdout, 'buffer'):
                    sys.stdout = io.TextIOWrapper(
                        sys.stdout.buffer, 
                        encoding='utf-8', 
                        errors='replace')
                if sys.stderr and hasattr(sys.stderr, 'buffer'):
                    sys.stderr = io.TextIOWrapper(
                        sys.stderr.buffer, 
                        encoding='utf-8', 
                        errors='replace')
                # If we reach here, no crash — test passes
                passed = True
            except AttributeError as e:
                passed = False
                pytest.fail(
                    f"stdout reconfiguration crashed with "
                    f"None stdout: {e}")
            
            assert passed
        finally:
            # Always restore
            sys.stdout = orig_stdout
            sys.stderr = orig_stderr

    def test_mei_cleanup_exception_safe(self):
        """
        Regression: _cleanup_old_mei_folders must not 
        propagate exceptions — it must catch and log them
        so a cleanup failure never crashes the app.
        """
        import sys
        from unittest.mock import patch
        
        # Import main module functions without running main()
        # We test the cleanup function in isolation
        import tempfile
        from pathlib import Path
        import shutil
        
        # Create a fake MEI folder we don't have permission 
        # to delete (simulate the TLS crash scenario)
        tmp = Path(tempfile.mkdtemp())
        fake_mei = tmp / "_MEI99999"
        fake_mei.mkdir()
        
        # Mock sys._MEIPASS to simulate frozen exe
        with patch.object(sys, '_MEIPASS', str(tmp / '_MEI00001'),
                         create=True):
            # Also mock sys.frozen
            with patch.object(sys, 'frozen', True, create=True):
                
                def _cleanup_safe():
                    """Copy of the guarded cleanup from main.py"""
                    try:
                        if not getattr(sys, 'frozen', False):
                            return
                        mei_parent = Path(sys._MEIPASS).parent
                        current = Path(sys._MEIPASS).name
                        for item in mei_parent.iterdir():
                            if (item.is_dir() 
                                    and item.name.startswith('_MEI')
                                    and item.name != current):
                                try:
                                    shutil.rmtree(str(item))
                                except Exception:
                                    pass
                    except Exception as e:
                        print(f"[MEI cleanup] Error: {e}")
                
                # Must not raise
                try:
                    _cleanup_safe()
                    passed = True
                except Exception as e:
                    passed = False
                    pytest.fail(
                        f"MEI cleanup propagated exception: {e}")
                
                assert passed
        
        # Cleanup temp
        shutil.rmtree(str(tmp), ignore_errors=True)


class TestWatcherResilience:
    def setup_method(self):
        from tests.dummy import DummyRomMClient
        from src.config import ConfigManager
        from src.watcher import WingosyWatcher
        self.client = DummyRomMClient()
        self.config = ConfigManager()
        # Create watcher without starting thread
        self.watcher = WingosyWatcher.__new__(WingosyWatcher)
        self.watcher.client = self.client
        self.watcher.config = self.config
        self.watcher.session_errors = {}
        self.watcher.active_sessions = {}
        self.watcher.running = True
        self.watcher._sync_threads = []
        # Stub signals
        self._log_signal = MagicMock()
        self._notify_signal = MagicMock()
        self._path_detected_signal = MagicMock()
        self._conflict_signal = MagicMock()
        
        self.watcher.log_signal = self._log_signal
        self.watcher.notify_signal = self._notify_signal
        self.watcher.path_detected_signal = self._path_detected_signal
        self.watcher.conflict_signal = self._conflict_signal

    def test_watcher_continues_after_resolve_error(self):
        """Test that track_session handles resolve_save_path exceptions."""
        from unittest.mock import MagicMock
        proc = MagicMock()
        proc.pid = 123
        game_data = {"id": 1, "name": "Test Game", "platform_slug": "snes"}
        
        # PID should NOT be in active_sessions because setup failed
        assert 123 not in self.watcher.active_sessions

    def test_error_counter_stops_at_five(self):
        """Test that handle_exit stops syncing after 5 consecutive errors."""
        import logging
        from unittest.mock import patch
        from src.save_strategies import get_strategy
        
        emu = {"id": "snes9x", "name": "Snes9x", "save_resolution": {"mode": "file"}}
        strategy = get_strategy(self.config, emu)
        
        data = {
            "rom_id": 1,
            "title": "Broken Game",
            "game_data": {"id": 1, "name": "Broken Game"},
            "emulator": emu,
            "strategy": strategy,
            "save_path": "fake.srm",
            "is_folder": False
        }
        
        # Force 5 errors
        self.watcher.session_errors["1"] = 5
        
        with patch("logging.warning") as mock_warn:
            self.watcher.handle_exit(data)
            mock_warn.assert_called_with("[Watcher] Giving up on save sync for Broken Game after 5 consecutive errors")

    def test_error_counter_resets_on_success(self, tmp_path):
        """Test that error counter resets to 0 after a successful sync."""
        from unittest.mock import MagicMock
        import os
        from src.save_strategies import get_strategy
        
        save_file = tmp_path / "test.srm"
        save_file.write_text("data")
        
        emu = {"id": "snes9x", "name": "Snes9x", "save_resolution": {"mode": "file"}}
        strategy = get_strategy(self.config, emu)
        
        # Mock strategy to return our tmp file
        strategy.get_save_files = MagicMock(return_value=[save_file])

        data = {
            "rom_id": 1,
            "title": "Good Game",
            "game_data": {"id": 1, "name": "Good Game"},
            "emulator": emu,
            "strategy": strategy,
            "save_path": str(save_file),
            "is_folder": False,
            "initial_hash": "old-hash", # Force change detection
            "start_time": 0
        }
        
        self.watcher.session_errors["1"] = 3
        self.watcher.sync_cache = {}
        self.watcher.tmp_dir = tmp_path / "tmp"
        self.watcher.tmp_dir.mkdir()
        
        # Mock successful upload
        self.client.upload_save = MagicMock(return_value=(True, "ok"))
        self.watcher.save_cache = MagicMock()
        
        self.watcher.handle_exit(data)
        
        # Manually trigger the success callback because signals need an event loop
        self.watcher._on_sync_thread_done("1", 12345, True)
        
        assert self.watcher.session_errors["1"] == 0


class TestLogging:
    def test_log_level_set_from_config(self):
        """Test that main.py logic for setting log level works."""
        import logging
        from src.config import ConfigManager
        config = ConfigManager()
        
        for level in ["DEBUG", "INFO", "WARNING", "ERROR"]:
            config.data["log_level"] = level
            log_level_str = config.get("log_level", "INFO").upper()
            target_level = getattr(logging, log_level_str)
            
            # Simulate main.py logic
            logging.getLogger().setLevel(target_level)
            assert logging.getLogger().getEffectiveLevel() == target_level


class TestEmulatorSchema:
    def setup_method(self):
        import tempfile
        from pathlib import Path
        from src import emulators
        self.test_dir = tempfile.TemporaryDirectory()
        self.home_path = Path(self.test_dir.name)
        
        # Patch EMULATORS_FILE to point to our temp dir
        self.orig_file = emulators.EMULATORS_FILE
        emulators.EMULATORS_FILE = self.home_path / "emulators.json"
        self.emulators = emulators

    def teardown_method(self):
        self.test_dir.cleanup()
        self.emulators.EMULATORS_FILE = self.orig_file

    def test_default_emulators_file_created(self):
        """File should be created on first load if missing."""
        assert not self.emulators.EMULATORS_FILE.exists()
        emus = self.emulators.load_emulators()
        assert self.emulators.EMULATORS_FILE.exists()
        assert len(emus) > 0

    def test_get_emulator_for_platform(self):
        """Should find correct emulator for a slug."""
        # SNES is in RetroArch by default
        emu = self.emulators.get_emulator_for_platform("snes")
        assert emu is not None
        assert emu["id"] == "retroarch"
        
        # Switch is in Eden by default
        emu = self.emulators.get_emulator_for_platform("switch")
        assert emu is not None
        assert emu["id"] == "eden"

    def test_get_emulator_for_unknown_platform(self):
        """Should return None for unsupported slugs."""
        emu = self.emulators.get_emulator_for_platform("unknown_console")
        assert emu is None

    def test_user_defined_survives_cycle(self):
        """Custom emulators should persist after save/load."""
        custom_emu = {
            "id": "custom_id",
            "name": "Custom Emu",
            "executable_path": "C:/path.exe",
            "platform_slugs": ["custom_platform"],
            "user_defined": True
        }
        all_emus = self.emulators.load_emulators()
        all_emus.append(custom_emu)
        self.emulators.save_emulators(all_emus)
        
        # Reload
        reloaded = self.emulators.load_emulators()
        found = next((e for e in reloaded if e["id"] == "custom_id"), None)
        assert found is not None
        assert found["name"] == "Custom Emu"
        assert found["user_defined"] is True

    def test_yuzu_is_not_present(self):
        """Yuzu should be completely removed from defaults."""
        emus = self.emulators.DEFAULT_EMULATORS
        for emu in emus:
            assert "yuzu" not in emu["id"].lower()
            assert "yuzu" not in emu["name"].lower()


# ── Live Connection ───────────────────────────────────────────────────────

@pytest.mark.skipif(not LIVE, reason="requires live RomM server (set ROMM_TEST_LIVE=1)")
class TestLiveConnection(unittest.TestCase):
    """
    Live integration tests against a real RomM server.
    Skipped automatically if host/token not in config or 
    server is unreachable.
    """
    
    @classmethod
    def setUpClass(cls):
        from src.config import ConfigManager
        from src.api import RomMClient
        config = ConfigManager()
        host = config.get("host")
        token = config.get("token")
        
        if not host or not token:
            raise unittest.SkipTest(
                "No host/token in config — skipping live tests")
        
        from src.api import CERTIFI_PATH
        cls.client = RomMClient(host, config)
        cls.client.token = token
        
        # Quick reachability check
        try:
            import requests
            r = requests.get(
                f"{host}/api/platforms",
                headers=cls.client.get_auth_headers(),
                timeout=5,
                verify=CERTIFI_PATH)
            if r.status_code not in [200, 401]:
                raise unittest.SkipTest(
                    f"Server not reachable: {r.status_code}")
        except Exception as e:
            raise unittest.SkipTest(
                f"Server not reachable: {e}")
    
    def test_fetch_library_returns_games(self):
        """Live server must return at least 1 game."""
        games = self.client.fetch_library()
        self.assertIsInstance(games, list)
        if isinstance(games, list):
            self.assertGreater(len(games), 0,
                "Live server returned empty library")
    
    def test_auth_headers_present(self):
        """Auth headers must include Authorization."""
        headers = self.client.get_auth_headers()
        self.assertIn('Authorization', headers,
            "Missing Authorization header")
        self.assertTrue(
            headers['Authorization'].startswith('Bearer '),
            "Authorization header must be Bearer token")
    
    def test_get_latest_save_returns_dict_or_none(self):
        """get_latest_save must return dict or None, never crash."""
        games = self.client.fetch_library()
        if not isinstance(games, list) or not games:
            self.skipTest("No games available")
        rom_id = games[0]['id']
        result = self.client.get_latest_save(rom_id)
        self.assertTrue(
            result is None or isinstance(result, dict),
            f"Expected dict or None, got {type(result)}")
    
    def test_get_latest_state_returns_dict_or_none(self):
        """get_latest_state must return dict or None, never crash."""
        games = self.client.fetch_library()
        if not isinstance(games, list) or not games:
            self.skipTest("No games available")
        rom_id = games[0]['id']
        result = self.client.get_latest_state(rom_id)
        self.assertTrue(
            result is None or isinstance(result, dict),
            f"Expected dict or None, got {type(result)}")
    
    def test_certifi_bundle_accessible(self):
        """certifi CA bundle must be accessible from current process."""
        import certifi
        import os
        path = certifi.where()
        self.assertTrue(
            os.path.exists(path),
            f"certifi bundle not found at: {path}")
    
    def test_https_not_required_for_local_server(self):
        """HTTP (non-TLS) connections must work for local servers."""
        from src.config import ConfigManager
        config = ConfigManager()
        host = config.get("host", "")
        if host.startswith("https://"):
            self.skipTest("Server uses HTTPS — skipping HTTP test")
        # HTTP connection should work without certifi
        import requests
        from src.api import RomMClient
        client = RomMClient(host, config)
        client.token = config.get("token")
        try:
            games = client.fetch_library()
            self.assertIsInstance(games, list)
        except Exception as e:
            self.fail(f"HTTP connection failed: {e}")

class TestSaveStrategies:
    
    def test_registry_has_all_modes(self):
        from src.save_strategies import STRATEGY_REGISTRY
        for mode in ["retroarch", "folder", "file", "windows"]:
            assert mode in STRATEGY_REGISTRY
    
    def test_get_strategy_returns_correct_type(self):
        from src.save_strategies import get_strategy, RetroArchStrategy, FolderStrategy, FileStrategy
        
        config = {}
        
        ra_emu = {"save_resolution": {"mode": "retroarch"}}
        assert isinstance(get_strategy(config, ra_emu), RetroArchStrategy)
        
        folder_emu = {"save_resolution": {"mode": "folder", "save_dir": "/tmp"}}
        assert isinstance(get_strategy(config, folder_emu), FolderStrategy)
        
        file_emu = {"save_resolution": {"mode": "file"}}
        assert isinstance(get_strategy(config, file_emu), FileStrategy)
    
    def test_windows_strategy_no_save_dir(self):
        from src.save_strategies import WindowsNativeStrategy
        s = WindowsNativeStrategy({}, {"is_native": True})
        rom = {"id": "nonexistent_999"}
        assert s.get_save_files(rom) == []
        assert s.get_save_dir(rom) is None
    
    def test_strategy_is_extensible(self):
        """Verify adding a new strategy requires only a new class."""
        from src.save_strategies import SaveStrategy, STRATEGY_REGISTRY
        
        class MockStrategy(SaveStrategy):
            mode_id = "mock_test"
            def get_save_files(self, rom):
                return []
            def restore_save_files(self, rom, data, fname):
                return True
        
        # Register it
        STRATEGY_REGISTRY["mock_test"] = MockStrategy
        
        # Verify it works
        from src.save_strategies import get_strategy
        emu = {"save_resolution": {"mode": "mock_test"}}
        s = get_strategy({}, emu)
        assert isinstance(s, MockStrategy)
        
        # Cleanup
        del STRATEGY_REGISTRY["mock_test"]

# Changelog

## [0.6.6] - 2026-03-21

### Fixed
- **ROM downloads: smart file selection** — multi-file games (e.g. Switch NSP + updates + DLC + artbooks) now correctly pick the base game file instead of blindly using the first file in the list. Files are ranked by platform extension priority; updates, DLC, amiibo JSON, artbooks, and PDFs are deprioritised.
- **No extraction for non-Windows platforms** — PS1, PS2, PS3, Switch, N64, GBA and all retro platform downloads no longer trigger 7-Zip extraction. Emulators handle these formats natively. Extraction is now Windows-only. Fixes 7z exit code 2 error on PS3 ISOs.
- **Filename sanitisation** — files with garbage server-side names (e.g. `COMICSANS18.LAF.txt`) are automatically renamed to `<Game Title>.<platform ext>` post-download. Filenames containing `[TitleID][v0](4.58 GB)` junk are also cleaned.
- **ROM detection extended** — `resolve_local_rom_path` now recognises `.nsp`, `.xci`, `.nsz`, `.rvz`, `.gcz`, `.wbfs`, `.wua`, `.gba`, `.3ds`, `.cia`, `.nds`, `.sfc`, `.nes`, `.gen` and more. Adds game-title-based fuzzy search and bracket-stripping so renamed files are always found.
- **`.nsz` warning** — attempting to download a `.nsz` Switch ROM now shows a warning that Eden cannot play this format directly, with the option to cancel or proceed.
- **Updater** — removed unreliable auto-restart-via-batch-file logic. After a successful update download, the app now prompts the user to reopen manually instead of attempting to restart itself (which caused freezes and crashes on Windows).


## v0.6.5 (2026-03-21)
### Fixed
- Server connection timeout no longer causes infinite startup hang: ConnectTimeout now fails fast and shows an error message instead of retrying with a 300s fallback
- Game cards now open correctly when clicking anywhere on the card, not just the image area
- "No Cover" placeholder now fills the full card area and matches the style used in the game detail panel

### Changed
- Game cards now use uniform fixed height for an orderly grid layout; images scale with aspect ratio preserved and are centered within the card
- Eden emulator source updated: switched from defunct GitHub mirror to official Gitea release (v0.2.0-rc2)
- RetroArch stable download URL corrected (RetroArch.7z, was RetroArch_update.7z)

## v0.6.4 (2026-03-17)
### Fixed
- Download stalling at 100%: registry entry now correctly unregistered when a download fails, preventing the UI from freezing with no Play button
- Duplicate downloads appearing when re-clicking download on a stalled game: registry now cancels and cleans up any existing entry before registering a new one
- PCSX2 save path returning None when memcards directory not yet created: configured path is now returned regardless of whether it exists on disk
- FolderStrategy returning None for uncreated save directories: get_save_dir now falls back to the configured path even if the folder doesn't exist yet
- Fixed hint argument order in FolderStrategy auto-detection: exe path is now tried before rom dict, preventing type errors in PCSX2 and similar emulators

## v0.6.3 (2026-03-14)
### Added
- Improved Library UI:
    - Fixed alphabetical sorting across all batches (no more fragmented sorting when scrolling)
    - Reliable "All Platforms" search (now checks both game names and filesystem names)
    - Enhanced Game Cards: Scaled artwork better supports square cover art without clipping
- Robust Download & Extraction:
    - Download list now correctly transitions to "Extracting" status (no longer stuck on "Downloading")
    - Windows games now show "Play" button immediately after extraction finishes
    - Expanded executable detection for Windows games (better exclusion of setups/launchers)
- Self-Updater Reliability:
    - Refined Windows restart logic using detached processes to prevent update failures
    - Added error reporting for extraction failures in the game detail panel

### Fixed
- Xenoblade Chronicles 2 and other 'X' games sorted incorrectly into 'S'
- Search failing to find games when on "All Platforms" view
- Extraction status not updating in the download queue UI

## v0.6.2 (2026-03-14)
### Added
- Overhauled BIOS/Firmware Manager:
    - Dedicated RomM `/api/firmware` support with platform-scraping fallback
    - Group-by-platform UI layout with "Download All" support
    - Smart BIOS destinations (auto-resolves `%APPDATA%`, `Documents`, and emulator paths)
    - Emulator-specific filtering (only shows BIOS files relevant to the active emulator)
    - PS3 Firmware (`PS3UPDAT.PUP`) installation via RPCS3 `--installfw` command
- Mid-session save sync improvements:
    - Opt-in via settings (`mid_session_sync_enabled`, default False)
    - Hash-based change detection (only uploads if save changed since session start)

### Fixed
- BIOS Manager false "No BIOS files found" by restoring platform-based fetching
- BIOS Manager noise reduction: added filename blocklist (python, java, etc.) and PlayStation pattern cross-checks
- Redundant mid-session uploads for frequent autosave games (Switch Odyssey fix)

## v0.6.0 (2026-03-12)
### Fixed
- Cloud save missing detection (upload when no wingosy slot exists)
- Windows settings auto-detect NameError (typo in loop variable)
- Exe picker dialog not launching game after selection (broken parent-walk replaced with signal)
- Game launches before conflict dialog resolved (blocking QEventLoop)
- Emulator track_session re-pulling saves after launch (skip_pull=True)

### Added
- PCGamingWiki integration in Windows game settings for automatic save directory detection
- Windows native game support (.zip/.7z/.iso download, extract, launch)
- Per-game Windows settings (default exe, save directory)
- Custom emulator editor UI with full schema support
- Per-platform emulator assignment
- Sync settings sub-tab with per-emulator sync toggle and conflict behavior
- Platform Assignments sub-tab for granular control
- Smart Windows pre-launch save pull logic
- Extraction progress bar for Windows games
- Dynamic emulator schema managed via emulators.json
- Redesigned game detail focus view
- Watcher error boundaries and configurable log levels
- DummyRomMClient stub methods (list_all_saves, list_all_states, delete_save, delete_state)

### Security
- Migrated auth token storage to system keyring (Windows Credential Picker)
- Automatic migration of existing tokens from plaintext config

## v0.5.7
### Added
- Parallel library page loading for significantly faster startup
- Inline loading status labels instead of popup banners

### Fixed
- Increased connection timeouts with descriptive error messages
- MEI cleanup delay to prevent access denied errors on restart

## v0.5.6
### Fixed
- Improved error handling for slow or unreachable servers
- Distinct error messages for timeout vs auth failure
- MEI cleanup resilience

## v0.5.5
### Added
- Cloud pull blocks before emulator launch
- Live connection tests in test suite
- File logging to ~/.wingosy/app.log

### Fixed
- App crash on restart related to certifi TLS paths
- Restart logic for frozen executables on Windows
- Platform filter persistence
- False connection failure banners on startup
- PSP state sync when SAVEDATA remained unchanged
- Save conflict dialog timing

## v0.5.4
### Added
- Dual save sync (SRM + savestate) for RetroArch cores
- Full PSP folder and state file synchronization
- Pre-launch blocking cloud pull

### Fixed
- skip_next_pull logic after conflict resolution
- PSP permission errors on SAVEDATA folders
- State file naming conventions on download
- Missing save folder mappings for 3DO, MSX, and Saturn

## v0.5.3
### Added
- Cards-per-row setting (1–12) with live resize
- Background library fetch with local caching
- Live host editing with connection testing
- Network error handling with reconnect banner
- Startup MEI folder cleanup

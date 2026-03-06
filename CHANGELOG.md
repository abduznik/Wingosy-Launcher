# Wingosy Launcher Changelog

All notable changes to this project will be documented here.

## [0.5.2] - 2026-03-06

### Added
- RetroArch save sync — per-core subfolder detection for 40+ cores (saves/<CoreFolder>/<rom>.srm)
- PSP save sync — full SAVEDATA folder sync via PPSSPP core path
- Save sync uses both hash AND mtime detection so saves are never missed even when hash matches previous session
- RetroArch auto-save prompt — once per session, offers to enable savestate_auto_save and savestate_auto_load in retroarch.cfg (PSP exempt)
- PPSSPP asset auto-download — detects missing ppge_atlas.zim on PSP launch, offers to fetch asset pack from buildbot.libretro.com
- Pagination tests — 32 tests total, covers offset pagination, duplicate detection, and RomM API response shape
- Demo mode uses realistic 50-card scroll batches

### Fixed
- Library pagination — now uses limit/offset params matching RomM's actual API (was using page/page_size which RomM ignores)
- All games now fetched — was silently capping at 50 regardless of library size
- Scrollbar drag no longer causes concurrent batch render crashes (150ms debounce)

## [0.5.1] - 2026-03-06

### Fixed
- Pagination loop stop condition — was stopping after first page due to item count vs page_size comparison
- Duplicate page detection safety guard added

## [0.5.0] - 2026-03-06

### Added
- Virtual scrolling — 50 cards per batch, eliminates UI freeze on large libraries
- Library cache — instant startup display while background refresh runs
- Platform slug expansion — 80+ slug variants recognized
- "⚠️ No Emulator" filter for unsupported platforms
- Testing infrastructure — pytest suite, DummyRomMClient, demo.py
- Azahar emulator support (replaces archived Citra)
- platform_slugs lists on all emulator configs

### Fixed
- RPCS3 DLL conflict with PyInstaller bundled vcruntime140.dll
- Cemu save path zip extraction folder structure
- Scrollbar drag crash on rapid scroll in large libraries

### v0.4.0
- Auto-updating exe with in-place replacement and restart prompt
- Save conflict resolution dialog (Use Cloud / Keep Local / Keep Both)
- RetroArch core auto-download from libretro buildbot when core is missing
- RetroArch fallback for platforms without a dedicated emulator (N64, PSX, SNES, GBA, etc.)
- System tray notifications for sync success, failure, and cloud save applied
- Download queue panel showing active downloads with progress and cancel buttons
- Game state indicators on library cards: green dot for local ROM, blue dot for cloud save
- Emulator health indicators: green/red/grey status per emulator row
- Library refresh button and F5 keyboard shortcut
- Ctrl+F keyboard shortcut to focus search
- First-run welcome dialog explaining setup steps
- Connection test button in Settings
- Window geometry saved and restored between sessions
- About dialog in Settings
- Logout confirmation dialog
- URL validation in setup dialog
- UI refactored from single 1000+ line file into maintainable package structure
- Save temp files now go to ~/.wingosy/tmp/ instead of current working directory
- Fixed: simultaneous game launches no longer corrupt each other's temp files
- Fixed: image fetch queue properly cancels on library filter change
- Fixed: track_session no longer blocks the UI thread on PLAY
- Fixed: Switch title ID resolution via SQLite cache, XCI header, and recency scan

### v0.3.1
- Fixed Switch save path resolution for Eden and Yuzu
- Dynamic title ID resolution replacing hardcoded dictionary
- Multi-method fallback: SQLite cache, XCI header, recency scan, regex
- Expanded search roots for yuzu, eden, sudachi, torzu

### v0.3.0
- Initial Windows release
- Cloud save sync with RomM
- Portable emulator management
- BIOS/firmware download
- Process-specific game tracking

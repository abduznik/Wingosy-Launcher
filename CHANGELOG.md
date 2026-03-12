# Changelog

## v0.6.0
### Added
- Windows native game support (.zip/.7z/.iso download, extract, launch)
- PCGamingWiki save location suggestions
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

### Security
- Migrated auth token storage to system keyring (Windows Credential Picker)
- Automatic migration of existing tokens from plaintext config

### Fixed
- Library reload behavior on emulator path changes
- Platform filter reset regression
- Standardized RomMClient token lifecycle management

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

# Changelog

## v0.5.4
### New Features
- RetroArch dual save sync: SRM + savestate synced on every session for all RetroArch cores
- PSP full sync: SAVEDATA folder AND state file both uploaded and downloaded per session
- Cloud pull now happens before emulator launches (blocking)
- Conflict dialog shown before launch, not after

### Bug Fixes
- Fixed skip_next_pull firing on every launch instead of only after conflict resolution
- Fixed upload_state sending to wrong endpoint
- Fixed PSP permission error on SAVEDATA folder at launch
- Fixed PSP state never uploading when SAVEDATA was unchanged
- Fixed state file written without .auto suffix on download
- Fixed _ppsspp_assets_checked NameError on PSP launch
- Added missing save folder mappings for 3DO, MSX, Saturn

### Cleanup
- Removed all diagnostic debug prints and temp scripts

## v0.5.3
### New Features
- Cards-per-row setting (1–12, live resize)
- Background library fetch with instant cache on startup
- Live host editing in Settings with test + apply + restart
- Network error handling with reconnect banner
- MEI folder cleanup on startup

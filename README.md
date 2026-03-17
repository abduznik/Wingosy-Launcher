<p align="center">
  <img src="gif_example.gif" alt="Wingosy in action" width="850">
</p>

# Wingosy
> A game launcher and cloud save sync client for RomM on Windows. Browse your library, launch games, and keep saves backed up automatically.

![Tests](https://github.com/abduznik/Wingosy-Launcher/actions/workflows/test.yml/badge.svg)

## Features
- Browse full RomM library with cover art, ratings, platform filter and search
- Launch games via configured emulators with one click
- Auto save sync — pulls latest save before launch, pushes on exit
- Smart conflict detection — per-emulator behavior: always ask, prefer cloud, or prefer local
- Windows native game support — download, extract and launch .zip / .7z / .iso PC games directly
- PCGamingWiki integration — auto-suggests save folder locations for Windows games
- Per-game Windows settings — pin a default exe and save directory
- Custom emulator support — add any emulator with full config (name, exe, launch args, platforms, save mode)
- Per-platform emulator assignment — e.g. use native PPSSPP instead of RetroArch for PSP
- Secure credential storage via OS keyring
- Parallel library loading for large collections
- Configurable sync interval and log level

## What's New in v0.6.4 (2026-03-17)
### Fixed
- **Download Stall at 100%**: Downloads that failed after completing no longer freeze the UI — the Play button now appears correctly and the registry entry is cleaned up
- **Duplicate Downloads**: Re-clicking download on a stalled game no longer creates duplicate entries in the download list
- **PCSX2 Save Path**: Save directory is now resolved correctly even before the memcards folder exists on disk
- **Save Strategy Robustness**: FolderStrategy and PCSX2Strategy no longer return None for configured-but-uncreated save directories

## What's New in v0.6.3 (2026-03-14)
### Added
- **Improved Library UI**:
    - **Alphabetical Batch Sorting**: Fixed issues where games loaded later would break the sort order. Your library is now perfectly sorted A-Z regardless of batch size.
    - **Reliable Global Search**: Searching "All Platforms" now correctly finds games by both their display name and internal filename.
    - **Square Artwork Support**: Game cards now scale better for square artwork, ensuring your covers aren't clipped or misaligned.
- **Robustness & Fixes**:
    - **Extraction Status**: The download manager now clearly shows "Extracting" after a download finishes, and Windows games immediately show the "Play" button once done.
    - **Resilient Self-Updater**: Refined the Windows restart logic to prevent "Access Denied" or hanging errors during the self-update process.
    - **Enhanced EXE Detection**: Better filtering of installers, setups, and launchers when auto-detecting Windows game executables.

## What's New in v0.6.2 (2026-03-14)
### Added
- **Overhauled BIOS/Firmware Manager**:
    - Automatic grouping and filtering of BIOS files per emulator
    - Smart destination resolution (places files in correct system/keys folders automatically)
    - PS3 Firmware installation support via RPCS3 integration
- **Optimized Save Sync**:
    - Mid-session sync is now opt-in to save bandwidth and disk IO
    - Hash-based change detection prevents redundant uploads

## What's New in v0.6.0 (2026-03-12)
### Fixed
- **Cloud save missing detection**: Wingosy now uploads even when no wingosy slot exists on RomM
- **Windows settings auto-detect NameError**: Fixed crash caused by loop variable typo
- **Exe picker dialog**: Fixed broken parent-walk logic that prevented game launch after selection
- **Conflict blocking**: Game launch now correctly waits for conflict dialog resolution
- **Double pull prevention**: Fixed emulator track_session re-pulling saves after pre-launch sync

### Added
- **PCGamingWiki integration**: Automatic save directory discovery for Windows games
- **API Parity**: Full test suite coverage for DummyRomMClient stub methods

## Supported Emulators

| Emulator | Platforms |
| :--- | :--- |
| Multi-Console (RetroArch) | multi, nes, snes, n64, gb, gbc, gba, genesis, mastersystem, segacd, gamegear, atari2600, psx, psp |
| Switch (Eden) | switch, nintendo-switch |
| PlayStation 3 | ps3, playstation-3, playstation3 |
| GameCube / Wii | gc, ngc, wii, gamecube, nintendo-gamecube, nintendo-wii, wii-u-vc |
| PlayStation 2 | ps2, playstation-2, playstation2 |
| Wii U (Cemu) | wiiu, wii-u, nintendo-wii-u, nintendo-wiiu |
| Nintendo 3DS (Azahar) | n3ds, 3ds, nintendo-3ds, nintendo3ds, new-nintendo-3ds, new-nintendo-3ds-xl |
| Windows (Native) | windows, win, pc, pc-windows, windows-games, win95, win98 |

## Getting Started (for regular users)

1. Download the latest `Wingosy.exe` from [Releases](https://github.com/abduznik/Wingosy-Launcher/releases)
2. Run it — no install needed
3. Enter your RomM server URL and credentials
4. Set emulator paths in the **Emulators** tab
5. Click any game to play

That's it. No Python, no dependencies.

## Windows Games
- Add games as .zip, .7z, or .iso to RomM under a Windows platform slug
- Wingosy downloads and extracts them automatically
- PCGamingWiki suggests where the game saves files
- Pin a default exe and save folder per game in Game Settings
- Saves are zipped and synced to RomM on exit

## Save Sync
- Pulls before launch if cloud is newer, folder is empty, or folder is missing
- Pushes on exit — zips save dir, uploads to RomM
- Per-emulator conflict behavior in the Sync tab
- Sync interval configurable (default 120s)

## For Developers & Contributors

### Requirements
- Python 3.11+
- A running RomM instance

### Run from source
    git clone https://github.com/abduznik/Wingosy-Launcher
    cd Wingosy-Launcher
    pip install -r requirements.txt
    python main.py

### Run tests
    python -m pytest tests/ -v

### Build exe
    pip install pyinstaller
    pyinstaller wingosy.spec

## License
GPL-3.0

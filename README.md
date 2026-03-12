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

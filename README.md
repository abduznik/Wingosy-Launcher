# Argosy Desktop Launcher

A Windows port of the original [Argosy Launcher for Android](https://github.com/rommapp/argosy-launcher).

Argosy is a lightweight, portable Windows game launcher designed to bridge the gap between your local emulators and a RomM server. It features automated cloud save syncing, portable emulator management, and a unified library interface.

## Key Features

- Cloud Save Syncing: Automatically pulls your latest saves from RomM before you play and pushes changes back to the cloud as soon as you close the emulator.
- Universal PLAY Button: One-click to sync, launch, and track your games across PCSX2, Dolphin, Yuzu/Eden, RetroArch, and more.
- Portable Emulator Management: Download and manage the latest versions of your favorite emulators directly through the app. Supports Portable Mode automatically.
- BIOS / Firmware Rescue: Search and download required BIOS files directly from your RomM library or firmware index.
- Library Search & Filtering: Instantly find games by name or console platform.

## Getting Started

1. Download: Grab the latest Argosy.exe from the Releases page.
2. Setup: On the first run, enter your RomM host URL and credentials.
3. Configure Paths:
    - Go to the Emulators tab.
    - Set your ROM Path (where your games are stored).
    - Set your Emu Path (where you want emulators to be installed).
4. Sync & Play: Click on any game in your library and hit PLAY. Argosy will handle the rest!

## Supported Emulators

Note: Only PlayStation 2 and Nintendo Switch have been fully tested and verified as stable in the current prototype.

- PlayStation 2: PCSX2 (Qt) - Tested
- Nintendo Switch: Yuzu / Eden / Ryujinx - Tested
- GameCube / Wii: Dolphin - In Progress
- Multi-system: RetroArch - In Progress
- And more... (easily extensible via config.json)

## Project Roadmap

### Current Status
- Tested and Stable: PlayStation 2 (PCSX2), Nintendo Switch (Yuzu/Eden).
- In Progress: Dolphin (GC/Wii), RetroArch (Multi-system).

### Planned Features
- Expanded Emulator Support: Verify and stabilize path resolution for Dolphin, RPCS3, and Citra.
- RetroArch Intelligence: Logic to automatically select/download the correct core based on RomM platform metadata.
- Conflict Resolution: A simple UI prompt to choose between Keep Local or Use Cloud if both have changed since last sync.
- System Tray Notifications: Native Windows notifications for sync success, failures, or background tracking status.
- UI Polish:
    - Smooth transitions between Library and Emulator tabs.
    - Detailed game view with screenshots and metadata from RomM.
    - Download queue manager for multiple ROM/BIOS downloads.
- Auto-Update: Self-updating capability for the Argosy.exe itself.
- Custom Emulator Profiles: Allow users to add their own custom emulator definitions via the UI.

## Building from Source

If you want to run or build Argosy manually:

```powershell
# Install dependencies
pip install PySide6 psutil requests py7zr

# Run the app
python main.py

# Build .exe
pip install pyinstaller
pyinstaller --noconsole --onefile --name Argosy main.py
```

## License

MIT License. See LICENSE for details.

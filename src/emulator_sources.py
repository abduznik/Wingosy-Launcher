"""
Emulator download source definitions.
Edit this file to update download sources without touching application logic.
"""

EMULATOR_SOURCES = {
    "retroarch": {
        "type": "direct",
        "label": "RetroArch (Stable)",
        "url": "https://buildbot.libretro.com/stable/1.22.2/windows/x86_64/RetroArch_update.7z",
        "exe_hint": "retroarch.exe"
    },
    "eden": {
        "type": "github",
        "repo": "eden-emulator/Releases",
        "asset_filters": {
            "required": ["windows", "msvc"],
            "excluded": ["arm64", "macos", "android", "source", "mingw"]
        },
        "exe_hint": "eden.exe"
    },
    "rpcs3": {
        "type": "github",
        "repo": "RPCS3/rpcs3",
        "asset_filters": {
            "required": ["win64"],
            "excluded": ["debug"]
        },
        "exe_hint": "rpcs3.exe"
    },
    "dolphin": {
        "type": "dolphin_api",
        "exe_hint": "Dolphin.exe"
    },
    "pcsx2": {
        "type": "github",
        "repo": "PCSX2/pcsx2",
        "asset_filters": {
            "required": ["windows", "Qt"],
            "excluded": ["debug", "sse4", "arm64"]
        },
        "exe_hint": "pcsx2-qt.exe"
    },
    "cemu": {
        "type": "github",
        "repo": "cemu-project/Cemu",
        "asset_filters": {
            "required": ["windows"],
            "excluded": ["experimental", "debug"]
        },
        "exe_hint": "Cemu.exe"
    },
    "azahar": {
        "type": "github",
        "repo": "azahar-emu/azahar",
        "asset_filters": {
            "required": ["windows", "msys2"],
            "excluded": ["debug", "appimage"]
        },
        "exe_hint": "azahar.exe"
    },
    "xemu": {
        "type": "github",
        "repo": "xemu-project/xemu",
        "asset_filters": {
            "required": ["win", "x86_64", "release"],
            "excluded": ["dbg", "pdb", "arm", "macos", "appimage", "tar"]
        },
        "exe_hint": "xemu.exe"
    },
    "xenia": {
        "type": "direct",
        "url": "https://github.com/xenia-project/release-builds-windows/releases/latest/download/xenia_master.zip",
        "exe_hint": "xenia.exe"
    },
    "duckstation": {
        "type": "github",
        "repo": "stenzek/duckstation",
        "asset_filters": {
            "required": ["windows", "x64"],
            "excluded": ["nogui", "debug", "arm64"]
        },
        "exe_hint": "duckstation-qt-x64-ReleaseLTCG.exe"
    },
    "melonds": {
        "type": "github",
        "repo": "melonDS-emu/melonDS",
        "asset_filters": {
            "required": ["windows", "x86_64"],
            "excluded": ["aarch64", "macos", "ubuntu", "appimage", "freebsd", "netbsd", "openbsd"]
        },
        "exe_hint": "melonDS.exe"
    }
}

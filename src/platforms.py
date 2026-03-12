from src.config import ConfigManager

def platform_matches(platform_slug, emu_data):
    """Check if a platform slug matches an emulator's supported platforms."""
    if not platform_slug:
        return False
    slugs = emu_data.get("platform_slugs", [emu_data.get("platform_slug", "")])
    return platform_slug in slugs

RETROARCH_PLATFORMS = [
    # Nintendo handhelds
    "gb", "gbc", "gba", "nds", "nintendo-ds",
    # Nintendo home
    "nes", "nintendo-entertainment-system", "famicom",
    "snes", "super-nintendo-entertainment-system", "superfamicom",
    "n64", "nintendo64",
    "virtualboy", "virtual-boy",
    # Sega handhelds
    "gamegear", "game-gear",
    # Sega home
    "mastersystem", "master-system", "sega-master-system",
    "genesis", "megadrive", "mega-drive", "sega-genesis", "sega-mega-drive",
    "32x", "sega32x", "sega-32x",
    "segacd", "sega-cd", "megacd", "mega-cd", "sega-mega-cd",
    "saturn", "sega-saturn",
    "dreamcast", "sega-dreamcast",
    # Sony
    "psx", "ps1", "playstation", "playstation-1",
    "psp", "playstation-portable",
    # Microsoft
    "xbox", "xbox360",
    # Atari
    "atari2600", "atari-2600",
    "atari5200", "atari-5200",
    "atari7800", "atari-7800",
    "atari8bit", "atari-8-bit",
    "lynx", "atari-lynx",
    "jaguar", "atari-jaguar",
    # NEC
    "pcengine", "pc-engine", "turbografx-16", "turbografx16",
    # SNK
    "neogeo", "neo-geo", "ngp", "ngpc",
    "neo-geo-pocket", "neo-geo-pocket-color",
    # Misc
    "arcade", "fba", "mame",
    "3do",
    "wonderswan", "wonderswan-color",
    "msx", "msx2",
    "c64", "commodore-64",
    "dos", "pc-dos",
    "amiga",
    "scummvm",
]

RETROARCH_CORES = {
    # Nintendo
    "nes": "nestopia_libretro.dll",
    "nintendo-entertainment-system": "nestopia_libretro.dll",
    "famicom": "nestopia_libretro.dll",
    "snes": "snes9x_libretro.dll",
    "super-nintendo-entertainment-system": "snes9x_libretro.dll",
    "superfamicom": "snes9x_libretro.dll",
    "n64": "mupen64plus_next_libretro.dll",
    "nintendo64": "mupen64plus_next_libretro.dll",
    "gb": "gambatte_libretro.dll",
    "gbc": "gambatte_libretro.dll",
    "gba": "mgba_libretro.dll",
    "nds": "desmume2015_libretro.dll",
    "nintendo-ds": "desmume2015_libretro.dll",
    "virtualboy": "mednafen_vb_libretro.dll",
    "virtual-boy": "mednafen_vb_libretro.dll",
    # Sega
    "mastersystem": "genesis_plus_gx_libretro.dll",
    "master-system": "genesis_plus_gx_libretro.dll",
    "sega-master-system": "genesis_plus_gx_libretro.dll",
    "genesis": "genesis_plus_gx_libretro.dll",
    "megadrive": "genesis_plus_gx_libretro.dll",
    "mega-drive": "genesis_plus_gx_libretro.dll",
    "sega-genesis": "genesis_plus_gx_libretro.dll",
    "sega-mega-drive": "genesis_plus_gx_libretro.dll",
    "32x": "picodrive_libretro.dll",
    "sega32x": "picodrive_libretro.dll",
    "sega-32x": "picodrive_libretro.dll",
    "segacd": "genesis_plus_gx_libretro.dll",
    "sega-cd": "genesis_plus_gx_libretro.dll",
    "megacd": "genesis_plus_gx_libretro.dll",
    "mega-cd": "genesis_plus_gx_libretro.dll",
    "sega-mega-cd": "genesis_plus_gx_libretro.dll",
    "gamegear": "genesis_plus_gx_libretro.dll",
    "game-gear": "genesis_plus_gx_libretro.dll",
    "saturn": "yabasanshiro_libretro.dll",
    "sega-saturn": "yabasanshiro_libretro.dll",
    "dreamcast": "flycast_libretro.dll",
    "sega-dreamcast": "flycast_libretro.dll",
    # Sony
    "psx": "pcsx_rearmed_libretro.dll",
    "ps1": "pcsx_rearmed_libretro.dll",
    "playstation": "pcsx_rearmed_libretro.dll",
    "playstation-1": "pcsx_rearmed_libretro.dll",
    "psp": "ppsspp_libretro.dll",
    "playstation-portable": "ppsspp_libretro.dll",
    # Atari
    "atari2600": "stella2014_libretro.dll",
    "atari-2600": "stella2014_libretro.dll",
    "atari5200": "a5200_libretro.dll",
    "atari-5200": "a5200_libretro.dll",
    "atari7800": "prosystem_libretro.dll",
    "atari-7800": "prosystem_libretro.dll",
    "lynx": "handy_libretro.dll",
    "atari-lynx": "handy_libretro.dll",
    "jaguar": "virtualjaguar_libretro.dll",
    "atari-jaguar": "virtualjaguar_libretro.dll",
    # NEC
    "pcengine": "mednafen_pce_libretro.dll",
    "pc-engine": "mednafen_pce_libretro.dll",
    "turbografx-16": "mednafen_pce_libretro.dll",
    "turbografx16": "mednafen_pce_libretro.dll",
    # SNK
    "neogeo": "fbalpha2012_neogeo_libretro.dll",
    "neo-geo": "fbalpha2012_neogeo_libretro.dll",
    "ngp": "mednafen_ngp_libretro.dll",
    "ngpc": "mednafen_ngp_libretro.dll",
    "neo-geo-pocket": "mednafen_ngp_libretro.dll",
    "neo-geo-pocket-color": "mednafen_ngp_libretro.dll",
    # Misc
    "arcade": "mame_libretro.dll",
    "fba": "fbalpha2012_libretro.dll",
    "mame": "mame_libretro.dll",
    "3do": "opera_libretro.dll",
    "wonderswan": "mednafen_wswan_libretro.dll",
    "wonderswan-color": "mednafen_wswan_libretro.dll",
    "msx": "fmsx_libretro.dll",
    "msx2": "fmsx_libretro.dll",
    "c64": "vice_x64_libretro.dll",
    "commodore-64": "vice_x64_libretro.dll",
    "dos": "dosbox_pure_libretro.dll",
    "pc-dos": "dosbox_pure_libretro.dll",
    "amiga": "puae_libretro.dll",
    "scummvm": "scummvm_libretro.dll",
}

# Maps core name (no .dll) → saves subfolder name
# Standard cores: saves/<folder>/<rom>.srm
# PSP: saves/<folder>/PSP/SAVEDATA/ (folder sync)
RETROARCH_CORE_SAVE_FOLDERS = {
    # Nintendo
    "fceumm":           "FCEUmm",
    "nestopia":         "Nestopia",
    "snes9x":           "Snes9x",
    "snes9x2010":       "Snes9x2010",
    "gambatte":         "Gambatte",
    "mgba":             "mGBA",
    "vba_next":         "VBA Next",
    "mednafen_gba":     "Mednafen GBA",
    "mupen64plus_next": "Mupen64Plus-Next",
    "parallel_n64":     "ParaLLEl N64",
    "melonds":          "MelonDS",
    "desmume2015":      "DeSmuME 2015",
    "desmume":          "DeSmuME",
    "mednafen_vb":      "Mednafen VB",
    # Sega
    "genesis_plus_gx":  "Genesis Plus GX",
    "picodrive":        "PicoDrive",
    "blastem":          "BlastEm",
    "mednafen_saturn":  "Mednafen Saturn",
    "flycast":          "Flycast",
    "yabause":          "Yabause",
    "gearsystem":       "GearSystem",
    # Sony
    "mednafen_psx_hw":  "Mednafen PSX HW",
    "mednafen_psx":     "Mednafen PSX",
    "pcsx_rearmed":     "PCSX-ReARMed",
    # PSP — special: folder sync not single SRM
    "ppsspp":           "PPSSPP",
    # Saturn
    "yabasanshiro":     "YabaSanshiro",
    # Atari
    "stella":           "Stella",
    "stella2014":       "Stella 2014",
    "prosystem":        "ProSystem",
    "a5200":            "a5200",
    "atari800":         "Atari800",
    "handy":            "Handy",
    "virtualjaguar":    "Virtual Jaguar",
    # NEC
    "mednafen_pce":     "Mednafen PCE",
    "mednafen_pce_fast":"Mednafen PCE Fast",
    # SNK
    "fbalpha2012_neogeo": "FB Alpha 2012 NeoGeo",
    "fbneo":            "FinalBurn Neo",
    "mednafen_ngp":     "Mednafen NGP",
    # Arcade
    "mame":             "MAME",
    "mame2003_plus":    "MAME 2003-Plus",
    "fbalpha2012":      "FB Alpha 2012",
    # Misc
    "opera":            "Opera",
    "fmsx":             "fMSX",
    "mednafen_wswan":   "Mednafen WonderSwan",
    "smsplus":          "SMS Plus GX",
    "bluemsx":          "blueMSX",
    "vice_x64":         "VICE x64",
    "dosbox_pure":      "DOSBox-pure",
    "puae":             "PUAE",
    "scummvm":          "ScummVM",
    "3do_libretro":     "3DO",
}

# Cores that use folder-based saves instead of single SRM files
RETROARCH_FOLDER_SAVE_CORES = {
    "ppsspp",  # saves/PPSSPP/PSP/SAVEDATA/<game>/
}

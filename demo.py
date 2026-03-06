"""
demo.py — Run Wingosy in demo mode with a fake library.
Usage:
    python demo.py           # 5000 fake games
    python demo.py --count 100   # 100 fake games
    python demo.py --count 1200  # simulate GavlanWantSoul's library
"""
import sys
import logging
import argparse
from pathlib import Path
from PySide6.QtWidgets import QApplication
from src.config import ConfigManager
from src.watcher import WingosyWatcher
from src.ui import WingosyMainWindow
from tests.dummy import DummyRomMClient

VERSION = "DEMO"

# Set up logging to both console and file
log_path = Path("demo.log")
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(log_path, mode="w", encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ]
)
logger = logging.getLogger("wingosy.demo")

def main():
    parser = argparse.ArgumentParser(description="Wingosy Demo Mode")
    parser.add_argument("--count", type=int, default=5000,
                        help="Number of fake games to generate (default 5000)")
    args = parser.parse_args()

    logger.info("=" * 60)
    logger.info("  WINGOSY DEMO MODE — based on v0.5.2")
    logger.info(f"  Fake library size: {args.count} games")
    logger.info(f"  Log file: {log_path.resolve()}")
    logger.info("=" * 60)

    app = QApplication(sys.argv)
    app.setApplicationName("Wingosy Launcher [DEMO]")
    app.setOrganizationName("Wingosy")
    app.setQuitOnLastWindowClosed(False)
    app.setStyle("Fusion")

    config = ConfigManager()

    # Use dummy client — no login needed
    DummyRomMClient.GAME_COUNT = args.count
    client = DummyRomMClient(config=config)
    client.fetch_library()  # pre-populate user_games

    logger.info("Starting Wingosy window in demo mode...")
    window = WingosyMainWindow(config, client, WingosyWatcher, VERSION)
    # Use realistic batch size matching RomM's 50-per-page default
    window.library_tab.LOAD_BATCH = 50
    logger.info("  Scroll batch size: 50 (matching real RomM page size)")
    window.setWindowTitle(f"Wingosy Launcher [DEMO — {args.count} games]")
    window.show()

    sys.exit(app.exec())

if __name__ == "__main__":
    main()

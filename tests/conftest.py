"""
conftest.py — shared pytest fixtures and configuration for Wingosy tests.
"""
import pytest
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Ensure PySide6 QApplication exists for any test that needs Qt
_app = None

@pytest.fixture(scope="session", autouse=True)
def qt_app():
    global _app
    from PySide6.QtWidgets import QApplication
    if QApplication.instance() is None:
        _app = QApplication(sys.argv)
    yield QApplication.instance()

@pytest.fixture
def dummy_client():
    from tests.dummy import DummyRomMClient
    return DummyRomMClient(game_count=50)

@pytest.fixture
def config():
    from src.config import ConfigManager
    return ConfigManager()

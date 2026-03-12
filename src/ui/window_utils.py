import sys
import logging

def apply_dark_titlebar(widget):
    """
    Apply dark title bar to any QWidget/QDialog on Windows 10 20H1+ and Windows 11.
    Safe no-op on other platforms.
    """
    if sys.platform != "win32":
        return
    try:
        import ctypes
        import ctypes.wintypes
        
        hwnd = int(widget.winId())
        
        # DWMWA_USE_IMMERSIVE_DARK_MODE = 20
        # Works on Windows 10 20H1 (build 19041+) and Windows 11
        DWMWA_USE_IMMERSIVE_DARK_MODE = 20
        value = ctypes.c_int(1)
        
        result = ctypes.windll.dwmapi.DwmSetWindowAttribute(
            hwnd,
            DWMWA_USE_IMMERSIVE_DARK_MODE,
            ctypes.byref(value),
            ctypes.sizeof(value))
        
        if result != 0:
            # Try older attribute value (19) for Windows 10 builds before 20H1
            DWMWA_USE_IMMERSIVE_DARK_MODE_OLD = 19
            ctypes.windll.dwmapi.DwmSetWindowAttribute(
                hwnd,
                DWMWA_USE_IMMERSIVE_DARK_MODE_OLD,
                ctypes.byref(value),
                ctypes.sizeof(value))
    except Exception as e:
        logging.debug(f"[DarkTitle] Failed: {e}")

def apply_dark_titlebar_on_show(widget):
    """
    Schedule dark title bar application after the widget is shown 
    (winId may not be valid before show).
    """
    from PySide6.QtCore import QTimer
    QTimer.singleShot(0, lambda: apply_dark_titlebar(widget))

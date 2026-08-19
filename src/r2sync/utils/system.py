"""System utilities for autostart, network check, and OS integration."""

import os
import socket
import sys
from pathlib import Path
from typing import Optional


def is_windows() -> bool:
    return sys.platform == "win32"


def check_internet_connection(host: str = "1.1.1.1", port: int = 53, timeout: float = 3.0) -> bool:
    """Check internet connectivity via DNS reachability."""
    try:
        socket.setdefaulttimeout(timeout)
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.connect((host, port))
        s.close()
        return True
    except Exception:
        return False


def set_windows_autostart(app_name: str, app_path: str, enable: bool = True) -> bool:
    """Register or unregister an application in HKCU\Software\Microsoft\Windows\CurrentVersion\Run."""
    if not is_windows():
        return False

    try:
        import winreg  # Windows only
        key = winreg.HKEY_CURRENT_USER
        sub_key = r"Software\Microsoft\Windows\CurrentVersion\Run"
        
        with winreg.OpenKey(key, sub_key, 0, winreg.KEY_ALL_ACCESS) as reg_key:
            if enable:
                winreg.SetValueEx(reg_key, app_name, 0, winreg.REG_SZ, f'"{app_path}" --minimized')
            else:
                try:
                    winreg.DeleteValue(reg_key, app_name)
                except FileNotFoundError:
                    pass
        return True
    except Exception:
        return False


def get_windows_autostart(app_name: str) -> bool:
    """Check if application is registered in HKCU Run key."""
    if not is_windows():
        return False

    try:
        import winreg
        key = winreg.HKEY_CURRENT_USER
        sub_key = r"Software\Microsoft\Windows\CurrentVersion\Run"
        
        with winreg.OpenKey(key, sub_key, 0, winreg.KEY_READ) as reg_key:
            try:
                winreg.QueryValueEx(reg_key, app_name)
                return True
            except FileNotFoundError:
                return False
    except Exception:
        return False

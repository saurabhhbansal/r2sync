"""System utilities for autostart, network check, and OS integration."""

import logging
import os
import socket
import subprocess
import sys
from pathlib import Path
from typing import List, Optional

logger = logging.getLogger(__name__)

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"

# Registry value name for the *background service*. It is deliberately separate
# from the GUI's autostart entry: synchronization must resume at login whether
# or not the user wants the window to open.
SERVICE_AUTOSTART_NAME = "r2sync Service"


def is_windows() -> bool:
    return sys.platform == "win32"


# Probed in order until one answers. Port 443 comes first because that is what
# r2sync actually needs; the original check only tried DNS on port 53, which
# plenty of corporate networks, VPNs and consumer routers block outright while
# R2 itself is perfectly reachable -- and a dataset that fails this check is
# marked Offline and stops syncing until a later attempt succeeds.
#
# The IP-literal probe needs no name resolution; the hostname probe needs DNS
# to work, which rclone will also need. Trying both, and accepting either, is
# deliberate: a false "offline" stops synchronization altogether, while a false
# "online" only lets rclone attempt the transfer and report what really failed.
_CONNECTIVITY_PROBES = (
    ("1.1.1.1", 443),
    ("cloudflare.com", 443),
    ("1.1.1.1", 53),
)


def check_internet_connection(
    host: Optional[str] = None, port: Optional[int] = None, timeout: float = 3.0
) -> bool:
    """True when anything out on the internet answers.

    Pass ``host``/``port`` to probe one specific endpoint instead of the
    built-in list.
    """
    probes = ((host, port or 443),) if host else _CONNECTIVITY_PROBES

    for probe_host, probe_port in probes:
        try:
            # A per-socket timeout. This used to call socket.setdefaulttimeout,
            # which is process-global and was never restored, so one
            # connectivity check silently imposed its timeout on every socket
            # the GUI and daemon opened afterwards.
            with socket.create_connection((probe_host, probe_port), timeout=timeout):
                return True
        except OSError as e:
            logger.debug(f"Connectivity probe {probe_host}:{probe_port} failed: {e}")

    return False


def set_windows_autostart(app_name: str, app_path: str, enable: bool = True) -> bool:
    r"""Register or unregister an application in HKCU\Software\Microsoft\Windows\CurrentVersion\Run."""
    if not is_windows():
        return False

    try:
        import winreg  # Windows only
        key = winreg.HKEY_CURRENT_USER
        sub_key = r"Software\Microsoft\Windows\CurrentVersion\Run"
        
        with winreg.CreateKeyEx(key, sub_key, 0, winreg.KEY_ALL_ACCESS) as reg_key:
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


def get_service_executable() -> List[str]:
    r"""Return the command that launches the background service.

    Prefers the frozen ``r2sync-service.exe`` that sits next to the GUI
    executable; falls back to ``python -m r2sync.service.main`` when running
    from a source checkout.
    """
    exe_name = "r2sync-service.exe" if is_windows() else "r2sync-service"

    candidates = []
    if getattr(sys, "frozen", False):
        candidates.append(Path(sys.executable).parent / exe_name)
    candidates.append(Path(sys.executable).parent / exe_name)

    for candidate in candidates:
        try:
            if candidate.exists():
                return [str(candidate), "--standalone"]
        except OSError:
            continue

    return [sys.executable, "-m", "r2sync.service.main", "--standalone"]


def _quote_command(cmd: List[str]) -> str:
    return " ".join(f'"{part}"' if " " in part else part for part in cmd)


def set_windows_service_autostart(enable: bool = True) -> bool:
    r"""Register the *background service* to start at every Windows logon.

    Written to HKCU\...\Run so it works for a standard (non-elevated) install,
    which is what the r2sync installer performs. This is what makes sync resume
    after a reboot without the GUI being launched at all.
    """
    if not is_windows():
        return False

    try:
        import winreg

        with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_ALL_ACCESS) as reg_key:
            if enable:
                winreg.SetValueEx(
                    reg_key,
                    SERVICE_AUTOSTART_NAME,
                    0,
                    winreg.REG_SZ,
                    _quote_command(get_service_executable()),
                )
            else:
                try:
                    winreg.DeleteValue(reg_key, SERVICE_AUTOSTART_NAME)
                except FileNotFoundError:
                    pass
        return True
    except Exception as e:
        logger.warning(f"Could not update service autostart registration: {e}")
        return False


def get_windows_service_autostart() -> bool:
    """Check whether the background service is registered to start at logon."""
    if not is_windows():
        return False
    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_READ) as reg_key:
            try:
                winreg.QueryValueEx(reg_key, SERVICE_AUTOSTART_NAME)
                return True
            except FileNotFoundError:
                return False
    except Exception:
        return False


def is_service_process_running() -> bool:
    """True when an r2sync background service process is alive on this machine."""
    from r2sync.utils.paths import get_service_pid_path

    pid_path = get_service_pid_path()
    try:
        if not pid_path.exists():
            return False
        pid = int(pid_path.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return False

    try:
        import psutil

        if not psutil.pid_exists(pid):
            return False
        proc = psutil.Process(pid)
        name = (proc.name() or "").lower()
        cmdline = " ".join(proc.cmdline()).lower()
        return "r2sync" in name or "r2sync" in cmdline
    except Exception:
        # psutil unavailable or the process vanished mid-check.
        try:
            os.kill(pid, 0)
            return True
        except Exception:
            return False


def launch_background_service() -> bool:
    """Start the background service detached from the caller.

    Detaching matters: the service must outlive the GUI so closing the window
    does not stop synchronization.
    """
    if is_service_process_running():
        return True

    cmd = get_service_executable()
    kwargs = {
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
        "stdin": subprocess.DEVNULL,
    }
    if is_windows():
        # CREATE_NO_WINDOW | DETACHED_PROCESS
        kwargs["creationflags"] = 0x08000000 | 0x00000008
    else:
        kwargs["start_new_session"] = True

    try:
        subprocess.Popen(cmd, **kwargs)
        logger.info(f"Launched background service: {_quote_command(cmd)}")
        return True
    except Exception as e:
        logger.error(f"Failed to launch background service: {e}")
        return False

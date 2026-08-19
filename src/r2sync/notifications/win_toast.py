"""Native Windows 10/11 Toast Notification implementation."""

import logging
import subprocess
import sys
from typing import Optional

logger = logging.getLogger(__name__)


def show_windows_toast(
    title: str,
    message: str,
    app_id: str = "r2sync",
    notification_type: str = "info",
) -> bool:
    """Display a native Windows toast notification using PowerShell WinRT API."""
    if sys.platform != "win32":
        return False

    safe_title = title.replace('"', '`"').replace('$', '`$')
    safe_msg = message.replace('"', '`"').replace('$', '`$')

    ps_script = f"""
[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] > $null
[Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom.XmlDocument, ContentType = WindowsRuntime] > $null

$template = @"
<toast>
    <visual>
        <binding template="ToastGeneric">
            <text>{safe_title}</text>
            <text>{safe_msg}</text>
        </binding>
    </visual>
</toast>
"@

$xml = New-Object Windows.Data.Xml.Dom.XmlDocument
$xml.LoadXml($template)
$toast = [Windows.UI.Notifications.ToastNotification]::new($xml)
[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier("{app_id}").Show($toast)
"""

    try:
        flags = 0x08000000 if sys.platform == "win32" else 0
        res = subprocess.run(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps_script],
            capture_output=True,
            text=True,
            timeout=5,
            creationflags=flags,
        )
        return res.returncode == 0
    except Exception as e:
        logger.debug(f"PowerShell Windows Toast failed: {e}")
        return False

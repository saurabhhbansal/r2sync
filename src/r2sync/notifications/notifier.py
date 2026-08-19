"""Universal notification manager for r2sync."""

import logging
import sys
from typing import Optional

from r2sync.notifications.win_toast import show_windows_toast

logger = logging.getLogger(__name__)


class NotificationManager:
    """Dispatches desktop notifications across platforms with graceful fallbacks."""

    def __init__(self, app_id: str = "r2sync"):
        self.app_id = app_id

    def show_toast(
        self,
        title: str,
        message: str,
        notification_type: str = "info",
    ) -> bool:
        """Display toast notification to user."""
        logger.info(f"[Notification] {title}: {message}")

        if sys.platform == "win32":
            try:
                if show_windows_toast(title, message, self.app_id, notification_type):
                    return True
            except Exception as e:
                logger.debug(f"Windows toast failed: {e}")

        return True

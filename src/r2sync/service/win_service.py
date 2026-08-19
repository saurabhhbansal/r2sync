"""Windows Service integration for r2sync-service.exe using pywin32."""

import logging
import sys
from r2sync.config import (
    WINDOWS_SERVICE_DESCRIPTION,
    WINDOWS_SERVICE_DISPLAY_NAME,
    WINDOWS_SERVICE_NAME,
)

logger = logging.getLogger(__name__)

# Check for pywin32
try:
    import win32service
    import win32serviceutil
    import win32event
    import servicemanager
    PYWIN32_AVAILABLE = True
except ImportError:
    PYWIN32_AVAILABLE = False


if PYWIN32_AVAILABLE:
    class R2SyncWindowsService(win32serviceutil.ServiceFramework):
        _svc_name_ = WINDOWS_SERVICE_NAME
        _svc_display_name_ = WINDOWS_SERVICE_DISPLAY_NAME
        _svc_description_ = WINDOWS_SERVICE_DESCRIPTION

        def __init__(self, args):
            super().__init__(args)
            self.hWaitStop = win32event.CreateEvent(None, 0, 0, None)
            from r2sync.service.daemon import ServiceDaemon
            self.daemon = ServiceDaemon()

        def SvcStop(self):
            self.ReportServiceStatus(win32service.SERVICE_STOP_PENDING)
            self.daemon.stop()
            win32event.SetEvent(self.hWaitStop)

        def SvcDoRun(self):
            servicemanager.LogMsg(
                servicemanager.EVENTLOG_INFORMATION_TYPE,
                servicemanager.PYS_SERVICE_STARTED,
                (self._svc_name_, "")
            )
            self.daemon.start()
            win32event.WaitForSingleObject(self.hWaitStop, win32event.INFINITE)
            self.daemon.stop()


def handle_service_command(args: list[str]) -> None:
    if not PYWIN32_AVAILABLE:
        print("pywin32 is not installed. Running in standalone background daemon mode.")
        from r2sync.service.daemon import ServiceDaemon
        daemon = ServiceDaemon()
        daemon.run_forever()
        return

    win32serviceutil.HandleCommandLine(R2SyncWindowsService, argv=args)

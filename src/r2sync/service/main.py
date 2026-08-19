"""Main entry point for r2sync-service (background service daemon)."""

import argparse
import sys
from r2sync.service.daemon import ServiceDaemon
from r2sync.service.win_service import handle_service_command, PYWIN32_AVAILABLE


def main() -> int:
    parser = argparse.ArgumentParser(description="r2sync Background Backup Service")
    parser.add_argument("--standalone", action="store_true", help="Run daemon directly in console/standalone mode")
    parser.add_argument("--install", action="store_true", help="Install as Windows Service")
    parser.add_argument("--uninstall", action="store_true", help="Uninstall Windows Service")
    parser.add_argument("--start", action="store_true", help="Start Windows Service")
    parser.add_argument("--stop", action="store_true", help="Stop Windows Service")
    parser.add_argument("--status", action="store_true", help="Check service status")

    args, unknown = parser.parse_known_args()

    if args.standalone or not sys.platform == "win32" or not PYWIN32_AVAILABLE:
        daemon = ServiceDaemon()
        daemon.run_forever()
        return 0

    if args.install:
        handle_service_command([sys.argv[0], "install"])
    elif args.uninstall:
        handle_service_command([sys.argv[0], "remove"])
    elif args.start:
        handle_service_command([sys.argv[0], "start"])
    elif args.stop:
        handle_service_command([sys.argv[0], "stop"])
    elif args.status:
        handle_service_command([sys.argv[0], "status"])
    else:
        # Default Windows service dispatch or fallback standalone daemon
        try:
            handle_service_command(sys.argv)
        except Exception:
            daemon = ServiceDaemon()
            daemon.run_forever()

    return 0


if __name__ == "__main__":
    sys.exit(main())

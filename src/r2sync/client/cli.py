"""Command Line Interface for r2sync."""

import argparse
import json
import sys
from r2sync.client.ipc_client import IPCClient


def main() -> int:
    parser = argparse.ArgumentParser(prog="r2sync-cli", description="r2sync CLI client")
    subparsers = parser.add_subparsers(dest="command", help="Commands")

    # Status
    subparsers.add_parser("status", help="Check background service status and summary stats")

    # Jobs
    job_parser = subparsers.add_parser("jobs", help="Manage backup jobs")
    job_sub = job_parser.add_subparsers(dest="subcommand")
    job_sub.add_parser("list", help="List all backup jobs")
    run_cmd = job_sub.add_parser("run", help="Run a backup job now")
    run_cmd.add_argument("id", type=int, help="Job ID to run")
    cancel_cmd = job_sub.add_parser("cancel", help="Cancel a backup job")
    cancel_cmd.add_argument("id", type=int, help="Job ID to cancel")

    # R2
    r2_parser = subparsers.add_parser("r2", help="Manage Cloudflare R2")
    r2_sub = r2_parser.add_subparsers(dest="subcommand")
    r2_sub.add_parser("test", help="Test Cloudflare R2 connection")
    r2_sub.add_parser("buckets", help="List R2 buckets")

    # Runs / History
    subparsers.add_parser("history", help="List recent backup runs")

    # Interactive TUI
    subparsers.add_parser("tui", help="Launch interactive terminal dashboard (TUI)")

    # Updates
    subparsers.add_parser("update", help="Check for r2sync updates")

    args = parser.parse_args()

    if args.command == "tui":
        from r2sync.client.tui import run_tui
        run_tui()
        return 0

    if args.command == "update":
        from r2sync.core.updater import AutoUpdater
        from r2sync.config import APP_VERSION
        print(f"Checking for updates (current version: v{APP_VERSION})...")
        info = AutoUpdater.check_for_updates()
        if info.available:
            print(f"New version available: v{info.latest_version} ({info.release_name})")
            print(f"Release URL: {info.html_url}")
            if info.download_url:
                print(f"Download URL: {info.download_url}")
        else:
            print(f"You are already on the latest version of r2sync (v{APP_VERSION}).")
        return 0

    client = IPCClient()
    if not client.is_service_running():
        print("Error: r2sync background service is not running. Please start r2sync-service first (or run 'r2sync-cli tui').")
        return 1

    try:
        if args.command == "status":
            ping = client.call("ping")
            stats = client.get_summary_stats()
            print("=== r2sync Status ===")
            print(f"Service Version: {ping.get('version')}")
            print(f"Credentials Configured: {ping.get('has_credentials')}")
            print(f"Rclone Installed: {ping.get('rclone_installed')}")
            print(f"Total Jobs: {stats.get('total_jobs')} ({stats.get('active_jobs')} active)")
            print(f"Total Completed Runs: {stats.get('completed_runs')}")
            mb = round(stats.get('total_bytes_transferred', 0) / (1024 * 1024), 2)
            print(f"Total Data Transferred: {mb} MB ({stats.get('total_files_transferred', 0)} files)")
            print(f"Last Backup: {stats.get('last_backup_at') or 'Never'}")

        elif args.command == "jobs":
            if args.subcommand == "list":
                jobs = client.list_jobs()
                print(f"Found {len(jobs)} backup jobs:")
                for j in jobs:
                    status = f"[{'ACTIVE' if j.get('enabled') else 'DISABLED'}]"
                    print(f" - #{j.get('id')}: {j.get('name')} {status} | Source: {j.get('source_path')} -> Bucket: {j.get('bucket_name')}")
            elif args.subcommand == "run":
                res = client.run_job_now(args.id)
                print(f"Job #{args.id} triggered: {res}")
            elif args.subcommand == "cancel":
                res = client.cancel_job(args.id)
                print(f"Job #{args.id} cancel requested: {res}")

        elif args.command == "r2":
            if args.subcommand == "test":
                res = client.call("test_r2_connection")
                print("Connection Test Result:", json.dumps(res, indent=2))
            elif args.subcommand == "buckets":
                buckets = client.list_buckets()
                print(f"Buckets ({len(buckets)}):")
                for b in buckets:
                    print(f" - {b.get('name')}")

        elif args.command == "history":
            runs = client.list_runs(limit=10)
            print(f"Recent Runs ({len(runs)}):")
            for r in runs:
                print(f" - Run #{r.get('id')} for Job '{r.get('job_name')}': [{r.get('status').upper()}] {r.get('files_transferred')} files ({round(r.get('bytes_transferred', 0)/(1024*1024), 2)} MB) at {r.get('started_at')}")

        else:
            parser.print_help()

    except Exception as e:
        print(f"Error: {e}")
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())

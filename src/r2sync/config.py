"""Global configuration constants and metadata for r2sync."""

from r2sync import __version__

APP_NAME = "r2sync"
APP_DISPLAY_NAME = "r2sync"
# Single source of truth: r2sync/__init__.py. This value is what the IPC
# ``ping`` reply reports, so a hand-maintained copy here silently made
# ``r2sync-cli status`` claim a different build than the one actually running.
APP_VERSION = __version__
APP_AUTHOR = "r2sync contributors"
APP_DESCRIPTION = "Native, private, open-source backup tool for Cloudflare R2"

# Windows Identifiers
EXE_NAME_GUI = "r2sync.exe"
EXE_NAME_SERVICE = "r2sync-service.exe"
EXE_NAME_INSTALLER = "r2sync-setup.exe"
WINDOWS_SERVICE_NAME = "r2sync"
WINDOWS_SERVICE_DISPLAY_NAME = "r2sync Background Service"
WINDOWS_SERVICE_DESCRIPTION = "Manages automated Cloudflare R2 backups and schedules for r2sync."

# IPC Configuration
IPC_PIPE_NAME = r"\\.\pipe\r2sync_ipc"
IPC_DEFAULT_PORT = 47823
IPC_HOST = "127.0.0.1"

# Cloudflare Defaults
CLOUDFLARE_DASHBOARD_URL = "https://dash.cloudflare.com/"
CLOUDFLARE_R2_URL = "https://dash.cloudflare.com/?to=/:account/r2"
CLOUDFLARE_API_TOKENS_URL = "https://dash.cloudflare.com/?to=/:account/r2/api-tokens"
CLOUDFLARE_BILLING_URL = "https://dash.cloudflare.com/?to=/:account/billing"

# S3 / R2 Constants
R2_ENDPOINT_TEMPLATE = "https://{account_id}.r2.cloudflarestorage.com"
R2_DEFAULT_REGION = "auto"

# Default Exclude Globs
DEFAULT_EXCLUDE_PATTERNS = [
    ".git/",
    ".git/**",
    ".svn/",
    ".hg/",
    "node_modules/",
    "node_modules/**",
    "__pycache__/",
    "*.pyc",
    "*.tmp",
    "*.temp",
    "~$*",
    "Thumbs.db",
    "desktop.ini",
    ".DS_Store",
    "System Volume Information/",
    "$RECYCLE.BIN/",
]

# Rclone Defaults
RCLONE_VERSION = "v1.68.2"
RCLONE_DEFAULT_TRANSFERS = 32
RCLONE_DEFAULT_CHECKERS = 32
RCLONE_CHUNK_SIZE = "16M"
RCLONE_BUFFER_SIZE = "16M"
RCLONE_CONCURRENCY = 16

# Multi-PC Sync Constants
SYNC_PROTOCOL_VERSION = 1
SYNC_R2_ROOT = "r2sync/v1/datasets"
SYNC_DEFAULT_DEBOUNCE_SECONDS = 2.5
SYNC_DEFAULT_MAX_DELETE_THRESHOLD = 50  # Max files deleted before safety pause
SYNC_DEFAULT_MAX_DELETE_PERCENT = 20    # Max percentage of dataset deleted before safety pause
SYNC_DEFAULT_RECONCILE_INTERVAL_MINUTES = 30
# Ceiling on datasets synchronizing at the same time. Each running sync is its
# own rclone process with its own --transfers/--multi-thread-streams budget, so
# letting every dataset start at once (as happens on service startup, when all
# of them are queued for a catch-up reconcile) would oversubscribe the network
# and the local disk. Datasets over the ceiling are deferred to the next
# scheduler tick rather than dropped.
SYNC_MAX_CONCURRENT_DATASETS = 2
SYNC_DEFAULT_HEARTBEAT_INTERVAL_SECONDS = 60
# Passed to bisync as --max-lock. rclone refuses to start a run while a lock
# file for the same path pair exists, and a run killed by a crash, a reboot or
# Task Manager never removes its own lock -- which wedged the dataset
# permanently, every subsequent sync failing in a fraction of a second with
# "prior lock file found" and no way to clear it from the UI.
#
# This is safe for arbitrarily long syncs: with --max-lock set, rclone renews
# the lock file every max-lock/2 for as long as the run is alive (verified
# against v1.68.2 -- a 2m lock was rewritten every 60s mid-run), so only an
# *abandoned* lock ever expires. The value therefore only decides how long a
# dataset stays stuck after a crash, not how long a sync may take. rclone's own
# minimum is 2m; 5m leaves a comfortable margin over the 2.5m renewal cycle.
BISYNC_MAX_LOCK = "5m"

# Cloudflare R2 Pricing Reference (for UI visibility & estimation)
CLOUDFLARE_R2_STORAGE_PRICE_PER_GB_MONTH = 0.015  # $0.015 / GB-month
CLOUDFLARE_R2_FREE_TIER_GB = 10                  # First 10 GB/month free
CLOUDFLARE_R2_CLASS_A_PRICE_PER_MILLION = 4.50    # Writes, Lists, etc.
CLOUDFLARE_R2_CLASS_B_PRICE_PER_MILLION = 0.36    # Reads
CLOUDFLARE_PRICING_INFO_URL = "https://developers.cloudflare.com/r2/pricing/"

# GitHub Updates
GITHUB_REPO = "saurabhhbansal/r2sync"
GITHUB_RELEASES_API = "https://api.github.com/repos/saurabhhbansal/r2sync/releases/latest"

# Settings Keys
SETTING_SPEED_PROFILE = "speed_profile"
SETTING_AUTO_UPDATE = "auto_update"



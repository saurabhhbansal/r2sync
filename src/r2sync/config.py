"""Global configuration constants and metadata for r2sync."""

APP_NAME = "r2sync"
APP_DISPLAY_NAME = "r2sync"
APP_VERSION = "1.2.1"
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
SYNC_DEFAULT_HEARTBEAT_INTERVAL_SECONDS = 60

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



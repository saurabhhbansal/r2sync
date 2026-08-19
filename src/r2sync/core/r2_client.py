"""Cloudflare R2 integration, bucket management, and dashboard navigation."""

import logging
import webbrowser
from typing import Any, Dict, List, Optional

from r2sync.config import (
    CLOUDFLARE_API_TOKENS_URL,
    CLOUDFLARE_BILLING_URL,
    CLOUDFLARE_DASHBOARD_URL,
    CLOUDFLARE_R2_URL,
)
from r2sync.core.credentials import get_r2_credentials
from r2sync.core.models import R2BucketInfo, R2Credentials
from r2sync.core.rclone_engine import RcloneEngine

logger = logging.getLogger(__name__)


class CloudflareR2Client:
    """Client for Cloudflare R2 bucket operations and dashboard links."""

    def __init__(self, engine: Optional[RcloneEngine] = None):
        self.engine = engine or RcloneEngine()

    @staticmethod
    def get_dashboard_url(account_id: Optional[str] = None) -> str:
        if account_id:
            return f"https://dash.cloudflare.com/{account_id}/r2/overview"
        return CLOUDFLARE_DASHBOARD_URL

    @staticmethod
    def get_api_tokens_url(account_id: Optional[str] = None) -> str:
        if account_id:
            return f"https://dash.cloudflare.com/{account_id}/r2/api-tokens"
        return "https://dash.cloudflare.com/?to=/:account/r2/api-tokens"

    @staticmethod
    def get_bucket_url(bucket_name: str, account_id: Optional[str] = None) -> str:
        if account_id:
            return f"https://dash.cloudflare.com/{account_id}/r2/default/buckets/{bucket_name}"
        return f"https://dash.cloudflare.com/?to=/:account/r2/default/buckets/{bucket_name}"

    @staticmethod
    def get_billing_url(account_id: Optional[str] = None) -> str:
        if account_id:
            return f"https://dash.cloudflare.com/{account_id}/billing"
        return CLOUDFLARE_BILLING_URL

    @staticmethod
    def open_in_browser(url: str) -> bool:
        """Open official Cloudflare page safely in default web browser."""
        try:
            return webbrowser.open(url, new=2)
        except Exception as e:
            logger.error(f"Failed to open browser URL {url}: {e}")
            return False

    def test_connection(self, creds: Optional[R2Credentials] = None) -> Dict[str, Any]:
        c = creds or get_r2_credentials()
        if not c:
            return {
                "success": False,
                "buckets": [],
                "latency_ms": 0,
                "error": "No credentials configured",
                "message": "Please enter your Cloudflare Account ID, Access Key ID, and Secret Access Key.",
            }
        return self.engine.test_connection(c)

    def list_buckets(self, creds: Optional[R2Credentials] = None) -> List[R2BucketInfo]:
        c = creds or get_r2_credentials()
        if not c:
            return []

        bucket_names = self.engine.list_buckets(c)
        bucket_infos = []

        for name in bucket_names:
            info = R2BucketInfo(name=name, location="auto")
            bucket_infos.append(info)

        return bucket_infos

    def get_bucket_details(self, bucket_name: str, creds: Optional[R2Credentials] = None) -> R2BucketInfo:
        c = creds or get_r2_credentials()
        info = R2BucketInfo(name=bucket_name, location="auto")
        if c:
            size_data = self.engine.get_bucket_size(bucket_name, c)
            info.object_count = size_data.get("count", 0)
            info.size_bytes = size_data.get("bytes", 0)
        return info

    def create_bucket(self, bucket_name: str, creds: Optional[R2Credentials] = None) -> bool:
        c = creds or get_r2_credentials()
        if not c:
            raise ValueError("No credentials provided")
        return self.engine.create_bucket(bucket_name, c)

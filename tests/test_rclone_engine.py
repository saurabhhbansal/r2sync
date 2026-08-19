import platform
import pytest
from r2sync.core.models import BackupJob, BackupRun, R2Credentials
from r2sync.core.rclone_engine import RcloneBinaryManager, RcloneEngine


def test_binary_manager_arch():
    arch = RcloneBinaryManager.get_os_arch_string()
    assert "-" in arch
    url = RcloneBinaryManager.get_download_url("v1.68.2")
    assert "https://downloads.rclone.org/v1.68.2/rclone-v1.68.2-" in url
    assert url.endswith(".zip")


def test_rclone_env_variables_isolation():
    creds = R2Credentials(
        account_id="test_acc_999",
        access_key_id="test_key_aaa",
        secret_access_key="test_secret_bbb",
    )
    engine = RcloneEngine(creds)
    env = engine._build_env()

    assert env.get("RCLONE_CONFIG_R2_TYPE") == "s3"
    assert env.get("RCLONE_CONFIG_R2_PROVIDER") == "Cloudflare"
    assert env.get("RCLONE_CONFIG_R2_ACCESS_KEY_ID") == "test_key_aaa"
    assert env.get("RCLONE_CONFIG_R2_SECRET_ACCESS_KEY") == "test_secret_bbb"
    assert env.get("RCLONE_CONFIG_R2_ENDPOINT") == "https://test_acc_999.r2.cloudflarestorage.com"

import pytest
from r2sync.core.credentials import (
    CredentialVault,
    delete_r2_credentials,
    get_r2_credentials,
    has_r2_credentials,
    mask_secret,
    save_r2_credentials,
)
from r2sync.core.models import R2Credentials


def test_mask_secret():
    assert mask_secret("") == ""
    assert mask_secret("1234") == "••••"
    assert mask_secret("abcdef123456", visible_chars=4) == "••••••••3456"


def test_credential_save_and_retrieve(tmp_path, monkeypatch):
    monkeypatch.setenv("R2SYNC_DATA_DIR", str(tmp_path))
    vault = CredentialVault()
    vault.delete_credentials()

    # Initially empty
    assert not vault.has_credentials()
    assert vault.get_credentials() is None

    # Save
    success = vault.save_credentials(
        account_id="test_acc_123",
        access_key_id="test_ak_456",
        secret_access_key="test_sk_789",
        default_bucket="my-bucket",
    )
    assert success is True
    assert vault.has_credentials() is True

    creds = vault.get_credentials()
    assert creds is not None
    assert creds.account_id == "test_acc_123"
    assert creds.access_key_id == "test_ak_456"
    assert creds.secret_access_key == "test_sk_789"
    assert creds.default_bucket == "my-bucket"
    assert creds.get_endpoint() == "https://test_acc_123.r2.cloudflarestorage.com"

    # Delete
    assert vault.delete_credentials() is True
    assert not vault.has_credentials()

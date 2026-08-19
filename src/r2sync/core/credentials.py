"""Secure credential storage abstraction using Windows DPAPI / Credential Manager / Keyring."""

import base64
import json
import logging
import os
import sys
from typing import Optional

from r2sync.config import APP_NAME
from r2sync.core.models import R2Credentials

logger = logging.getLogger(__name__)

SERVICE_NAME = f"{APP_NAME}_credentials"
CREDENTIAL_USERNAME = "r2_auth_payload"


class WindowsDPAPI:
    """Direct native Windows Data Protection API (DPAPI) via ctypes."""

    @staticmethod
    def is_supported() -> bool:
        return sys.platform == "win32"

    @classmethod
    def encrypt(cls, plaintext: str) -> bytes:
        if not cls.is_supported():
            raise NotImplementedError("DPAPI is only available on Windows")
        
        import ctypes
        from ctypes import wintypes

        class DATA_BLOB(ctypes.Structure):
            _fields_ = [
                ("cbData", wintypes.DWORD),
                ("pbData", ctypes.POINTER(ctypes.c_byte)),
            ]

        data_bytes = plaintext.encode("utf-8")
        in_blob = DATA_BLOB(len(data_bytes), ctypes.cast(ctypes.create_string_buffer(data_bytes), ctypes.POINTER(ctypes.c_byte)))
        out_blob = DATA_BLOB()

        crypt32 = ctypes.windll.crypt32
        # CryptProtectData(pDataIn, szDataDescr, pOptionalEntropy, pvReserved, pPromptStruct, dwFlags, pDataOut)
        # dwFlags = 0x01 (CRYPTPROTECT_UI_FORBIDDEN)
        if not crypt32.CryptProtectData(ctypes.byref(in_blob), "r2sync_token", None, None, None, 0x01, ctypes.byref(out_blob)):
            raise ctypes.WinError()

        try:
            buffer = ctypes.string_at(out_blob.pbData, out_blob.cbData)
            return buffer
        finally:
            kernel32 = ctypes.windll.kernel32
            kernel32.LocalFree(out_blob.pbData)

    @classmethod
    def decrypt(cls, ciphertext: bytes) -> str:
        if not cls.is_supported():
            raise NotImplementedError("DPAPI is only available on Windows")

        import ctypes
        from ctypes import wintypes

        class DATA_BLOB(ctypes.Structure):
            _fields_ = [
                ("cbData", wintypes.DWORD),
                ("pbData", ctypes.POINTER(ctypes.c_byte)),
            ]

        in_blob = DATA_BLOB(len(ciphertext), ctypes.cast(ctypes.create_string_buffer(ciphertext), ctypes.POINTER(ctypes.c_byte)))
        out_blob = DATA_BLOB()

        crypt32 = ctypes.windll.crypt32
        if not crypt32.CryptUnprotectData(ctypes.byref(in_blob), None, None, None, None, 0x01, ctypes.byref(out_blob)):
            raise ctypes.WinError()

        try:
            buffer = ctypes.string_at(out_blob.pbData, out_blob.cbData)
            return buffer.decode("utf-8")
        finally:
            kernel32 = ctypes.windll.kernel32
            kernel32.LocalFree(out_blob.pbData)


class CredentialVault:
    """Universal secure credential vault managing OS-level storage."""

    def __init__(self):
        self._memory_cache: Optional[R2Credentials] = None

    def save_credentials(
        self,
        account_id: str,
        access_key_id: str,
        secret_access_key: str,
        default_bucket: Optional[str] = None,
        endpoint_url: Optional[str] = None,
    ) -> bool:
        """Securely store credentials in OS vault."""
        creds = R2Credentials(
            account_id=account_id.strip(),
            access_key_id=access_key_id.strip(),
            secret_access_key=secret_access_key.strip(),
            default_bucket=default_bucket.strip() if default_bucket else None,
            endpoint_url=endpoint_url.strip() if endpoint_url else None,
        )
        payload = json.dumps({
            "account_id": creds.account_id,
            "access_key_id": creds.access_key_id,
            "secret_access_key": creds.secret_access_key,
            "default_bucket": creds.default_bucket,
            "endpoint_url": creds.endpoint_url,
        })

        saved = False

        # 1. Try Keyring (Windows Credential Manager / SecretService)
        try:
            import keyring
            keyring.set_password(SERVICE_NAME, CREDENTIAL_USERNAME, payload)
            saved = True
        except Exception as e:
            logger.debug(f"Keyring save failed or unavailable: {e}")

        # 2. On Windows, if DPAPI is available, also store DPAPI-encrypted backup in state dir
        if WindowsDPAPI.is_supported():
            try:
                from r2sync.utils.paths import get_state_dir
                enc_bytes = WindowsDPAPI.encrypt(payload)
                enc_path = get_state_dir() / ".credentials.dpapi"
                with open(enc_path, "wb") as f:
                    f.write(enc_bytes)
                saved = True
            except Exception as e:
                logger.debug(f"DPAPI save failed: {e}")

        # 3. Fallback for non-Windows testing / headless environments without keyring backend
        if not saved:
            try:
                from r2sync.utils.paths import get_state_dir
                encoded = base64.b64encode(payload.encode("utf-8")).decode("ascii")
                fallback_path = get_state_dir() / ".credentials.vault"
                with open(fallback_path, "w", encoding="utf-8") as f:
                    f.write(encoded)
                # Restrict permissions on POSIX
                if hasattr(os, "chmod"):
                    os.chmod(fallback_path, 0o600)
                saved = True
            except Exception as e:
                logger.error(f"Fallback credential save failed: {e}")
                return False

        self._memory_cache = creds
        return saved

    def get_credentials(self) -> Optional[R2Credentials]:
        """Retrieve and decrypt stored credentials."""
        if self._memory_cache:
            return self._memory_cache

        raw_payload: Optional[str] = None

        # 1. Try Keyring
        try:
            import keyring
            stored = keyring.get_password(SERVICE_NAME, CREDENTIAL_USERNAME)
            if stored:
                raw_payload = stored
        except Exception as e:
            logger.debug(f"Keyring get failed: {e}")

        # 2. Try Windows DPAPI file
        if not raw_payload and WindowsDPAPI.is_supported():
            try:
                from r2sync.utils.paths import get_state_dir
                enc_path = get_state_dir() / ".credentials.dpapi"
                if enc_path.exists():
                    with open(enc_path, "rb") as f:
                        enc_bytes = f.read()
                    raw_payload = WindowsDPAPI.decrypt(enc_bytes)
            except Exception as e:
                logger.debug(f"DPAPI decrypt failed: {e}")

        # 3. Try Fallback file
        if not raw_payload:
            try:
                from r2sync.utils.paths import get_state_dir
                fallback_path = get_state_dir() / ".credentials.vault"
                if fallback_path.exists():
                    with open(fallback_path, "r", encoding="utf-8") as f:
                        encoded = f.read().strip()
                    raw_payload = base64.b64decode(encoded.encode("ascii")).decode("utf-8")
            except Exception as e:
                logger.debug(f"Fallback vault read failed: {e}")

        if not raw_payload:
            return None

        try:
            data = json.loads(raw_payload)
            creds = R2Credentials(
                account_id=data.get("account_id", ""),
                access_key_id=data.get("access_key_id", ""),
                secret_access_key=data.get("secret_access_key", ""),
                default_bucket=data.get("default_bucket"),
                endpoint_url=data.get("endpoint_url"),
            )
            self._memory_cache = creds
            return creds
        except Exception as e:
            logger.error(f"Failed to parse decrypted credential payload: {e}")
            return None

    def has_credentials(self) -> bool:
        creds = self.get_credentials()
        return bool(creds and creds.account_id and creds.access_key_id and creds.secret_access_key)

    def delete_credentials(self) -> bool:
        self._memory_cache = None
        deleted = False

        try:
            import keyring
            keyring.delete_password(SERVICE_NAME, CREDENTIAL_USERNAME)
            deleted = True
        except Exception:
            pass

        try:
            from r2sync.utils.paths import get_state_dir
            for name in (".credentials.dpapi", ".credentials.vault"):
                p = get_state_dir() / name
                if p.exists():
                    p.unlink()
                    deleted = True
        except Exception:
            pass

        return deleted


_vault = CredentialVault()


def save_r2_credentials(
    account_id: str,
    access_key_id: str,
    secret_access_key: str,
    default_bucket: Optional[str] = None,
    endpoint_url: Optional[str] = None,
) -> bool:
    return _vault.save_credentials(account_id, access_key_id, secret_access_key, default_bucket, endpoint_url)


def get_r2_credentials() -> Optional[R2Credentials]:
    return _vault.get_credentials()


def has_r2_credentials() -> bool:
    return _vault.has_credentials()


def delete_r2_credentials() -> bool:
    return _vault.delete_credentials()


def mask_secret(secret: str, visible_chars: int = 4) -> str:
    """Mask a sensitive string for UI preview (e.g., '••••••••••••abcd')."""
    if not secret:
        return ""
    if len(secret) <= visible_chars:
        return "•" * len(secret)
    return "•" * (len(secret) - visible_chars) + secret[-visible_chars:]

# ------------------------------------------------------------------------------
# This module provides a small keychain wrapper for persistent iCloud
# credential storage.
# ------------------------------------------------------------------------------

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import os

import keyring
from keyrings.alt.file import PlaintextKeyring


# ------------------------------------------------------------------------------
# This data class describes the explicit keyring bootstrap side effects.
# ------------------------------------------------------------------------------
@dataclass(frozen=True)
class KeyringBootstrap:
    keyring_file_path: Path


# ------------------------------------------------------------------------------
# This function configures a deterministic file-based keyring path.
#
# 1. "config_dir" is the root directory used for worker runtime state.
#
# Returns: "KeyringBootstrap" describing the applied bootstrap path.
#
# N.B.
# This bootstrap sets the "PYTHON_KEYRING_FILENAME" environment variable for
# the current process and points the plaintext backend at the same file. The
# file path stays explicit, but no broader XDG or home-directory state is
# changed for the process.
#
# Notes: File keyring keeps credentials in mounted container volumes.
# ------------------------------------------------------------------------------
def configure_keyring(CONFIG_DIR: Path) -> KeyringBootstrap:
    KEYRING_DIR = CONFIG_DIR / "keyring"
    KEYRING_FILE_PATH = KEYRING_DIR / "keyring_pass.cfg"
    KEYRING_DIR.mkdir(parents=True, exist_ok=True)
    os.environ["PYTHON_KEYRING_FILENAME"] = str(KEYRING_FILE_PATH)

    KEYRING_BACKEND = PlaintextKeyring()
    KEYRING_BACKEND.file_path = str(KEYRING_FILE_PATH)
    keyring.set_keyring(KEYRING_BACKEND)
    return KeyringBootstrap(KEYRING_FILE_PATH)


# ------------------------------------------------------------------------------
# This function reads credentials from keyring storage.
# 1. "service_name" scopes credentials.
# 2. "username" identifies the account key prefix.
# Returns: Tuple "(email, password)" with empty-string fallbacks.
# ------------------------------------------------------------------------------
def load_credentials(SERVICE_NAME: str, USERNAME: str) -> tuple[str, str]:
    EMAIL = keyring.get_password(SERVICE_NAME, f"{USERNAME}:email") or ""
    PASSWORD = keyring.get_password(SERVICE_NAME, f"{USERNAME}:password") or ""
    return EMAIL, PASSWORD


# ------------------------------------------------------------------------------
# This function writes credentials to keyring storage when values are available.
# 1. "service_name" scopes credentials.
# 2. "username" identifies keys.
# 3. "email" and "password" are values to store.
# Returns: "None".
# ------------------------------------------------------------------------------
def save_credentials(
    SERVICE_NAME: str,
    USERNAME: str,
    EMAIL: str,
    PASSWORD: str,
) -> None:
    if EMAIL:
        keyring.set_password(SERVICE_NAME, f"{USERNAME}:email", EMAIL)

    if PASSWORD:
        keyring.set_password(SERVICE_NAME, f"{USERNAME}:password", PASSWORD)

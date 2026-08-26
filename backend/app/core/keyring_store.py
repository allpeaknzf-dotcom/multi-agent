"""API Key 安全存储：值存入系统钥匙串（keyring），数据库只保留引用名。"""
from __future__ import annotations

import keyring

# keyring service 名（macOS 上会落到 Keychain 里）
_SERVICE = "com.multiagent.app"


def save_key(key_ref: str, value: str) -> None:
    keyring.set_password(_SERVICE, key_ref, value)


def get_key(key_ref: str) -> str | None:
    return keyring.get_password(_SERVICE, key_ref)


def delete_key(key_ref: str) -> None:
    try:
        keyring.delete_password(_SERVICE, key_ref)
    except keyring.errors.PasswordDeleteError:
        pass

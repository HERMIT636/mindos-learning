"""Encrypt local provider credentials outside the project checkout."""

from __future__ import annotations

import os
import threading
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken


class SecretStore:
    def __init__(self, key_path: Path | None = None) -> None:
        self.key_path = key_path or Path.home() / ".config" / "mindos" / "master.key"
        self._fernet: Fernet | None = None
        self._lock = threading.Lock()

    def _cipher(self) -> Fernet:
        if self._fernet is not None:
            return self._fernet
        with self._lock:
            if self._fernet is not None:
                return self._fernet
            self.key_path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            if self.key_path.is_symlink():
                raise ValueError("本机模型密钥文件不能是符号链接")
            try:
                fd = os.open(self.key_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            except FileExistsError:
                pass
            else:
                with os.fdopen(fd, "wb") as stream:
                    stream.write(Fernet.generate_key())
            if os.name != "nt" and self.key_path.stat().st_mode & 0o077:
                raise ValueError("本机模型密钥文件权限过宽，请限制为仅本人可读写")
            key = self.key_path.read_bytes().strip()
            try:
                self._fernet = Fernet(key)
            except (ValueError, TypeError) as exc:
                raise ValueError("本机模型密钥文件无效，请恢复原密钥文件") from exc
        return self._fernet

    def encrypt(self, value: str) -> str:
        return self._cipher().encrypt(value.encode("utf-8")).decode("ascii") if value else ""

    def decrypt(self, token: str) -> str:
        if not token:
            return ""
        cipher = self._cipher()
        try:
            return cipher.decrypt(token.encode("ascii")).decode("utf-8")
        except (InvalidToken, UnicodeDecodeError, ValueError) as exc:
            raise ValueError("保存的 API 密钥无法解密，请检查本机主密钥文件") from exc

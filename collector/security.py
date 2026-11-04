# -*- coding: utf-8 -*-
"""凭据安全：本地密钥 + AES-256-GCM 加密存储、手机号脱敏、文件权限收紧。

三条原则：

1. **明文密码不落盘**。默认只把登录后的 cookie 存盘（cookie 本来就是登录凭证），
   密码只留在进程内存里；只有用户勾了"记住密码"才用本机密钥加密后写 `password_enc`。
2. **密钥与配置分离**。`secret.key` 单独一个文件，权限收紧到只有当前用户能读；
   拿到 config.json 也解不开。
3. **不外泄**。接口不返回密码、日志不打印密码，手机号对外一律脱敏（只保留前 3 位与后 4 位）。
"""

from __future__ import annotations

import base64
import getpass
import os
import subprocess
import sys

from Crypto.Cipher import AES
from Crypto.Random import get_random_bytes

KEY_FILE = "secret.key"
KEY_BYTES = 32          # AES-256
NONCE_BYTES = 12
TAG_BYTES = 16


# ---------------------------------------------------------------- 文件权限

def harden(path: str) -> None:
    """把文件权限收紧到仅当前用户（Windows 用 icacls，类 Unix 用 chmod 600）。"""
    try:
        if sys.platform == "win32":
            user = os.environ.get("USERNAME") or getpass.getuser()
            subprocess.run(
                ["icacls", path, "/inheritance:r", "/grant:r", f"{user}:F"],
                capture_output=True, timeout=15, check=False,
            )
        else:
            os.chmod(path, 0o600)
    except Exception:
        # 权限收紧失败不阻断主流程，但要在日志里说一声
        print(f"[warn] 收紧文件权限失败（不影响使用）: {path}")


# ---------------------------------------------------------------- 密钥

def key_path(config_dir: str) -> str:
    return os.path.join(config_dir, KEY_FILE)


def load_or_create_key(config_dir: str) -> bytes:
    """读取本机密钥；没有就生成一个 32 字节随机密钥并收紧权限。"""
    path = key_path(config_dir)
    if os.path.exists(path):
        try:
            with open(path, "rb") as f:
                raw = f.read().strip()
            key = base64.b64decode(raw)
            if len(key) == KEY_BYTES:
                return key
            print("[warn] secret.key 长度异常，重新生成")
        except Exception as e:
            print(f"[warn] secret.key 读取失败，重新生成: {e}")
    key = get_random_bytes(KEY_BYTES)
    os.makedirs(config_dir, exist_ok=True)
    with open(path, "wb") as f:
        f.write(base64.b64encode(key))
    harden(path)
    return key


# ---------------------------------------------------------------- 加解密

def encrypt_secret(plaintext: str, key: bytes) -> str:
    """AES-256-GCM 加密，返回 base64(nonce + tag + 密文)。"""
    cipher = AES.new(key, AES.MODE_GCM, nonce=get_random_bytes(NONCE_BYTES))
    ciphertext, tag = cipher.encrypt_and_digest(plaintext.encode("utf-8"))
    return base64.b64encode(cipher.nonce + tag + ciphertext).decode("ascii")


def decrypt_secret(blob: str, key: bytes) -> str | None:
    """解密；密钥不对/数据被改过时返回 None（GCM 会校验 tag）。"""
    try:
        raw = base64.b64decode(blob)
        nonce, tag, ciphertext = (raw[:NONCE_BYTES],
                                  raw[NONCE_BYTES:NONCE_BYTES + TAG_BYTES],
                                  raw[NONCE_BYTES + TAG_BYTES:])
        cipher = AES.new(key, AES.MODE_GCM, nonce=nonce)
        return cipher.decrypt_and_verify(ciphertext, tag).decode("utf-8")
    except Exception:
        return None


# ---------------------------------------------------------------- 脱敏

def mask_phone(phone: str | None) -> str:
    """保留前 3 位与后 4 位，中间用 * 打码；太短就整体打码。"""
    s = str(phone or "").strip()
    if not s:
        return ""
    if len(s) <= 4:
        return "*" * len(s)
    if len(s) <= 7:
        return s[:1] + "*" * (len(s) - 2) + s[-1:]
    return s[:3] + "*" * (len(s) - 7) + s[-4:]

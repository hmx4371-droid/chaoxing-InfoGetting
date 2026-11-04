# -*- coding: utf-8 -*-
"""学习通采集服务（FastAPI，默认 :8801）。

职责单一：登录学习通 → 抓作业/课表/考试/通知 → 组装统一 JSON 给 Java 后端。
本服务不连数据库、不做业务判断，重启只丢内存缓存（cookie 和上次结果在 data/ 里）。

凭据安全（见 security.py）：
- 密码默认只在进程内存里，不落盘；勾"记住密码"才用本机密钥 AES-256-GCM 加密存 password_enc
- 接口不返回密码（手机号一律脱敏），日志不打印密码

启动：
    python -m uvicorn main:app --host 127.0.0.1 --port 8801
"""

from __future__ import annotations

import json
import os
import threading
import time
import traceback
from datetime import datetime

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from chaoxing.client import ChaoxingClient, _TZ_CN
from chaoxing.collect import collect
from chaoxing.mock import mock_payload
from security import (decrypt_secret, encrypt_secret, harden, load_or_create_key,
                      mask_phone)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE = os.path.join(BASE_DIR, "config.json")
DATA_DIR = os.path.join(BASE_DIR, "data")
LAST_SYNC_FILE = os.path.join(DATA_DIR, "last_sync.json")
COOKIE_FILE = os.path.join(BASE_DIR, "session_cookies.json")

VERSION = "0.2.0"
app = FastAPI(title="学习通采集服务", version=VERSION)
app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"],
)


# ---------------------------------------------------------------- 配置读写

def read_config() -> dict:
    """每次读盘，改 config.json 不用重启（mock 开关、节流间隔即时生效）。

    用 utf-8-sig 读取：Windows 记事本/PowerShell 存 UTF-8 时可能带 BOM，
    带 BOM 的 JSON 用普通 utf-8 解码会解析失败，表现就是"改了配置不生效"。
    """
    try:
        with open(CONFIG_FILE, encoding="utf-8-sig") as f:
            return json.load(f) or {}
    except FileNotFoundError:
        return {}
    except Exception as e:
        print(f"[warn] config.json 解析失败: {e}")
        return {}


def write_config(cfg: dict) -> None:
    os.makedirs(BASE_DIR, exist_ok=True)
    tmp = CONFIG_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)
    os.replace(tmp, CONFIG_FILE)
    harden(CONFIG_FILE)


def is_mock(cfg: dict | None = None) -> bool:
    if os.environ.get("CHAOXING_MOCK") == "1":
        return True
    cfg = cfg if cfg is not None else read_config()
    return bool(cfg.get("mock"))


def config_writable_defaults() -> None:
    """首次运行自动生成一份 config.json（不覆盖已有的）。"""
    if os.path.exists(CONFIG_FILE):
        return
    write_config({
        "phone": "", "password_enc": "", "remember": False,
        "mock": True, "throttle": 0.5, "notice_limit": 40, "with_details": True,
    })


# ---------------------------------------------------------------- 凭据

class CredentialStore:
    """凭据读取与保存：明文密码永不落盘。

    优先级：进程内存（刚登录过） > 加密存储 password_enc > 环境变量。
    老版本 config.json 里的明文 `password` 会在启动时迁移成加密存储并清空。
    """

    def __init__(self, config_dir: str):
        self.config_dir = config_dir
        self._mem_password = ""
        self._key: bytes | None = None

    def _secret_key(self) -> bytes:
        if self._key is None:
            self._key = load_or_create_key(self.config_dir)
        return self._key

    def credentials(self) -> tuple[str, str]:
        cfg = read_config()
        phone = str(cfg.get("phone") or os.environ.get("CHAOXING_PHONE") or "").strip()
        password = self._mem_password

        if not password:
            blob = cfg.get("password_enc") or ""
            if blob:
                password = decrypt_secret(blob, self._secret_key()) or ""
                if not password:
                    print("[warn] password_enc 解密失败（密钥可能被换过），需要重新登录")
        if not password:
            password = os.environ.get("CHAOXING_PASSWORD") or ""

        legacy = str(cfg.get("password") or "")
        if not password and legacy:
            # 老版本明文密码：迁移成加密存储，顺手清掉明文
            print("[info] 检测到 config.json 里的明文密码，正在迁移为加密存储")
            password = legacy
            self.save(phone, password, remember=True)

        return phone, password

    def save(self, phone: str, password: str, remember: bool) -> None:
        """保存凭据：phone 存明文（要知道 cookie 属于谁），password 只存密文。"""
        cfg = read_config()
        cfg["phone"] = phone.strip()
        cfg["password"] = ""          # 永不写明文
        cfg["remember"] = bool(remember)
        cfg["password_enc"] = encrypt_secret(password, self._secret_key()) if remember else ""
        self._mem_password = password
        write_config(cfg)

    def forget_password(self) -> None:
        """退出登录：清掉内存与加密存储里的密码（cookie 另行清除）。"""
        cfg = read_config()
        self._mem_password = ""
        cfg["password"] = ""
        cfg["password_enc"] = ""
        cfg["remember"] = False
        write_config(cfg)

    def remember(self) -> bool:
        return bool(read_config().get("remember"))

    def masked_phone(self) -> str:
        phone, _ = self.credentials()
        return mask_phone(phone)


STORE = CredentialStore(BASE_DIR)


# ---------------------------------------------------------------- 单例客户端 + 同步状态

_client: ChaoxingClient | None = None
_client_lock = threading.Lock()


def get_client(force_new: bool = False) -> ChaoxingClient:
    """全局单例：复用 session/cookie 与各类缓存，避免每轮请求重复登录。"""
    global _client
    with _client_lock:
        if _client is None or force_new:
            cfg = read_config()
            phone, password = STORE.credentials()
            _client = ChaoxingClient(
                config_dir=BASE_DIR,
                phone=phone or None,
                password=password or None,
                throttle=float(cfg.get("throttle", 0.5)),
            )
        return _client


class SyncState:
    """一轮同步的运行状态（进程内，供 Java/前端轮询）。"""

    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.state = "idle"          # idle | running | done | error
        self.started_at: str | None = None
        self.finished_at: str | None = None
        self.error: str | None = None
        self.stats: dict | None = None
        self.payload: dict | None = None
        self.logs: list[str] = []

    def snapshot(self) -> dict:
        with self.lock:
            return {
                "state": self.state,
                "started_at": self.started_at,
                "finished_at": self.finished_at,
                "error": self.error,
                "stats": self.stats,
                "has_data": self.payload is not None,
                "synced_at": (self.payload or {}).get("synced_at"),
                "mock": bool((self.payload or {}).get("mock")),
                "logs": list(self.logs[-40:]),
            }


SYNC = SyncState()

# 账号资料缓存：姓名/学校不会常变，页面每 20 秒问一次没必要每次都打学习通
_profile_cache: dict = {"at": 0.0, "data": None}
PROFILE_TTL = 300.0


def cached_profile(client: ChaoxingClient, ttl: float = PROFILE_TTL) -> dict:
    """取账号资料（姓名/学校），带缓存；取失败时退回上次结果而不是返回空。"""
    now = time.time()
    if _profile_cache["data"] and now - _profile_cache["at"] < ttl:
        return _profile_cache["data"]
    try:
        profile = client.fetch_profile()
        if profile and profile.get("name") not in (None, "", "?"):
            _profile_cache.update(at=now, data=profile)
            return profile
        return _profile_cache["data"] or profile or {}
    except Exception:
        return _profile_cache["data"] or {}


def invalidate_profile_cache() -> None:
    """换账号时必须清掉，否则页面还显示上一个号的姓名。"""
    _profile_cache.update(at=0.0, data=None)


def _now_iso() -> str:
    return datetime.now(_TZ_CN).isoformat(timespec="seconds")


def load_last_payload() -> None:
    """进程启动时把上次结果读回内存，前端一打开就有数据。"""
    if not os.path.exists(LAST_SYNC_FILE):
        return
    try:
        with open(LAST_SYNC_FILE, encoding="utf-8") as f:
            SYNC.payload = json.load(f)
        SYNC.state = "done"
        SYNC.stats = SYNC.payload.get("stats")
        SYNC.finished_at = SYNC.payload.get("synced_at")
        print(f"[info] 已加载上次同步结果: {SYNC.finished_at}")
    except Exception as e:
        print(f"[warn] 上次同步结果读取失败: {e}")


def save_payload(payload: dict) -> None:
    os.makedirs(DATA_DIR, exist_ok=True)
    tmp = LAST_SYNC_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False)
    os.replace(tmp, LAST_SYNC_FILE)


def _run_sync(with_details: bool) -> None:
    """后台线程主体：采集 → 保存。异常只落到状态里，不抛出。"""
    log = lambda msg: (SYNC.logs.append(msg), print(msg, flush=True))  # noqa: E731
    try:
        cfg = read_config()
        if is_mock(cfg):
            log("[mock] 使用假数据（config.json 里 mock=true）")
            payload = mock_payload(with_details)
        else:
            client = get_client(force_new=True)   # 每轮新会话：重新读凭据
            payload = collect(client, with_details=with_details,
                              notice_limit=int(cfg.get("notice_limit", 40)), log=log)
        save_payload(payload)
        with SYNC.lock:
            SYNC.payload = payload
            SYNC.stats = payload.get("stats")
            SYNC.state = "done"
            SYNC.finished_at = _now_iso()
            SYNC.error = None
        log(f"[done] 采集完成，共 {len(payload.get('items', []))} 条")
    except Exception as e:
        traceback.print_exc()
        with SYNC.lock:
            SYNC.state = "error"
            SYNC.error = str(e) or e.__class__.__name__
            SYNC.finished_at = _now_iso()
        log(f"[error] {SYNC.error}")


def start_sync(with_details: bool = True) -> bool:
    """启动一轮同步；已有任务在跑时返回 False。"""
    with SYNC.lock:
        if SYNC.state == "running":
            return False
        SYNC.state = "running"
        SYNC.started_at = _now_iso()
        SYNC.finished_at = None
        SYNC.error = None
        SYNC.logs = []
    threading.Thread(target=_run_sync, args=(with_details,), daemon=True).start()
    return True


# ---------------------------------------------------------------- 接口

class LoginBody(BaseModel):
    phone: str
    password: str
    remember: bool = True


@app.on_event("startup")
def _startup() -> None:
    config_writable_defaults()
    load_last_payload()
    # 老版本的明文密码迁移（顺带清掉明文）
    STORE.credentials()


def _account_view(client: ChaoxingClient | None, logged_in: bool, msg: str) -> dict:
    """账号信息对外视图：手机号脱敏，绝不含密码。"""
    profile = cached_profile(client) if (logged_in and client is not None) else {}
    return {
        "logged_in": logged_in,
        "msg": msg,
        "name": (profile or {}).get("name") or "",
        "school": (profile or {}).get("school") or "",
        "uid": (profile or {}).get("uid") or "",
        "phone_masked": STORE.masked_phone(),
        "remember": STORE.remember(),
        "has_cookie": os.path.exists(COOKIE_FILE),
    }


@app.get("/api/health")
def health() -> dict:
    cfg = read_config()
    phone, password = STORE.credentials()
    return {
        "ok": True, "service": "chaoxing-collector", "version": VERSION,
        "mock": is_mock(cfg),
        "has_credentials": bool(phone and password),
        "has_cookie": os.path.exists(COOKIE_FILE),
        "phone_masked": mask_phone(phone),
    }


@app.get("/api/account")
def account(check: bool = True) -> dict:
    """当前账号（脱敏）：登录状态、姓名、学校、手机号掩码、是否记住了密码。"""
    cfg = read_config()
    if is_mock(cfg):
        return {"logged_in": True, "msg": "假数据模式", "mock": True,
                "name": "演示同学", "school": "演示大学", "uid": "000000",
                "phone_masked": STORE.masked_phone(), "remember": STORE.remember(),
                "has_cookie": os.path.exists(COOKIE_FILE)}
    if not check:
        return {"logged_in": None, "mock": False, **_account_view(None, False, "")}
    client = get_client()
    res = client.ensure_login()
    view = _account_view(client, res.ok, res.msg)
    view["mock"] = False
    return view

@app.get("/api/login/status")
def login_status() -> dict:
    """兼容旧接口（等价于 GET /api/account）。"""
    return account()


@app.post("/api/login")
def login(body: LoginBody) -> dict:
    """用账号密码登录学习通。

    密码只经内存与本机密钥加密后使用，不写明文、不回显。
    """
    phone = body.phone.strip()
    if not phone or not body.password:
        return {"ok": False, "msg": "手机号和密码都不能为空"}
    if is_mock():
        return {"ok": True, "msg": "假数据模式，无需登录"}

    STORE.save(phone, body.password, body.remember)
    invalidate_profile_cache()
    client = get_client(force_new=True)
    res = client.login(phone, body.password)
    if not res.ok:
        return {"ok": False, "msg": res.msg}
    return {"ok": True, "msg": res.msg, "account": _account_view(client, True, res.msg)}


@app.post("/api/logout")
def logout() -> dict:
    """退出登录：清 cookie 与已保存的密码。"""
    try:
        get_client()._drop_session()
    except Exception:
        pass
    invalidate_profile_cache()
    STORE.forget_password()
    return {"ok": True, "msg": "已退出登录，cookie 与保存的密码都已清除"}


@app.post("/api/sync")
def sync(with_details: bool = True) -> dict:
    """触发一轮采集（异步，立刻返回；进度查 /api/sync/status）。"""
    started = start_sync(with_details)
    return {"started": started, **SYNC.snapshot()}


@app.get("/api/sync/status")
def sync_status() -> dict:
    return SYNC.snapshot()


@app.get("/api/data")
def data() -> dict:
    """最近一次成功的采集结果（统一 JSON）。"""
    payload = SYNC.payload
    if not payload:
        raise HTTPException(status_code=404, detail="还没有同步过，请先调用 POST /api/sync")
    return payload


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8801)

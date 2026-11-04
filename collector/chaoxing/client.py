# -*- coding: utf-8 -*-
"""学习通（超星）只读 HTTP 客户端：会话、登录、四类数据接口。

移植自参考项目 2「xuexitong-cli」的 xuexitong_mcp/client.py（MIT 协议），
只保留本 demo 需要的能力：作业 / 课表 / 考试 / 通知。

铁律：全部是只读查询，不做签到、刷课、答题、提交等任何写操作。

凭据优先级：显式参数 > 环境变量 CHAOXING_PHONE/CHAOXING_PASSWORD > config.json
"""

from __future__ import annotations

import base64
import html as html_mod
import json
import os
import re
import threading
import time
from dataclasses import dataclass
from datetime import date, datetime, time as dtime, timedelta, timezone
from urllib.parse import parse_qs, unquote, urlparse

import requests
from Crypto.Cipher import AES
from Crypto.Util.Padding import pad
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# ---------------------------------------------------------------- 常量

TIMEOUT = 20.0                    # 常规接口超时（秒）
LOGIN_STATE_TTL = 300.0           # 登录探测结果缓存 5 分钟
COURSES_CACHE_TTL = 300.0         # 课程列表缓存 5 分钟
HOMEWORK_CACHE_TTL = 120.0        # 单课作业列表缓存 2 分钟
DEFAULT_THROTTLE = 0.5            # 请求最小间隔（秒），"温和人类"节流
_TZ_CN = timezone(timedelta(hours=8))  # 学习通时间戳均为北京时间

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/118.0.0.0 Safari/537.36")
AES_KEY = AES_IV = b"u2oh6Vu^HWe4_AES"

URL_LOGIN = "https://passport2.chaoxing.com/fanyalogin"
URL_BASE = "https://i.chaoxing.com/base"
URL_SCHEDULE = "https://kb.chaoxing.com/pc/curriculum/getMyLessons"
URL_COURSELIST = "https://mooc2-ans.chaoxing.com/mooc2-ans/visit/courselistdata"
URL_STUMIDDLE = "https://mooc1.chaoxing.com/visit/stucoursemiddle"
URL_WORKLIST = "https://mooc1.chaoxing.com/mooc2/work/list"
URL_EXAMLIST = "https://mooc1-api.chaoxing.com/exam-ans/exam/test/examcode/examlist"
URL_NOTICELIST = "https://notice.chaoxing.com/pc/notice/getNoticeList"

# 命中任一标记即视为"登录态已失效、跳到了登录页"
LOGIN_MARKERS = ("passport2.chaoxing.com/login", "用户登录")


# ---------------------------------------------------------------- 纯函数（可独立单测）

def aes_encrypt(text: str) -> str:
    """学习通登录参数的 AES-128-CBC/PKCS7 加密 + base64（key=iv 为固定值）。"""
    cipher = AES.new(AES_KEY, AES.MODE_CBC, AES_IV)
    return base64.b64encode(cipher.encrypt(pad(text.encode("utf-8"), 16))).decode()


def strip_tags(text: str) -> str:
    """去掉 script/style/HTML 标签并压缩空白，得到可读纯文本。"""
    text = re.sub(r"<script[\s\S]*?</script>|<style[\s\S]*?</style>", " ", text)
    text = re.sub(r"<[^>]+>", " ", text)
    return html_mod.unescape(" ".join(text.split()))


def hidden_value(page_html: str, input_id: str) -> str:
    """提取页面里 <input type="hidden" id="X" value="Y"> 的 value。"""
    m = re.search(r'id="%s"[^>]*value="([^"]*)"' % input_id, page_html) or \
        re.search(r'value="([^"]*)"[^>]*id="%s"' % input_id, page_html)
    return m.group(1) if m else ""


def parse_courses(html: str) -> list[dict]:
    """从 courselistdata 页面 HTML 解析课程列表。

    返回 [{name, teacher, courseid, clazzid, cpi}]，按出现顺序去重。
    """
    courses, seen = [], set()
    for m in re.finditer(r"stucoursemiddle\?courseid=(\d+)&clazzid=(\d+)&cpi=(\d+)", html):
        cid, clazz, cpi = m.groups()
        if (cid, clazz, cpi) in seen:
            continue
        seen.add((cid, clazz, cpi))
        seg = html[m.end():m.end() + 2500]
        nm = re.search(r'course-name[^>]*title="([^"]+)"', seg)
        # 老师在 <p class="line2 color3" title="姓名">（color2 是学校名，别取错）
        teacher = ""
        tp = re.search(r'<p class="line2 color3"[^>]*title="([^"]+)"', seg)
        if tp:
            teacher = tp.group(1).strip()
        else:
            for pm in re.finditer(r'<p class="overHidden2"[^>]*>([^<]{2,15})</p>', seg):
                txt = pm.group(1).strip()
                if txt and txt != (nm.group(1) if nm else ""):
                    teacher = txt
                    break
        courses.append({
            "name": html_mod.unescape(nm.group(1)) if nm else "?",
            "teacher": html_mod.unescape(teacher),
            "courseid": cid, "clazzid": clazz, "cpi": cpi,
        })
    return courses


def notice_course_name(notice: dict) -> str:
    """从通知的 extendParam.cparams 里取课程名（两层都是 JSON 字符串）。"""
    try:
        ext = notice.get("extendParam")
        if isinstance(ext, str):
            ext = json.loads(ext)
        cp = (ext or {}).get("cparams")
        if isinstance(cp, str):
            cp = json.loads(cp)
        content = ((cp or {}).get("funConfig") or {}).get("content") or {}
        return str(content.get("courseName") or "")
    except Exception:
        return ""


def parse_notice_attachments(notice: dict) -> list[dict]:
    """解析通知里的作业附件。

    学习通把「作业」通知的 courseId / classId / workId 塞在 attachment 里
    （一个 JSON 字符串），这是拿不到课程列表时反查作业的唯一入口。
    """
    raw = notice.get("attachment")
    items: list = []
    if isinstance(raw, str) and raw.strip():
        try:
            items = json.loads(raw)
        except Exception:
            items = []
    elif isinstance(raw, list):
        items = raw
    out = []
    for a in items or []:
        web = (a or {}).get("att_web") or {}
        if web.get("examOrWork") != "work":
            continue
        out.append({
            "work_id": str(web.get("examOrWorkId") or ""),
            "course_id": str(web.get("courseId") or ""),
            "class_id": str(web.get("clazzId") or ""),
            "title": (web.get("title") or "").strip(),
            "time_text": (web.get("content") or "").strip(),
            "url": web.get("url") or "",
            "course_name": notice_course_name(notice),
        })
    return out


def parse_homework_detail(html: str) -> dict:
    """从作业详情页提取标题/题量/满分/作答起止/得分（解析不到就留 None）。"""
    text = strip_tags(html)
    out = {"title": None, "question_count": None, "full_score": None,
           "start_time": None, "deadline": None, "score": None}
    m = re.search(r"题量[:：]", text)
    if m:
        head = text[:m.start()]
        k = head.rfind("作业详情")
        if k >= 0:
            title = head[k + 4:].strip()
            if title:
                out["title"] = title
    m = re.search(r"题量[:：]\s*(\d+)", text)
    if m:
        out["question_count"] = int(m.group(1))
    m = re.search(r"满分[:：]\s*(\d+)", text)
    if m:
        out["full_score"] = int(m.group(1))
    m = re.search(r"作答时间[:：]\s*(\d{1,2}-\d{1,2}\s+\d{1,2}:\d{2})\s*至\s*"
                  r"(\d{1,2}-\d{1,2}\s+\d{1,2}:\d{2})", text)
    if m:
        out["start_time"], out["deadline"] = m.group(1), m.group(2)
    else:
        # 新版页面把起止拆成两行（"作答开始时间: 11-04 14:37"），且老师可以不设截止
        m2 = re.search(r"作答(?:开始)?时间[:：]\s*(\d{1,2}-\d{1,2}\s+\d{1,2}:\d{2})", text)
        if m2:
            out["start_time"] = m2.group(1)
        m3 = re.search(r"(?:作答)?(?:截止|结束)时间[:：]\s*(\d{1,2}-\d{1,2}\s+\d{1,2}:\d{2})", text)
        if m3:
            out["deadline"] = m3.group(1)
    m = (re.search(r"智能分析\s*(\d+(?:\.\d+)?)\s*分", text)
         or re.search(r"(?:得分|总评|成绩|批阅)[:：]?\s*(\d+(?:\.\d+)?)\s*分", text))
    if m:
        out["score"] = m.group(1)
    return out


def compress_weeks(weeks) -> str:
    """[1,2,3,5] → "1-3,5"。"""
    out: list[str] = []
    start = prev = None
    for w in sorted({int(x) for x in weeks}):
        if prev is not None and w == prev + 1:
            out[-1] = f"{start}-{w}"
        else:
            start = w
            out.append(str(w))
        prev = w
    return ",".join(out)


def ms_to_date(ms) -> date | None:
    """毫秒时间戳 → 北京时间日期（课表 firstWeekDate 等均为北京时区）。"""
    try:
        return datetime.fromtimestamp(int(ms) / 1000, tz=_TZ_CN).date()
    except (TypeError, ValueError):
        return None


def parse_section_times(config_array) -> list[tuple[dtime, dtime]]:
    """lessonTimeConfigArray（["8:00-8:50", ...]）→ 按节次的 (上课, 下课) 时间表。"""
    out: list[tuple[dtime, dtime]] = []
    for item in config_array or []:
        m = re.match(r"(\d{1,2}):(\d{2})-(\d{1,2}):(\d{2})", str(item).strip())
        if m:
            h1, m1, h2, m2 = map(int, m.groups())
            out.append((dtime(h1, m1), dtime(h2, m2)))
    return out


def parse_exam_rows(raw_rows) -> list[dict]:
    """考试列表 tds 行 → 结构化行。

    列序：tds[1] 名称 tds[2] 时间 tds[3] 时长 tds[4] 考试状态
    tds[5] 作答状态 tds[6] 分数 tds[7] 方式。解析失败整行跳过。
    """
    out = []
    for tds in raw_rows:
        if not isinstance(tds, list) or len(tds) < 8:
            continue
        name, time_s = (tds[1] or "").strip(), (tds[2] or "").strip()
        m = re.match(r"(\d{4}-\d{2}-\d{2})\s+(\d{1,2}:\d{2})", time_s)
        e = re.search(r"至\s*(\d{4}-\d{2}-\d{2})\s+(\d{1,2}:\d{2})", time_s)
        if not name or not m:
            continue
        try:
            start = datetime.strptime(f"{m.group(1)} {m.group(2)}", "%Y-%m-%d %H:%M")
            end = datetime.strptime(f"{e.group(1)} {e.group(2)}",
                                    "%Y-%m-%d %H:%M") if e else start
        except ValueError:
            continue
        out.append({"name": name, "start": start, "end": end,
                    "durationMin": (tds[3] or "").strip(),
                    "status": (tds[4] or "").strip(),
                    "answer": (tds[5] or "").strip(),
                    "score": (tds[6] or "").strip(),
                    "mode": (tds[7] or "").strip()})
    return out


def nearest_datetime_for(month_day: str, today: date) -> datetime | None:
    """作业详情的作答时间只有 "MM-DD HH:MM"，取与今天最接近的年份补全。"""
    m = re.match(r"(\d{1,2})-(\d{1,2})\s+(\d{1,2}):(\d{2})", str(month_day).strip())
    if not m:
        return None
    mo, d, hh, mm = map(int, m.groups())
    best: datetime | None = None
    for year in (today.year - 1, today.year, today.year + 1):
        try:
            cand = datetime(year, mo, d, hh, mm)
        except ValueError:
            continue
        if best is None or abs((cand.date() - today).days) < abs((best.date() - today).days):
            best = cand
    return best


_DONE_MARKS = ("已完成", "已提交", "待批阅", "已批阅", "已批改")


def is_homework_pending(status: str) -> bool:
    """作业是否"还没交/需要关注"（已完成、已提交、待批阅都不算）。"""
    s = (status or "").strip()
    return not any(mark in s for mark in _DONE_MARKS)


# ---------------------------------------------------------------- 客户端

@dataclass
class AuthResult:
    ok: bool
    msg: str


class ChaoxingClient:
    """学习通 Web 端只读客户端。

    会话 cookie 持久化到 config_dir/session_cookies.json，跨进程复用免重复登录。
    """

    def __init__(self, config_dir: str | None = None,
                 phone: str | None = None, password: str | None = None,
                 timeout: float = TIMEOUT, throttle: float = DEFAULT_THROTTLE):
        config_dir = config_dir or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        self.config_dir = config_dir
        self.config_file = os.path.join(self.config_dir, "config.json")
        self.cookie_file = os.path.join(self.config_dir, "session_cookies.json")
        self.timeout = timeout
        self.throttle = max(0.0, float(throttle))
        self._explicit_phone = phone
        self._explicit_password = password
        self._login_checked_at = 0.0
        self._base_html: str | None = None
        self._courses_cache: list[dict] | None = None
        self._courses_cache_at = 0.0
        self._hw_cache: dict[tuple, tuple[float, dict]] = {}
        self._last_request_at = 0.0
        self._throttle_lock = threading.Lock()
        self.session = self._build_session()

    # ---------------- 会话与登录 ----------------

    def _build_session(self) -> requests.Session:
        """带 UA、重试策略与本地 cookie 的会话。"""
        s = requests.Session()
        s.headers.update({"User-Agent": UA})
        retry = Retry(total=2, backoff_factor=0.5,
                      status_forcelist=(429, 502, 503, 504),
                      allowed_methods=frozenset(["GET", "POST"]))
        adapter = HTTPAdapter(max_retries=retry)
        s.mount("https://", adapter)
        s.mount("http://", adapter)
        if os.path.exists(self.cookie_file):
            try:
                with open(self.cookie_file, encoding="utf-8") as f:
                    s.cookies.update(json.load(f))
            except Exception:
                pass
        return s

    def _load_credentials(self) -> tuple[str | None, str | None]:
        """凭据来源：显式参数 > 环境变量 > config.json（支持加密存储 password_enc）。"""
        phone = self._explicit_phone or os.environ.get("CHAOXING_PHONE")
        password = self._explicit_password or os.environ.get("CHAOXING_PASSWORD")
        if phone and password:
            return phone, password
        cfg = self._read_config()
        phone = phone or cfg.get("phone")
        if not password and cfg.get("password_enc"):
            # 加密存储：用本机 secret.key 解开（security.py 与采集服务同目录）
            try:
                from security import decrypt_secret, load_or_create_key
                password = decrypt_secret(cfg["password_enc"],
                                          load_or_create_key(self.config_dir)) or ""
            except Exception:
                password = ""
        if not password:
            password = cfg.get("password") or ""
        return phone, password

    def _read_config(self) -> dict:
        if os.path.exists(self.config_file):
            try:
                # utf-8-sig：兼容记事本/PowerShell 存出来的带 BOM 的 JSON
                with open(self.config_file, encoding="utf-8-sig") as f:
                    return json.load(f) or {}
            except Exception:
                return {}
        return {}

    def _save_cookies(self) -> None:
        try:
            cookies = {c.name: c.value for c in self.session.cookies}
            with open(self.cookie_file, "w", encoding="utf-8") as f:
                json.dump(cookies, f)
        except Exception:
            pass

    # ---- cookie 归属：换了 config.json 里的手机号必须重新登录，
    #      否则旧 cookie 还有效，就会一直用着上一个账号（踩过这个坑）

    def _owner_file(self) -> str:
        return os.path.join(self.config_dir, "session_owner.json")

    def _read_owner(self) -> str:
        """记录当前 cookie 属于哪个手机号。"""
        try:
            with open(self._owner_file(), encoding="utf-8-sig") as f:
                return str((json.load(f) or {}).get("phone") or "")
        except Exception:
            return ""

    def _write_owner(self, phone: str) -> None:
        try:
            with open(self._owner_file(), "w", encoding="utf-8") as f:
                json.dump({"phone": phone}, f)
        except Exception:
            pass

    def _drop_session(self) -> None:
        """清掉内存里的 cookie 与磁盘上的会话文件。"""
        try:
            self.session.cookies.clear()
        except Exception:
            pass
        for path in (self.cookie_file, self._owner_file()):
            try:
                os.remove(path)
            except OSError:
                pass

    def login(self, phone: str | None = None, password: str | None = None) -> AuthResult:
        """账号密码登录（参数 AES 加密）；成功后 cookie 落盘。"""
        if not phone or not password:
            phone, password = self._load_credentials()
        if not phone or not password:
            return AuthResult(False, "未提供凭据（config.json / 环境变量 / 参数均无）")
        r = self.session.post(
            URL_LOGIN,
            data={
                "fid": "-1",
                "uname": aes_encrypt(phone),
                "password": aes_encrypt(password),
                "refer": "https%3A%2F%2Fi.chaoxing.com",
                "t": "true",
                "forbidotherlogin": "0",
                "validate": "",
                "doubleFactorLogin": "0",
                "independentId": "0",
            },
            timeout=self.timeout,
        )
        try:
            body = r.json()
            ok = body.get("status") is True
            msg = body.get("msg2") or ("登录成功" if ok else "登录失败（账号密码错误或需要验证码）")
        except Exception:
            ok, msg = False, "登录响应异常: " + r.text[:120]
        if ok:
            self._save_cookies()
            self._write_owner(phone)
            self._login_checked_at = time.time()
        return AuthResult(ok, msg)

    def ensure_login(self, force: bool = False) -> AuthResult:
        """cookie 有效就直接用；否则用配置里的凭据登录。

        若 config.json 里的手机号和"当前 cookie 属于谁"不一致，强制重登——
        不然改了账号却还拿着上一个账号的 cookie，页面数据就一直不变。
        """
        phone, _ = self._load_credentials()
        owner = self._read_owner()
        if not force and phone and owner != phone:
            print(f"[info] 检测到账号变更（cookie 属于 {owner or '未知'}，配置是 {phone}），强制重新登录")
            force = True
            self._drop_session()
            self._login_checked_at = 0.0
        if not force and time.time() - self._login_checked_at < LOGIN_STATE_TTL:
            return AuthResult(True, "cookie 有效")
        try:
            r = self.session.get(URL_BASE, timeout=self.timeout)
            if not any(marker in r.url or marker in r.text for marker in LOGIN_MARKERS):
                self._login_checked_at = time.time()
                self._base_html = r.text     # fetch_courses 要用 fid，别二次请求同页
                return AuthResult(True, "cookie 有效")
        except Exception:
            pass
        res = self.login()
        if res.ok:
            return res
        return AuthResult(False, "未登录且自动登录失败：" + res.msg)

    # ---------------- HTTP（登录态失效自动重登一次） ----------------

    def _throttle_wait(self) -> None:
        """两次请求之间至少间隔 throttle 秒，模拟人类点击节奏，降低风控概率。"""
        if self.throttle <= 0:
            return
        with self._throttle_lock:
            gap = time.time() - self._last_request_at
            if gap < self.throttle:
                time.sleep(self.throttle - gap)
            self._last_request_at = time.time()

    def _is_login_redirect(self, resp: requests.Response) -> bool:
        return any(marker in resp.url or marker in resp.text for marker in LOGIN_MARKERS)

    @staticmethod
    def _fix_encoding(resp: requests.Response) -> requests.Response:
        """按字节真实编码纠正解码方式。

        学习通有些页面 Header 声明 GBK、body 却是 UTF-8（或反过来），requests 会照着
        Header 解出乱码，导致中文匹配（如"没有此页面访问权限"）永远不命中。
        这里统一按字节嗅探：能解 UTF-8 就当 UTF-8，否则退回 GBK。
        """
        try:
            raw = resp.content
            try:
                raw.decode("utf-8")
                resp.encoding = "utf-8"
            except UnicodeDecodeError:
                resp.encoding = "gbk"
        except Exception:
            pass
        return resp

    def get(self, url: str, **kw) -> requests.Response:
        kw.setdefault("timeout", self.timeout)
        self._throttle_wait()
        r = self.session.get(url, **kw)
        if self._is_login_redirect(r):
            if self.ensure_login(force=True).ok:
                self._throttle_wait()
                r = self.session.get(url, **kw)
        return self._fix_encoding(r)

    def post(self, url: str, **kw) -> requests.Response:
        kw.setdefault("timeout", self.timeout)
        self._throttle_wait()
        r = self.session.post(url, **kw)
        if self._is_login_redirect(r):
            if self.ensure_login(force=True).ok:
                self._throttle_wait()
                r = self.session.post(url, **kw)
        return self._fix_encoding(r)

    # ---------------- 数据接口 ----------------

    def fetch_courses(self, refresh: bool = False) -> list[dict]:
        """我学的课程列表（5 分钟缓存）。"""
        now = time.time()
        if (not refresh and self._courses_cache is not None
                and now - self._courses_cache_at < COURSES_CACHE_TTL):
            return self._courses_cache
        base = self._base_html or self.get(URL_BASE).text
        m = (re.search(r'"fid"\s*:\s*"?(\d+)"?', base)
             or re.search(r"var fid = '(\d+)'", base))
        fid = m.group(1) if m else "427"
        r = self.get(URL_COURSELIST, params={
            "courseType": 1, "courseFid": fid,
            "courseTeacherid": 0, "courseOrderBy": 0})
        self._courses_cache = parse_courses(r.text)
        self._courses_cache_at = now
        return self._courses_cache

    def fetch_course_page(self, c: dict) -> str:
        """课程中间页 HTML（stucoursemiddle），含 enc/openc/workEnc 等隐藏域。"""
        return self.get(URL_STUMIDDLE, params={
            "courseid": c["courseid"], "clazzid": c["clazzid"], "cpi": c["cpi"],
            "ismooc2": 1, "v": 2}).text

    def fetch_profile(self) -> dict:
        """个人资料：姓名 / 学校 / uid / fid。"""
        base = self.get(URL_BASE).text
        name = (re.search(r'aria-label="账号：([^"<]{1,20})"', base)
                or re.search(r"账号：([^<\s]{1,20})", base))
        school = re.search(r'id="siteName"[^>]*title="([^"]+)"', base)
        uid = re.search(r"var uid =\s*'?(\d+)'?", base)
        fid = (re.search(r'"fid"\s*:\s*"?(\d+)"?', base)
               or re.search(r"var fid = '(\d+)'", base))
        return {
            "name": name.group(1) if name else "?",
            "school": school.group(1) if school else "?",
            "uid": uid.group(1) if uid else "?",
            "fid": fid.group(1) if fid else "?",
        }

    def fetch_schedule(self, week: int | None = None) -> dict:
        """课表：{curriculum, lessons}。

        关键协议：getMyLessons 不带参数只返回"当前周"的课（每条 weeks 字段
        就是当前周数，不是全学期）；带 {"week": N} 才返回第 N 周。
        """
        data = {"week": week} if week else {}
        j = self.post(URL_SCHEDULE, data=data).json()
        if j.get("result") != 1:
            raise RuntimeError("课表接口返回失败: " + str(j.get("msg")))
        body = j.get("data") or {}
        return {"curriculum": body.get("curriculum") or {},
                "lessons": body.get("lessonArray") or []}

    def fetch_homework(self, c: dict, refresh: bool = False) -> dict:
        """某门课的作业列表：{progress, items:[{index,title,status,url}]}。

        列表接口的 enc 必须用课程页隐藏域 workEnc（页面 enc 不通用）。
        """
        key = (c["courseid"], c["clazzid"])
        now = time.time()
        cached = self._hw_cache.get(key)
        if not refresh and cached and now - cached[0] < HOMEWORK_CACHE_TTL:
            return cached[1]
        page = self.fetch_course_page(c)
        work_enc = hidden_value(page, "workEnc")
        openc = hidden_value(page, "openc")
        page_enc = hidden_value(page, "enc")
        if not work_enc:
            raise RuntimeError("课程页未生成作业签名（workEnc），该课可能未开放作业功能")
        r = self.get(URL_WORKLIST, params={
            "courseId": c["courseid"], "classId": c["clazzid"], "cpi": c["cpi"],
            "ut": "s", "openc": openc, "enc": work_enc,
            "t": int(time.time() * 1000), "stuenc": page_enc, "isdisplaytable": 2})
        html = r.text
        if "没有此页面访问权限" in html:
            raise RuntimeError("作业页签名校验失败（动态 enc），请稍后重试")
        m_prog = re.search(r"<span>(\d+)/(\d+)</span>\s*</div>\s*</div>", html)
        items = re.findall(
            r'<li onclick="goTask\(this\);" data="([^"]+)"[\s\S]*?'
            r'<p class="overHidden2 fl">([^<]+)</p>[\s\S]*?<p class="status fl">([^<]*)</p>', html)
        result = {
            "progress": (int(m_prog.group(1)), int(m_prog.group(2))) if m_prog else None,
            "items": [{"index": i + 1, "title": t.strip(), "status": s.strip(),
                       "url": unquote(u)}
                      for i, (u, t, s) in enumerate(items)],
        }
        self._hw_cache[key] = (now, result)
        return result

    def fetch_homework_detail(self, url: str) -> dict:
        """取单份作业详情页（题量/满分/作答起止/得分）。url 来自作业列表条目。"""
        return parse_homework_detail(self.get(url).text)

    def fetch_exams(self) -> list[dict]:
        """全部考试安排（已解析成结构化行）。"""
        r = self.get(URL_EXAMLIST)
        raw_rows = []
        for row in re.findall(r'<tr[^>]*class="dataTr"[^>]*>([\s\S]*?)</tr>', r.text):
            tds = [html_mod.unescape(re.sub(r"<[^>]+>", "", td)).strip()
                   for td in re.findall(r"<td[^>]*>([\s\S]*?)</td>", row)]
            if len(tds) >= 9:
                raw_rows.append(tds)
        return parse_exam_rows(raw_rows)

    def resolve_work_course(self, work_url: str) -> dict | None:
        """跟进作业附件 url 的跳转，反推 courseid / clazzid / cpi。

        作业列表接口需要 cpi，而 cpi 只在跳转后的地址里出现；拿到它就能对
        "课程列表里列不出来"的课程（个人空间、测试号）继续抓作业。
        """
        try:
            r = self.get(work_url)
        except Exception:
            return None
        qs = parse_qs(urlparse(r.url).query)
        course_id = (qs.get("courseId") or qs.get("courseid") or [""])[0]
        class_id = (qs.get("classId") or qs.get("classid") or [""])[0]
        cpi = (qs.get("cpi") or [""])[0]
        if not (course_id and class_id and cpi):
            return None
        return {"courseid": course_id, "clazzid": class_id, "cpi": cpi}

    def fetch_notices(self, limit: int = 40) -> list[dict]:
        """通知中心列表（列表里的 content 就是全文，无需再请求详情页）。"""
        items: list[dict] = []
        last_id = ""
        for _ in range(3):
            r = self.post(URL_NOTICELIST, data={
                "type": 0, "notice_type": 0, "lastValue": last_id, "sort": 0,
                "folderUUID": "", "kw": "", "startTime": "", "endTime": "",
                "gKw": "", "gName": "", "year": "", "tag": "", "fidsCode": "",
                "filterSenderPuids": "", "filterTags": ""})
            j = r.json()
            if not j.get("status"):
                raise RuntimeError("通知接口返回失败: " + str(j.get("msg") or j)[:120])
            data = j.get("notices") or {}
            page_items = data.get("list") or []
            items.extend(page_items)
            last_id = data.get("lastGetId") or ""
            if not page_items or data.get("lastPage") or len(items) >= limit:
                break
        return items[:limit]

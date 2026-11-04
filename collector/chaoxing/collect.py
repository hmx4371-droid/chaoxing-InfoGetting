# -*- coding: utf-8 -*-
"""把学习通四类数据组装成「统一事件 JSON」。

输出结构（Java 后端只认这一份）:

{
  "source": "chaoxing",
  "schema": 1,
  "synced_at": "2026-11-04T16:30:00+08:00",
  "account": {"name": "...", "school": "...", "uid": "...", "fid": "..."},
  "week": {"current": 11, "max": 20, "first_week_date": "2026-08-24",
           "school_year": "2026-2027", "semester": "1"},
  "stats": {"homework": 3, "schedule": 18, "exam": 1, "notice": 20, "errors": 0},
  "errors": ["《某课》作业拉取失败: ..."],
  "items": [ <item>, ... ]
}

<item> = {
  "source": "chaoxing",
  "item_type": "homework|schedule|exam|notice",
  "source_id": "幂等键（同一来源内唯一，重复同步不会产生新行）",
  "title", "course", "teacher", "location",
  "deadline", "start_time", "end_time",     # ISO8601 带 +08:00，可为 null
  "status", "url", "raw"
}
"""

from __future__ import annotations

import json
import re
from datetime import date, datetime, timedelta
from urllib.parse import parse_qs, urlparse

from .client import (ChaoxingClient, _TZ_CN, is_homework_pending, ms_to_date,
                     nearest_datetime_for, parse_notice_attachments,
                     parse_section_times, strip_tags)

SOURCE = "chaoxing"


def _iso(dt: datetime | None) -> str | None:
    """datetime → ISO8601（北京时间，秒精度），None 原样返回。"""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=_TZ_CN)
    return dt.astimezone(_TZ_CN).isoformat(timespec="seconds")


def _pick(les: dict, *keys, default=""):
    """课表字段名在不同版本里变过，按优先级取第一个非空值。"""
    for k in keys:
        v = les.get(k)
        if v not in (None, "", []):
            return v
    return default


def _work_id(url: str) -> str:
    """从作业详情链接里取 workId 作为稳定主键（取不到返回空串）。"""
    try:
        qs = parse_qs(urlparse(url).query)
    except Exception:
        return ""
    for key in ("workId", "workid", "work_id", "id"):
        v = qs.get(key)
        if v:
            return str(v[0])
    return ""


def _notice_id(it: dict) -> str:
    """通知主键：优先服务端 id，缺失时退化到标题+时间。"""
    for key in ("id", "noticeId", "notice_id", "uuid"):
        v = it.get(key)
        if v not in (None, ""):
            return str(v)
    return f"{it.get('title', '')}|{it.get('completeTime', '')}"


def _parse_notice_time(text) -> datetime | None:
    """通知发布时间，形如 "2026-11-04 14:00"（少数带秒）。"""
    s = str(text or "").strip()
    if not s:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M",
                "%Y/%m/%d %H:%M:%S", "%Y/%m/%d %H:%M"):
        try:
            return datetime.strptime(s, fmt).replace(tzinfo=_TZ_CN)
        except ValueError:
            continue
    return None


# ---------------------------------------------------------------- 四类数据

def build_schedule(client: ChaoxingClient, now: datetime | None = None) -> tuple[list[dict], dict]:
    """当前周课表 → schedule 条目列表 + 周次元信息。

    只拉当前周（getMyLessons 不带 week 参数就是当前周），全学期逐周合并
    会多出 ~20 次请求，留到后续优化。日期由 firstWeekDate + dayOfWeek 推算。
    """
    now = now or datetime.now(_TZ_CN)
    data = client.fetch_schedule()
    cur = data["curriculum"]
    first_date = ms_to_date(cur.get("firstWeekDate"))
    max_week = int(cur.get("maxWeek") or 0) or 25
    # 服务端自己就知道现在第几周（currentWeek / realCurrentWeek），优先用它；
    # 老账号没有这两个字段时再用 firstWeekDate 推算（dayOfWeek 为 1 基）。
    current_week = int(cur.get("currentWeek") or cur.get("realCurrentWeek") or 0)
    if not current_week and first_date:
        current_week = max(1, min(max_week, (now.date() - first_date).days // 7 + 1))
    section_times = parse_section_times(cur.get("lessonTimeConfigArray"))

    items = []
    for les in data["lessons"]:
        day = int(_pick(les, "dayOfWeek", "dayOfWeekInt", default=0) or 0)
        begin = int(_pick(les, "beginNumber", "startSection", "begin", default=0) or 0)
        length = int(_pick(les, "length", "sectionLength", "step", default=1) or 1)
        name = str(_pick(les, "name", "courseName", default="?"))
        location = str(_pick(les, "location", "classroom", "place", default=""))
        teacher = str(_pick(les, "teacherName", "teacher", default=""))
        weeks = str(_pick(les, "weeks", default=""))

        start_dt = end_dt = None
        if first_date and 1 <= day <= 7 and current_week:
            the_day = first_date + timedelta(days=(current_week - 1) * 7 + day - 1)
            if section_times and 1 <= begin <= len(section_times):
                s_t, e_t = section_times[begin - 1]
                start_dt = datetime.combine(the_day, s_t, tzinfo=_TZ_CN)
                last_idx = min(len(section_times), begin + max(0, length) - 1) - 1
                end_dt = datetime.combine(the_day, section_times[last_idx][1],
                                          tzinfo=_TZ_CN)

        if end_dt and now > end_dt:
            status = "已下课"
        elif start_dt and start_dt <= now <= (end_dt or start_dt):
            status = "上课中"
        else:
            status = "未开始"

        items.append({
            "source": SOURCE,
            "item_type": "schedule",
            "source_id": f"sc:{_pick(les, 'lessonId', 'id', default='')}:{day}:{begin}:{location}",
            "title": name,
            "course": name,
            "teacher": teacher,
            "location": location,
            "deadline": None,
            "start_time": _iso(start_dt),
            "end_time": _iso(end_dt),
            "status": status,
            "url": "",
            "raw": {
                "lesson_id": _pick(les, "lessonId", "id", default=""),
                "day_of_week": day,
                "begin_number": begin,
                "length": length,
                "weeks": weeks,
                "courseid": _pick(les, "courseId", "courseid", default=""),
                "clazzid": _pick(les, "classId", "clazzid", default=""),
            },
        })

    week_meta = {
        "current": current_week,
        "max": max_week,
        "first_week_date": first_date.isoformat() if first_date else None,
        "school_year": cur.get("schoolYear"),
        "semester": cur.get("semester"),
        "lesson_count": len(data["lessons"]),
    }
    return items, week_meta


def build_homework(client: ChaoxingClient, courses: list[dict], today: date,
                   with_details: bool = True, log=None) -> tuple[list[dict], list[str]]:
    """逐课拉作业列表；未交的再逐份拉详情拿截止时间。

    已完成/已提交的不请求详情页（省掉大部分请求）；某门课失败只记错不中断。
    """
    log = log or (lambda *_: None)
    items: list[dict] = []
    errors: list[str] = []
    for c in courses:
        try:
            hw = client.fetch_homework(c)
        except Exception as e:                      # 未开放作业功能的课
            errors.append(f"《{c['name']}》作业拉取失败: {e}")
            continue
        for it in hw["items"]:
            url = it["url"] if it["url"].startswith("http") else ""
            status = it["status"] or "未知"
            detail = {}
            if with_details and url and is_homework_pending(status):
                try:
                    detail = client.fetch_homework_detail(url)
                except Exception as e:
                    errors.append(f"《{c['name']}》{it['title']} 详情失败: {e}")
            deadline_dt = None
            if detail.get("deadline"):
                deadline_dt = nearest_datetime_for(detail["deadline"], today)
            start_dt = None
            if detail.get("start_time"):
                start_dt = nearest_datetime_for(detail["start_time"], today)
            wid = _work_id(url)
            items.append({
                "source": SOURCE,
                "item_type": "homework",
                "source_id": f"hw:{wid}" if wid else f"hw:{c['courseid']}:{it['index']}:{it['title']}",
                "title": detail.get("title") or it["title"],
                "course": c["name"],
                "teacher": c.get("teacher") or "",
                "location": "",
                "deadline": _iso(deadline_dt),
                "start_time": _iso(start_dt),
                "end_time": None,
                "status": status,
                "url": url,
                "raw": {
                    "question_count": detail.get("question_count"),
                    "full_score": detail.get("full_score"),
                    "score": detail.get("score"),
                    "deadline_text": detail.get("deadline"),
                    "progress": list(hw["progress"]) if hw["progress"] else None,
                },
            })
        log(f"  作业 {c['name']}: {len(hw['items'])} 份")
    return items, errors


def build_exams(client: ChaoxingClient) -> tuple[list[dict], list[str]]:
    """考试安排（接口本身是全校汇总，没有课程维度）。"""
    try:
        rows = client.fetch_exams()
    except Exception as e:
        return [], [f"考试拉取失败: {e}"]
    items = []
    for r in rows:
        start, end = r["start"], r["end"]
        status = r["answer"] or r["status"] or "未知"
        items.append({
            "source": SOURCE,
            "item_type": "exam",
            "source_id": f"ex:{r['name']}:{_iso(start)}",
            "title": r["name"],
            "course": "",
            "teacher": "",
            "location": "",
            "deadline": _iso(end),
            "start_time": _iso(start),
            "end_time": _iso(end),
            "status": status,
            "url": "https://mooc1-api.chaoxing.com/exam-ans/exam/test/examcode/examlist",
            "raw": {"duration_min": r["durationMin"], "exam_status": r["status"],
                    "answer_status": r["answer"], "score": r["score"],
                    "mode": r["mode"]},
        })
    return items, []


def build_notices(client: ChaoxingClient, limit: int = 40) -> tuple[list[dict], list[str]]:
    """通知中心（列表里的 content 就是全文）。"""
    try:
        rows = client.fetch_notices(limit=limit)
    except Exception as e:
        return [], [f"通知拉取失败: {e}"]
    items = []
    for it in rows:
        content = strip_tags(it.get("content") or "")
        is_read = str(it.get("isread", "1")) == "1"
        items.append({
            "source": SOURCE,
            "item_type": "notice",
            "source_id": f"nt:{_notice_id(it)}",
            "title": (it.get("title") or "").strip() or "（无标题通知）",
            "course": "",
            "teacher": (it.get("createrName") or "").strip(),
            "location": "",
            "deadline": None,
            # 通知的 start_time 表示"发布时间"，前端按它倒序排
            "start_time": _iso(_parse_notice_time(it.get("completeTime"))),
            "end_time": None,
            "status": "已读" if is_read else "未读",
            "url": "",
            "raw": {"content": content[:1000],
                    "time": it.get("completeTime"),
                    "images": len(it.get("imgs") or []),
                    # 作业类通知里带着 courseId/classId/workId，后面反查作业要用
                    "works": parse_notice_attachments(it)},
        })
    return items, []


# ---------------------------------------------------------------- 从通知反查课程

def build_courses_from_notices(client: ChaoxingClient, notice_items: list[dict],
                               log=None) -> list[dict]:
    """从「作业」类通知里反推出课程三元组 (courseid, clazzid, cpi)。

    为什么需要它：课程列表接口（courselistdata）对个人空间/测试号常常返回 0 门课，
    但作业通知里带着 courseId/classId，跳转后的地址里还带 cpi —— 凑齐这三样，
    就能照常调作业列表接口，把作业和截止时间捞出来。
    """
    log = log or (lambda *_: None)
    seen: set[str] = set()
    courses: list[dict] = []
    for it in notice_items:
        for work in (it.get("raw") or {}).get("works") or []:
            cid = work.get("course_id")
            if not cid or cid in seen or not work.get("url"):
                continue
            seen.add(cid)
            info = client.resolve_work_course(work["url"])
            if not info:
                log(f"  通知反查课程失败: {work.get('title')}")
                continue
            courses.append({
                "name": work.get("course_name") or f"课程{cid}",
                "teacher": "",
                **info,
            })
            log(f"  从通知补到课程: {work.get('course_name') or cid}")
    return courses


# ---------------------------------------------------------------- 入口

def attach_raw_json(items: list[dict]) -> None:
    """把 raw 对象序列化成 raw_json 字符串：Java 侧不解析 JSON，直接落 TEXT 列。

    raw 保留对象形态（人/agent 读 /api/data 时友好），raw_json 供数据库存储。
    """
    for it in items:
        it["raw_json"] = json.dumps(it.get("raw") or {}, ensure_ascii=False)


def collect(client: ChaoxingClient, with_details: bool = True,
            notice_limit: int = 40, log=None) -> dict:
    """跑一轮完整采集，返回统一 JSON（失败的门类只记 errors，不整体报错）。"""
    log = log or (lambda *_: None)
    now = datetime.now(_TZ_CN)
    started = datetime.now(_TZ_CN)

    lg = client.ensure_login()
    if not lg.ok:
        raise RuntimeError("登录失败：" + lg.msg)

    try:
        profile = client.fetch_profile()
    except Exception as e:
        profile = {"name": "?", "school": "?"}
        log(f"  资料页拉取失败: {e}")

    courses = client.fetch_courses()
    log(f"课程 {len(courses)} 门")

    errors: list[str] = []
    sched_items, week_meta = [], {}
    try:
        sched_items, week_meta = build_schedule(client, now)
    except Exception as e:
        errors.append(f"课表拉取失败: {e}")
    log(f"  课表 {len(sched_items)} 节（第 {week_meta.get('current')} 周）")

    # 先取通知：作业类通知能反推出课程列表里没有的课程，再一起抓作业
    notice_items, notice_errors = build_notices(client, notice_limit)
    errors += notice_errors
    log(f"  通知 {len(notice_items)} 条")

    extra_courses = build_courses_from_notices(client, notice_items, log)
    known = {c["courseid"] for c in courses}
    merged = courses + [c for c in extra_courses if c["courseid"] not in known]

    hw_items, hw_errors = build_homework(client, merged, now.date(), with_details, log)
    errors += hw_errors

    exam_items, exam_errors = build_exams(client)
    errors += exam_errors
    log(f"  考试 {len(exam_items)} 场")

    items = hw_items + sched_items + exam_items + notice_items
    attach_raw_json(items)
    stats = {
        "homework": len(hw_items), "schedule": len(sched_items),
        "exam": len(exam_items), "notice": len(notice_items),
        "errors": len(errors),
    }
    return {
        "source": SOURCE,
        "schema": 1,
        "synced_at": _iso(now),
        "elapsed_ms": int((datetime.now(_TZ_CN) - started).total_seconds() * 1000),
        "account": profile,
        "week": week_meta,
        "stats": stats,
        "errors": errors,
        "items": items,
    }

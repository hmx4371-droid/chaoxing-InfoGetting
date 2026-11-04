# -*- coding: utf-8 -*-
"""假数据：没配学习通账号时也能把 采集 → 后端 → 前端 整条链路跑通。

config.json 里 "mock": true（或环境变量 CHAOXING_MOCK=1）时启用。
日期都按"今天"生成，所以随时打开都能看到正常/临期/已过期三种 DDL。
"""

from __future__ import annotations

from datetime import datetime, timedelta

from .client import _TZ_CN
from .collect import _iso, attach_raw_json

SOURCE = "chaoxing"


def _weekday_of(day: datetime) -> int:
    return day.isoweekday()


def mock_payload(with_details: bool = True) -> dict:
    """造一份和真实采集结果同构的数据。"""
    now = datetime.now(_TZ_CN).replace(microsecond=0)
    today = now.replace(hour=0, minute=0, second=0)
    first_week = today - timedelta(days=(today.isoweekday() - 1) + 7 * 10)
    current_week = 11
    monday = today - timedelta(days=today.isoweekday() - 1)

    items: list[dict] = []

    # ---------------- 作业（4 份：临期 / 宽裕 / 已过期 / 已提交）
    hw_specs = [
        ("实验四 整体调试实验报告", "数据结构与算法", "陈老师", 1.2, "待提交", 2, 100),
        ("第三章 课后习题", "高等数学（上）", "王老师", 3.5, "待提交", 8, 100),
        ("期中论文提纲", "大学英语（三）", "李老师", -1.5, "已截止", 1, 50),
        ("程序设计实践 第 5 周", "程序设计基础", "张老师", 6.0, "已完成", 3, 100),
    ]
    for i, (title, course, teacher, days, status, qcnt, full) in enumerate(hw_specs, 1):
        # 截止时间落到当天 23:59，看起来像真实教务习惯
        dl = (now + timedelta(days=days)).replace(hour=23, minute=59, second=0, microsecond=0)
        items.append({
            "source": SOURCE, "item_type": "homework",
            "source_id": f"hw:1000{i}:9000{i}",
            "title": title, "course": course, "teacher": teacher, "location": "",
            "deadline": _iso(dl),
            "start_time": _iso(dl - timedelta(days=7)),
            "end_time": None,
            "status": status,
            "url": f"https://mooc1.chaoxing.com/mooc2/work/task?courseId=1000{i}&classId=2000{i}&workId=9000{i}",
            "raw": {"question_count": qcnt, "full_score": full,
                    "score": "92" if status == "已完成" else None,
                    "deadline_text": dl.strftime("%m-%d %H:%M"), "progress": [i, 6]},
        })

    # ---------------- 课表（本周 8 节）
    slots = [
        (1, 1, 2, "高等数学（上）", "王老师", "教一楼 201"),
        (1, 3, 2, "大学英语（三）", "李老师", "外语楼 305"),
        (2, 1, 2, "程序设计基础", "张老师", "计算中心 A302"),
        (2, 5, 2, "数据结构与算法", "陈老师", "教三楼 401"),
        (3, 1, 2, "高等数学（上）", "王老师", "教一楼 201"),
        (4, 3, 2, "大学英语（三）", "李老师", "外语楼 305"),
        (4, 5, 2, "形势与政策", "赵老师", "教二楼 108"),
        (5, 1, 2, "数据结构与算法", "陈老师", "教三楼 401"),
    ]
    def _sec_time(begin: int) -> tuple[int, int, int, int]:
        """第 n 节 → (时, 分, 时, 分)，模拟 8:00 起每节 50 分钟。"""
        start_min = 8 * 60 + (begin - 1) * 55
        return start_min // 60, start_min % 60, (start_min + 100) // 60, (start_min + 100) % 60

    for idx, (day, begin, length, name, teacher, loc) in enumerate(slots, 1):
        the_day = monday + timedelta(days=day - 1)
        h1, m1, h2, m2 = _sec_time(begin)
        st = the_day.replace(hour=h1, minute=m1)
        et = the_day.replace(hour=h2, minute=m2)
        status = "已下课" if now > et else ("上课中" if now >= st else "未开始")
        items.append({
            "source": SOURCE, "item_type": "schedule",
            "source_id": f"sc:7700{idx}:{day}:{begin}:{loc}",
            "title": name, "course": name, "teacher": teacher, "location": loc,
            "deadline": None, "start_time": _iso(st), "end_time": _iso(et),
            "status": status, "url": "",
            "raw": {"lesson_id": f"7700{idx}", "day_of_week": day,
                    "begin_number": begin, "length": length,
                    "weeks": "1-16", "courseid": f"1000{idx}", "clazzid": f"2000{idx}"},
        })

    # ---------------- 考试（2 场：一周后 / 已出分）
    exam_specs = [
        ("高等数学（上）期末考试", 7, "闭卷", "未开始", ""),
        ("大学英语（三）期中测验", -9, "闭卷", "已结束", "86"),
    ]
    for i, (name, days, mode, estatus, score) in enumerate(exam_specs, 1):
        st = (now + timedelta(days=days)).replace(hour=9, minute=0, second=0)
        items.append({
            "source": SOURCE, "item_type": "exam",
            "source_id": f"ex:{name}:{_iso(st)}",
            "title": name, "course": "", "teacher": "", "location": "",
            "deadline": _iso(st + timedelta(hours=2)),
            "start_time": _iso(st), "end_time": _iso(st + timedelta(hours=2)),
            "status": estatus,
            "url": "https://mooc1-api.chaoxing.com/exam-ans/exam/test/examcode/examlist",
            "raw": {"duration_min": "120", "exam_status": estatus,
                    "answer_status": estatus, "score": score, "mode": mode},
        })

    # ---------------- 通知（5 条）
    notices = [
        ("【作业提醒】实验四 整体调试实验报告 即将截止", "陈老师", 0, 0.5),
        ("关于调整下周三《大学英语（三）》上课教室的通知", "教务处", 2, 1.2),
        ("2026-2027 学年第一学期期末考试安排已发布", "教务处", 0, 2.0),
        ("图书馆 11 月开放时间调整通知", "图书馆", 5, 3.4),
        ("【成绩发布】程序设计实践 第 4 周作业成绩已公布", "张老师", 9, 5.1),
    ]
    for i, (title, sender, unread, days_ago) in enumerate(notices, 1):
        t = now - timedelta(days=days_ago)
        items.append({
            "source": SOURCE, "item_type": "notice",
            "source_id": f"nt:6600{i}",
            "title": title, "course": "", "teacher": sender, "location": "",
            "deadline": None, "start_time": _iso(t), "end_time": None,
            "status": "未读" if unread == 0 else "已读",
            "url": "",
            "raw": {"content": f"{title}。这是一条假数据，用于在未配置学习通账号时演示界面。",
                    "time": t.strftime("%Y-%m-%d %H:%M"), "images": 0},
        })

    stats = {"homework": 4, "schedule": len(slots), "exam": len(exam_specs),
             "notice": len(notices), "errors": 0}
    attach_raw_json(items)
    return {
        "source": SOURCE,
        "schema": 1,
        "mock": True,
        "synced_at": _iso(now),
        "elapsed_ms": 1200,
        "account": {"name": "演示同学", "school": "演示大学", "uid": "000000", "fid": "427"},
        "week": {"current": current_week, "max": 20,
                 "first_week_date": first_week.date().isoformat(),
                 "school_year": "2026-2027", "semester": "1",
                 "lesson_count": len(slots)},
        "stats": stats,
        "errors": [],
        "items": items,
    }

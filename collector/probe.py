# -*- coding: utf-8 -*-
"""诊断脚本：把学习通原始响应 dump 出来，用来区分"确实没数据"和"解析失败"。

用法（在 demo/collector 目录下）：
    python probe.py              # 概览
    python probe.py --dump       # 同时把原始 HTML 存到 probe_out/
    python probe.py --course 3   # 只看第 3 门课的作业页

它只做只读 GET/POST 查询，不放大量请求（每类就一两次），可以放心跑。
"""

from __future__ import annotations

import json
import os
import re
import sys

from chaoxing.client import (URL_EXAMLIST, URL_NOTICELIST, URL_SCHEDULE,
                             URL_WORKLIST, ChaoxingClient, hidden_value,
                             strip_tags)

OUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "probe_out")


def save(name: str, content: str) -> None:
    """把原始响应存盘，方便用编辑器翻。"""
    os.makedirs(OUT_DIR, exist_ok=True)
    path = os.path.join(OUT_DIR, name)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    print(f"    原始响应已存: {path} ({len(content)} 字符)")


def main() -> None:
    dump = "--dump" in sys.argv
    only_course = None
    if "--course" in sys.argv:
        idx = sys.argv.index("--course")
        if idx + 1 < len(sys.argv):
            only_course = int(sys.argv[idx + 1])

    c = ChaoxingClient()
    lg = c.ensure_login()
    print(f"[1] 登录: ok={lg.ok} msg={lg.msg}")
    if not lg.ok:
        return

    profile = c.fetch_profile()
    print(f"    账号: {profile.get('name')} @ {profile.get('school')} (uid={profile.get('uid')})")

    courses = c.fetch_courses()
    print(f"\n[2] 课程 {len(courses)} 门:")
    for i, co in enumerate(courses, 1):
        print(f"    {i}. {co['name']} | {co['teacher']} | courseid={co['courseid']} clazzid={co['clazzid']}")

    # ---------------- 课表
    print("\n[3] 课表:")
    j = c.post(URL_SCHEDULE, data={}).json()
    body = (j.get("data") or {})
    cur = body.get("curriculum") or {}
    lessons = body.get("lessonArray") or []
    print(f"    result={j.get('result')} msg={j.get('msg')}")
    print(f"    curriculum 字段: {sorted(cur.keys())}")
    print(f"    schoolYear={cur.get('schoolYear')} semester={cur.get('semester')} "
          f"maxWeek={cur.get('maxWeek')} firstWeekDate={cur.get('firstWeekDate')}")
    print(f"    当前周课程数: {len(lessons)}")
    for les in lessons[:3]:
        print(f"      - {les.get('name')} 周{les.get('dayOfWeek')} 第{les.get('beginNumber')}节 "
              f"weeks={les.get('weeks')} 教室={les.get('location')}")
    if dump:
        save("schedule_current.json", json.dumps(j, ensure_ascii=False, indent=2))
    # 试几周，看看是不是"本周恰好没课"
    for w in (1, 2, 3):
        try:
            jj = c.post(URL_SCHEDULE, data={"week": w}).json()
            n = len(((jj.get("data") or {}).get("lessonArray")) or [])
            print(f"    第 {w} 周课程数: {n}")
        except Exception as e:
            print(f"    第 {w} 周查询失败: {e}")

    # ---------------- 作业（逐课）
    print("\n[4] 作业:")
    for i, co in enumerate(courses, 1):
        if only_course and i != only_course:
            continue
        try:
            page = c.fetch_course_page(co)
            work_enc = hidden_value(page, "workEnc")
            print(f"    《{co['name']}》课程页 {len(page)} 字符, workEnc={'有' if work_enc else '无!'}")
            if dump:
                save(f"course_{i}_middle.html", page)
            if not work_enc:
                continue
            hw = c.fetch_homework(co, refresh=True)
            print(f"      作业 {len(hw['items'])} 份, 进度={hw['progress']}")
            for it in hw["items"][:5]:
                print(f"        - [{it['status']}] {it['title']}")
                print(f"          {it['url'][:120]}")
            if dump and not hw["items"]:
                r = c.get(URL_WORKLIST, params={
                    "courseId": co["courseid"], "classId": co["clazzid"], "cpi": co["cpi"],
                    "ut": "s", "openc": hidden_value(page, "openc"), "enc": work_enc,
                    "t": 1, "stuenc": hidden_value(page, "enc"), "isdisplaytable": 2})
                save(f"course_{i}_worklist.html", r.text)
                print(f"      列表页 li 标签数={r.text.count('<li')} 含'没有此页面访问权限'="
                      f"{'没有此页面访问权限' in r.text}")
        except Exception as e:
            print(f"    《{co['name']}》失败: {e}")

    # ---------------- 考试
    print("\n[5] 考试:")
    r = c.get(URL_EXAMLIST)
    rows = re.findall(r'<tr[^>]*class="dataTr"[^>]*>', r.text)
    print(f"    页面 {len(r.text)} 字符, dataTr 行数={len(rows)}")
    if "登录" in r.text[:2000]:
        print("    ⚠ 页面疑似登录页")
    if dump:
        save("examlist.html", r.text)
    try:
        exams = c.fetch_exams()
        print(f"    解析出 {len(exams)} 场")
        for e in exams[:5]:
            print(f"      - {e['name']} {e['start']} {e['status']}")
    except Exception as e:
        print(f"    解析失败: {e}")

    # ---------------- 通知
    print("\n[6] 通知:")
    try:
        items = c.fetch_notices(limit=40)
        print(f"    取到 {len(items)} 条")
        for it in items[:5]:
            print(f"      - [{'未读' if str(it.get('isread')) == '0' else '已读'}] "
                  f"{(it.get('title') or '')[:40]} | {it.get('createrName')} | {it.get('completeTime')}")
        if dump:
            save("notices.json", json.dumps(items, ensure_ascii=False, indent=2))
    except Exception as e:
        print(f"    失败: {e}")

    print("\n完成。带 --dump 可把原始响应存到 probe_out/ 供对比。")


if __name__ == "__main__":
    main()

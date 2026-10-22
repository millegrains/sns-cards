"""Zoho用に作った Threads 原稿の一覧表（xlsx）から、台帳（posts.json）を作る変換プログラム。
マン管（mankan）・賃管（chintai）用。

使い方（保管庫のいちばん上のフォルダで実行）:
    python autopost/build_threads_posts.py mankan            # 台帳を作り直す＋自動チェック
    python autopost/build_threads_posts.py chintai --check   # 作り直さずに、今の台帳をチェックだけする

原稿の一覧表は <資格>/source/<資格>_threads_schedule_*-*.xlsx（1行 = 1投稿）:
    A列 = 日時（MM/DD/YYYY HH:MM 日本時間）／ B列 = 本文 ／ C列 = リンク ／ D列 = カード画像のアドレス
12時より前の行を「朝（問題）」、12時以降の行を「夜（解答）」として1日1件にまとめます。
"""
from __future__ import annotations

import argparse
import datetime as dt
import glob
import json
import re
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

REPO = Path(__file__).resolve().parent.parent
THREADS_LIMIT = 500
FIELDS = ["date", "no", "category", "card", "morning_time", "morning", "evening_time", "evening"]


def build(exam: str) -> list[dict]:
    import openpyxl  # 作り直すときだけ使う（チェックだけなら不要）

    files = sorted(glob.glob(str(REPO / exam / "source" / f"{exam}_threads_schedule_*-*.xlsx")))
    if not files:
        raise SystemExit(f"❌ 原稿の一覧表が見つかりません: {exam}/source/{exam}_threads_schedule_*-*.xlsx")
    days: dict[str, dict] = {}
    for f in files:
        for row in openpyxl.load_workbook(f).worksheets[0].iter_rows(values_only=True):
            if not row or not row[0]:
                continue
            when = dt.datetime.strptime(str(row[0]).strip(), "%m/%d/%Y %H:%M")
            d = days.setdefault(when.date().isoformat(), {"date": when.date().isoformat()})
            slot = "morning" if when.hour < 12 else "evening"
            d[slot] = str(row[1]).replace("\r\n", "\n").strip()
            d[slot + "_time"] = when.strftime("%H:%M")
            if len(row) > 3 and row[3]:
                d["card"] = str(row[3]).rsplit("/", 1)[1]
            m = re.search(r"出題分野：【(.+?)】", d[slot])
            if m:
                d["category"] = m.group(1)
    posts = []
    for key in sorted(days):
        d = days[key]
        m = re.search(r"_(\d+)\.png$", d.get("card", ""))
        d["no"] = m.group(1) if m else ""
        posts.append({k: d.get(k) for k in FIELDS})
    return posts


def check(exam: str, posts: list[dict]) -> list[str]:
    problems = []
    seen = set()
    for p in posts:
        where = p.get("date") or "?"
        if where in seen:
            problems.append(f"{where}: 同じ日付が2回あります")
        seen.add(where)
        for k in FIELDS:
            if not p.get(k):
                problems.append(f"{where}: {k} がありません")
        card = p.get("card") or ""
        if card and not card.startswith(f"{exam}_card_"):
            problems.append(f"{where}: カード名が {exam}_card_ で始まっていません（{card}）")
        if card and not (REPO / card).exists():
            problems.append(f"{where}: カード画像 {card} が保管庫にありません")
        for s in ("morning", "evening"):
            if p.get(s) and len(p[s]) > THREADS_LIMIT:
                problems.append(f"{where} {s}: {len(p[s])}字（Threadsの上限{THREADS_LIMIT}字を超えています）")
    return problems


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("exam", help="資格名（mankan／chintai）")
    ap.add_argument("--check", action="store_true", help="作り直さず、今の posts.json をチェックだけする")
    args = ap.parse_args()
    ledger = REPO / args.exam / "posts.json"

    if args.check:
        posts = json.loads(ledger.read_text(encoding="utf-8"))["posts"]
    else:
        posts = build(args.exam)

    problems = check(args.exam, posts)
    if problems:
        print("❌ チェック不合格（台帳は書き換えていません）")
        print("\n".join(problems))
        return 1
    if not args.check:
        data = {"exam": args.exam, "source": f"{args.exam}/source/{args.exam}_threads_schedule_*.xlsx", "posts": posts}
        ledger.write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8", newline="\n")
    print(f"✅ チェック合格：{args.exam} {len(posts)}日分（{posts[0]['date']}〜{posts[-1]['date']}）"
          f" 朝 {posts[0]['morning_time']}／夜 {posts[0]['evening_time']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

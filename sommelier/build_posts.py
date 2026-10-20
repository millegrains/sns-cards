"""原稿（tweets_x_full.txt）から台帳（posts.json）を作る変換プログラム。

使い方（保管庫のいちばん上のフォルダで実行）:
    python sommelier/build_posts.py            # 台帳を作り直す＋自動チェック
    python sommelier/build_posts.py --check    # 作り直さずに、今の台帳をチェックだけする

原稿を直したら、sommelier/source/tweets_x_full.txt を差し替えてから実行してください。
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
SOURCE = HERE / "source" / "tweets_x_full.txt"
GUIDE = HERE / "source" / "card_attach_guide.txt"
LEDGER = HERE / "posts.json"

THREADS_LIMIT = 500

HEADER_RE = re.compile(
    r"^===== (\d{4})/(\d{2})/(\d{2})\s+(P\d+)\s+\[(.*)\]\s+card=(\S+)\s+=====$"
)
SECTION_RE = re.compile(r"^--- (朝|夜) (\d{2}:\d{2})\s+\(\d+/\d+\) ---$")
GUIDE_RE = re.compile(r"^(\d{4})/(\d{2})/(\d{2})\s+→\s+(\S+)\s+\[(.*)\]\s*$")


def _clean(lines: list[str]) -> str:
    while lines and not lines[0].strip():
        lines.pop(0)
    while lines and not lines[-1].strip():
        lines.pop()
    return "\n".join(line.rstrip() for line in lines)


def parse_source(path: Path) -> list[dict]:
    posts: list[dict] = []
    current: dict | None = None
    section: str | None = None
    buf: list[str] = []

    def flush() -> None:
        if current is not None and section is not None:
            current[section] = _clean(buf)

    for lineno, raw in enumerate(path.read_text(encoding="utf-8-sig").splitlines(), 1):
        line = raw.rstrip()
        m = HEADER_RE.match(line)
        if m:
            flush()
            y, mo, d, no, category, card = m.groups()
            current = {
                "date": f"{y}-{mo}-{d}",
                "no": no,
                "category": category,
                "card": card,
            }
            posts.append(current)
            section, buf = None, []
            continue
        m = SECTION_RE.match(line)
        if m:
            if current is None:
                raise SystemExit(f"{lineno}行目: 見出し行より前に朝/夜の区切りがあります")
            flush()
            section = "morning" if m.group(1) == "朝" else "evening"
            current[f"{section}_time"] = m.group(2)
            buf = []
            continue
        if section is None:
            if line.strip():
                raise SystemExit(f"{lineno}行目: どの回にも属さない行があります: {line}")
            continue
        buf.append(line)
    flush()
    return posts


def parse_guide(path: Path) -> dict[str, tuple[str, str]]:
    result: dict[str, tuple[str, str]] = {}
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        m = GUIDE_RE.match(line.strip())
        if m:
            y, mo, d, card, category = m.groups()
            result[f"{y}-{mo}-{d}"] = (card, category)
    return result


def check(posts: list[dict]) -> list[str]:
    """問題があれば日本語の説明のリストを返す（空なら合格）。"""
    problems: list[str] = []
    if len(posts) != 366:
        problems.append(f"日数が366ではありません（{len(posts)}日分）")

    guide = parse_guide(GUIDE) if GUIDE.exists() else None
    if guide is None:
        problems.append(f"対応表が見つかりません: {GUIDE}")
    elif len(guide) != len(posts):
        problems.append(f"対応表の日数（{len(guide)}）と台帳の日数（{len(posts)}）が違います")

    prev: dt.date | None = None
    for p in posts:
        d = dt.date.fromisoformat(p["date"])
        tag = f"{p['date']} {p['no']}"
        if prev is not None and d != prev + dt.timedelta(days=1):
            problems.append(f"{tag}: 前の日（{prev}）から日付が連続していません")
        prev = d
        for key in ("morning", "evening"):
            if not p.get(key):
                problems.append(f"{tag}: {'朝' if key == 'morning' else '夜'}の本文が空です")
            elif len(p[key]) > THREADS_LIMIT:
                problems.append(
                    f"{tag}: {'朝' if key == 'morning' else '夜'}の本文が"
                    f"Threadsの上限{THREADS_LIMIT}字を超えています（{len(p[key])}字）"
                )
        if not (REPO / p["card"]).exists():
            problems.append(f"{tag}: カード画像 {p['card']} が保管庫にありません")
        num = re.search(r"(\d+)\.png$", p["card"])
        if num and int(num.group(1)) != int(p["no"][1:]):
            problems.append(f"{tag}: 問題番号とカード番号（{p['card']}）が食い違っています")
        if guide is not None:
            g = guide.get(p["date"])
            if g is None:
                problems.append(f"{tag}: 対応表にこの日付がありません")
            else:
                if g[0] != p["card"]:
                    problems.append(f"{tag}: カードが対応表（{g[0]}）と違います（原稿は {p['card']}）")
                if g[1] != p["category"]:
                    problems.append(f"{tag}: 分野が対応表（{g[1]}）と違います（原稿は {p['category']}）")
    return problems


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--check", action="store_true", help="作り直さず、今の posts.json をチェックだけする")
    args = ap.parse_args()

    if args.check:
        posts = json.loads(LEDGER.read_text(encoding="utf-8"))["posts"]
    else:
        posts = parse_source(SOURCE)
        LEDGER.write_text(
            json.dumps(
                {"exam": "sommelier", "source": "sommelier/source/tweets_x_full.txt", "posts": posts},
                ensure_ascii=False,
                indent=1,
            )
            + "\n",
            encoding="utf-8",
            newline="\n",
        )
        print(f"台帳を書き出しました: {LEDGER.relative_to(REPO)}（{len(posts)}日分）")

    problems = check(posts)
    if problems:
        print(f"\n❌ チェックで {len(problems)} 件の問題が見つかりました:")
        for msg in problems:
            print("  - " + msg)
        return 1
    print(f"✅ チェック合格: {posts[0]['date']}〜{posts[-1]['date']} の{len(posts)}日分、"
          "日付・カード番号・分野が対応表と一致しています")
    return 0


if __name__ == "__main__":
    sys.exit(main())

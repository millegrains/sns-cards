"""1問一答を Instagram・Facebookページ・Threads へ投稿するプログラム。

資格ごとの設定（投稿先・時刻・Instagramの窓口の種類など）は autopost/exams.json にあります。
  ・ソムリエ … @millegrains（Instagram・Facebookページ・Threads）朝7:00／夜20:50
  ・マン管・賃管 … @millegrains_app（Threads・Instagram）。時刻は exams.json の morning_at／evening_at

GitHub Actions から朝・夜に呼ばれます。手元で試すときの例:
    python autopost/post.py --exam sommelier --dry-run                 # 明日の朝・夜の予定を表示
    python autopost/post.py --exam sommelier --dry-run --date 2026-12-01
    python autopost/post.py --exam sommelier --slot morning            # 本番（今日の朝の分）

合鍵（アクセストークン）や番号は、すべて環境変数（＝GitHubの金庫 Secrets）から読みます。
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

REPO = Path(__file__).resolve().parent.parent
CONFIG = REPO / "autopost" / "exams.json"
STATE = REPO / "autopost" / "state.json"

JST = dt.timezone(dt.timedelta(hours=9), "JST")
GRAPH_VERSION = os.environ.get('META_GRAPH_VERSION') or 'v26.0'
GRAPH = f"https://graph.facebook.com/{GRAPH_VERSION}"
IG_GRAPH = f"https://graph.instagram.com/{GRAPH_VERSION}"  # Instagramログイン方式（Facebookページを使わない）の窓口
THREADS = "https://graph.threads.net/v1.0"
THREADS_LIMIT = 500

PLATFORM_NAMES = {"instagram": "Instagram", "facebook": "Facebookページ", "threads": "Threads"}
SLOT_NAMES = {"morning": "朝（問題）", "evening": "夜（解答）"}
MORNING_AT = dt.time(7, 0)    # 朝の回の時刻（日本時間）。exams.json の morning_at があればそちらを使う
EVENING_AT = dt.time(20, 50)  # 夜の回の時刻（日本時間）。exams.json の evening_at があればそちらを使う
RETRY_LIMIT = 3               # 自動実行で同じ投稿先が続けて失敗したら、その回はあきらめる回数
APP_LINKS_RE = re.compile(r"^iOS → \S+\nAndroid → \S+$", re.MULTILINE)


class PostError(Exception):
    """本人にそのまま見せる日本語の失敗理由。"""


class NotConfigured(Exception):
    """その投稿先の合鍵がまだ金庫に無い（準備中なので飛ばす）。"""


# ---------------------------------------------------------------- 通信まわり

def _explain(name: str, err: dict) -> str:
    code = err.get("code")
    sub = err.get("error_subcode")
    raw = f"（Metaからの返答: code={code}{f'/{sub}' if sub else ''} {err.get('message', '')}）"
    if code == 190:
        why = f"{name}の合鍵（アクセストークン）が期限切れか無効です。README「合鍵の作り直し」を見て金庫を更新してください"
    elif code == 10 or (isinstance(code, int) and 200 <= code <= 299):
        why = f"{name}への投稿の許可（権限）が足りません。合鍵を発行するときの許可の選択を確認してください"
    elif code in (4, 17, 32, 613) or sub == 2207042:
        why = f"{name}の投稿回数の制限に引っかかりました。しばらく時間をおいてください"
    elif code == 368:
        why = f"{name}側で一時的に投稿がブロックされています。アプリで警告が出ていないか確認してください"
    elif code == 9004 or sub in (2207052, 2207003):
        why = f"{name}がカード画像を取りに来られませんでした（画像アドレスを確認してください）"
    elif code == 100:
        why = f"{name}に送った内容か番号（ID）に誤りがあります。金庫の番号が正しいか確認してください"
    else:
        why = f"{name}への投稿に失敗しました"
    return why + raw


def call(name: str, method: str, url: str, params: dict) -> dict:
    data = urllib.parse.urlencode(params).encode()
    if method == "GET":
        req = urllib.request.Request(f"{url}?{data.decode()}", method="GET")
    else:
        req = urllib.request.Request(url, data=data, method=method)
    try:
        with urllib.request.urlopen(req, timeout=60) as res:
            return json.loads(res.read().decode() or "{}")
    except urllib.error.HTTPError as e:
        try:
            err = json.loads(e.read().decode()).get("error", {})
        except Exception:
            err = {"message": f"HTTP {e.code}"}
        raise PostError(_explain(name, err)) from None
    except (urllib.error.URLError, TimeoutError) as e:
        raise PostError(f"{name}につながりませんでした（通信エラー: {getattr(e, 'reason', e)}）") from None


def check_image(url: str) -> None:
    req = urllib.request.Request(url, method="HEAD")
    try:
        with urllib.request.urlopen(req, timeout=30) as res:
            if res.status != 200:
                raise PostError(f"カード画像が公開アドレスで見つかりません: {url}（HTTP {res.status}）")
    except urllib.error.HTTPError as e:
        raise PostError(f"カード画像が公開アドレスで見つかりません: {url}（HTTP {e.code}）") from None
    except urllib.error.URLError as e:
        raise PostError(f"カード画像のアドレスにつながりません: {url}（{e.reason}）") from None


def need(*names: str) -> list[str]:
    missing = [n for n in names if not os.environ.get(n)]
    if missing:
        raise PostError("金庫（GitHub Secrets）に次の値が登録されていません: " + "、".join(missing))
    return [os.environ[n] for n in names]


# 投稿先ごとに「これが金庫に無ければ未設定」とみなす合鍵の名前
TOKEN_ENV = {"instagram": "META_PAGE_ACCESS_TOKEN", "facebook": "META_PAGE_ACCESS_TOKEN", "threads": "THREADS_ACCESS_TOKEN"}
IG_LOGIN_TOKEN_ENV = "IG_LOGIN_ACCESS_TOKEN"


def token_env(platform: str, exam: dict) -> str:
    if platform == "instagram" and exam.get("instagram_api") == "instagram_login":
        return IG_LOGIN_TOKEN_ENV
    return TOKEN_ENV[platform]


def configured(platform: str, exam: dict) -> bool:
    return bool(os.environ.get(token_env(platform, exam)))


def wait_ready(name: str, url: str, token: str, field: str) -> None:
    """画像の受け取り処理が終わるまで待つ（最大およそ2分）。"""
    for _ in range(40):
        info = call(name, "GET", url, {"fields": field, "access_token": token})
        status = info.get(field)
        if status in ("FINISHED", "PUBLISHED"):
            return
        if status in ("ERROR", "EXPIRED"):
            raise PostError(f"{name}が画像の受け取りに失敗しました（状態: {status} {info.get('error_message', '')}）")
        time.sleep(3)
    raise PostError(f"{name}の画像の受け取りが2分たっても終わりませんでした")


# ---------------------------------------------------------------- 各投稿先

def _instagram_endpoint(exam: dict) -> tuple[str, str, str]:
    """(窓口のアドレス, 合鍵, Instagramの番号) を返す。

    ソムリエ … Facebookログイン方式（Facebookページの合鍵、graph.facebook.com）
    マン管・賃管 … Instagramログイン方式（Instagramの合鍵、graph.instagram.com。Facebookページ不要）
    """
    if exam.get("instagram_api") == "instagram_login":
        (token,) = need(IG_LOGIN_TOKEN_ENV)
        ig = os.environ.get("IG_LOGIN_USER_ID")
        if not ig:
            me = call(PLATFORM_NAMES["instagram"], "GET", f"{IG_GRAPH}/me",
                      {"fields": "user_id,username", "access_token": token})
            ig = str(me.get("user_id") or me.get("id"))
        return IG_GRAPH, token, ig
    token, ig = need("META_PAGE_ACCESS_TOKEN", "IG_USER_ID")
    return GRAPH, token, ig


def instagram_post(image_url: str, text: str, exam: dict) -> str:
    base, token, ig = _instagram_endpoint(exam)
    name = PLATFORM_NAMES["instagram"]
    c = call(name, "POST", f"{base}/{ig}/media",
             {"image_url": image_url, "caption": text, "access_token": token})
    wait_ready(name, f"{base}/{c['id']}", token, "status_code")
    return call(name, "POST", f"{base}/{ig}/media_publish",
                {"creation_id": c["id"], "access_token": token})["id"]


def instagram_comment(media_id: str, text: str, image_url: str, exam: dict) -> str:
    base, token, _ = _instagram_endpoint(exam)
    return call(PLATFORM_NAMES["instagram"], "POST", f"{base}/{media_id}/comments",
                {"message": text, "access_token": token})["id"]


def facebook_post(image_url: str, text: str, exam: dict) -> str:
    token, page = need("META_PAGE_ACCESS_TOKEN", "FB_PAGE_ID")
    r = call(PLATFORM_NAMES["facebook"], "POST", f"{GRAPH}/{page}/photos",
             {"url": image_url, "message": text, "published": "true", "access_token": token})
    return r.get("post_id") or r["id"]


def facebook_comment(post_id: str, text: str, image_url: str, exam: dict) -> str:
    (token,) = need("META_PAGE_ACCESS_TOKEN")
    return call(PLATFORM_NAMES["facebook"], "POST", f"{GRAPH}/{post_id}/comments",
                {"message": text, "access_token": token})["id"]


def _threads_publish(params: dict) -> str:
    (token,) = need("THREADS_ACCESS_TOKEN")
    uid = os.environ.get("THREADS_USER_ID") or "me"
    name = PLATFORM_NAMES["threads"]
    if len(params["text"]) > THREADS_LIMIT:
        raise PostError(f"本文が{len(params['text'])}字あり、Threadsの上限{THREADS_LIMIT}字を超えるため投稿を止めました")
    c = call(name, "POST", f"{THREADS}/{uid}/threads", {**params, "access_token": token})
    wait_ready(name, f"{THREADS}/{c['id']}", token, "status")
    return call(name, "POST", f"{THREADS}/{uid}/threads_publish",
                {"creation_id": c["id"], "access_token": token})["id"]


def threads_post(image_url: str, text: str, exam: dict) -> str:
    return _threads_publish({"media_type": "IMAGE", "image_url": image_url, "text": text})


def threads_reply(parent_id: str, text: str, image_url: str, exam: dict) -> str:
    if exam.get("threads_reply_image"):  # マン管・賃管は夜の返信にもカード画像を付ける
        return _threads_publish({"media_type": "IMAGE", "image_url": image_url,
                                 "text": text, "reply_to_id": parent_id})
    return _threads_publish({"media_type": "TEXT", "text": text, "reply_to_id": parent_id})


POSTERS = {"instagram": instagram_post, "facebook": facebook_post, "threads": threads_post}
REPLIERS = {"instagram": instagram_comment, "facebook": facebook_comment, "threads": threads_reply}
REPLY_KIND = {"instagram": "朝の投稿へのコメント", "facebook": "朝の投稿へのコメント", "threads": "朝の投稿への返信"}


def reply_kind(platform: str, exam: dict) -> str:
    if platform == "threads" and exam.get("threads_reply_image"):
        return "朝の投稿への返信（カード画像付き）"
    return REPLY_KIND[platform]


# ---------------------------------------------------------------- 本文・台帳・記録

def adapt(platform: str, text: str, exam: dict) -> str:
    """原稿を各投稿先向けに直す（Instagramだけ、押せないリンクの行を「プロフィールのリンクから」に置き換え）。"""
    if platform != "instagram":
        return text
    rules = exam.get("instagram_replacements")
    if rules:
        # マン管・賃管: 決められた形のリンク行を置き換え、リンクが残ったら安全のため止める
        for pattern, repl in rules:
            text = re.sub(pattern, repl, text)
        if "http" in text:
            raise PostError("Instagram用の文面にリンク（http〜）が残っています。原稿のリンクの書き方が"
                            "想定と違うため、Instagramへの投稿を止めました（exams.json の置き換え文を確認）")
        return text
    new, n = APP_LINKS_RE.subn(exam["instagram_app_line"], text)
    if n == 0 and "http" in text:
        print(f"  ⚠ Instagram用の置き換え対象（iOS/Androidの2行）が見つかりませんでした")
    return new


def state_path(exam: dict) -> Path:
    """投稿記録のファイル。資格ごとに分けると、同じ時刻に動いても記録がぶつからない。"""
    return REPO / exam["state"] if exam.get("state") else STATE


def load_state(exam: dict) -> dict:
    path = state_path(exam)
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return {}


def save_state(state: dict, exam: dict) -> None:
    state_path(exam).write_text(json.dumps(state, ensure_ascii=False, indent=1, sort_keys=True) + "\n",
                                encoding="utf-8", newline="\n")


def plan(platform: str, slot: str, entry: dict, exam: dict, day_state: dict) -> tuple[str, str | None, str]:
    """(やること, 返信先の投稿番号, 本文) を決める。"""
    text = adapt(platform, entry[slot], exam)
    if slot == "morning":
        return "カード画像付きで投稿", None, text
    parent = day_state.get("morning", {}).get(platform, {}).get("id")
    if parent:
        return reply_kind(platform, exam), parent, text
    return "単独の投稿（朝の投稿が無いためカード画像付き）", None, text


# ---------------------------------------------------------------- 実行

def slot_times(exam: dict) -> tuple[dt.time, dt.time]:
    """資格ごとの朝・夜の時刻（exams.json に無ければソムリエの 7:00／20:50）。"""
    m = dt.time.fromisoformat(exam["morning_at"]) if exam.get("morning_at") else MORNING_AT
    e = dt.time.fromisoformat(exam["evening_at"]) if exam.get("evening_at") else EVENING_AT
    return m, e


def due_slot(now: dt.datetime, exam: dict | None = None) -> tuple[str, dt.date]:
    """今の日本時間から「いま投稿すべき回」を決める。

    GitHubの目覚ましは何時間も遅れることがあるため、起動時刻の日付ではなく
    「直前に来た 朝の時刻 か 夜の時刻 はどちらか」で判断する（ソムリエなら 7:00／20:50）。
      朝の時刻〜夜の時刻の前 → 今日の朝 ／ 夜の時刻〜23:59 → 今日の夜 ／ 0:00〜朝の時刻の前 → 前の日の夜
    """
    morning_at, evening_at = slot_times(exam or {})
    t = now.time()
    if t >= evening_at:
        return "evening", now.date()
    if t >= morning_at:
        return "morning", now.date()
    return "evening", now.date() - dt.timedelta(days=1)


def dry_run(exam_key: str, exam: dict, entries: dict, date: dt.date, slots: list[str]) -> int:
    entry = entries.get(date.isoformat())
    print(f"【試し（dry-run）】実際には投稿しません。対象日: {date.isoformat()}（日本時間）\n")
    if entry is None:
        print("台帳にこの日の分がありません（期間外）。この日は何も投稿されません。")
        return 0
    image_url = exam["image_base_url"] + entry["card"]
    print(f"問題番号 {entry['no']} ／ 分野 [{entry['category']}] ／ カード {image_url}")
    try:
        check_image(image_url)
        print("  ✓ カード画像は公開アドレスから取得できます")
    except PostError as e:
        print(f"  ❌ {e}")
    day_state = load_state(exam).get(exam_key, {}).get(date.isoformat(), {})
    for slot in slots:
        print("\n" + "=" * 60)
        print(f"{SLOT_NAMES[slot]}  {entry[slot + '_time']}")
        for platform in exam["platforms"]:
            done = day_state.get(slot, {}).get(platform)
            print("-" * 60)
            try:
                action, parent, text = plan(platform, slot, entry, exam, day_state)
            except PostError as e:
                print(f"▶ {PLATFORM_NAMES[platform]}: ❌ {e}")
                continue
            if done:
                print(f"▶ {PLATFORM_NAMES[platform]}: 投稿済みのためスキップ（番号 {done['id']}）")
                continue
            if slot == "evening" and parent is None:
                action = (f"{reply_kind(platform, exam)}"
                          "（※朝の投稿に成功していれば。朝が失敗した場合はカード画像付きの単独投稿）")
            print(f"▶ {PLATFORM_NAMES[platform]}: {action}（{len(text)}字）")
            print(text)
    return 0


def live(exam_key: str, exam: dict, entries: dict, today: dt.date, slot: str, only: list[str],
         retry_limit: bool = False) -> int:
    print(f"【本番】{exam['label']} {today.isoformat()}（日本時間）の{SLOT_NAMES[slot]}")
    entry = entries.get(today.isoformat())
    if entry is None:
        print("台帳に今日の分がありません（期間外）。何もせず終了します。")
        return 0
    print(f"問題番号 {entry['no']} ／ 分野 [{entry['category']}] ／ カード {entry['card']}")

    state = load_state(exam)
    day_state = state.setdefault(exam_key, {}).setdefault(today.isoformat(), {})
    image_url = exam["image_base_url"] + entry["card"]
    image_error: PostError | None = None
    failures: list[str] = []
    tries = day_state.setdefault("failures", {}).setdefault(slot, {})

    for platform in exam["platforms"]:
        name = PLATFORM_NAMES[platform]
        if only and platform not in only:
            print(f"・{name}: 今回は対象外（--only 指定）")
            continue
        done = day_state.get(slot, {}).get(platform)
        if done:
            print(f"・{name}: 投稿済みのためスキップ（番号 {done['id']}）")
            continue
        if exam.get("skip_platform_without_token") and not configured(platform, exam):
            print(f"・{name}: 合鍵（{token_env(platform, exam)}）がまだ金庫に無いため、今回は飛ばします（準備中）")
            continue
        if retry_limit and tries.get(platform, 0) >= RETRY_LIMIT:
            print(f"・{name}: この回は{RETRY_LIMIT}回続けて失敗したため、今回は試しません"
                  "（原因を直したら手動ボタンで実行してください）")
            continue
        try:
            action, parent, text = plan(platform, slot, entry, exam, day_state)
            if parent:
                if exam.get("threads_reply_image") and platform == "threads":
                    if image_error is None:
                        try:
                            check_image(image_url)
                        except PostError as e:
                            image_error = e
                    if image_error:
                        raise image_error
                new_id = REPLIERS[platform](parent, text, image_url, exam)
            else:
                if image_error is None:
                    try:
                        check_image(image_url)
                    except PostError as e:
                        image_error = e
                if image_error:
                    raise image_error
                new_id = POSTERS[platform](image_url, text, exam)
        except PostError as e:
            failures.append(f"{name}: {e}")
            tries[platform] = tries.get(platform, 0) + 1
            save_state(state, exam)
            print(f"・{name}: ❌ 失敗 … {e}")
            print(f"::error title={name}の投稿に失敗::{e}")
            continue
        day_state.setdefault(slot, {})[platform] = {
            "id": new_id,
            "kind": action,
            "at": dt.datetime.now(JST).isoformat(timespec="seconds"),
        }
        tries.pop(platform, None)
        save_state(state, exam)  # 1か所ごとにすぐ記録（途中で止まっても二重投稿しないように）
        print(f"・{name}: ✅ 完了 … {action}（番号 {new_id}）")

    if failures:
        print(f"\n{len(failures)}か所で失敗しました。成功した投稿先は記録済みなので、"
              "原因を直して手動ボタン（本番）で同じ回を実行すれば、失敗した所だけ投稿されます。")
        return 1
    print("\nすべて完了しました。")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--exam", default="sommelier", help="資格名（autopost/exams.json の名前）")
    ap.add_argument("--slot", choices=["auto", "morning", "evening"],
                    help="auto=今の時刻から自動で判断／morning=今日の朝／evening=今日の夜")
    ap.add_argument("--dry-run", action="store_true", help="投稿せずに内容を表示するだけ")
    ap.add_argument("--date", help="試しで表示する日付 YYYY-MM-DD（省略時は明日）。本番では使えません")
    ap.add_argument("--only", default="", help="本番で一部の投稿先だけにする（例: threads,facebook）")
    args = ap.parse_args()

    exams = json.loads(CONFIG.read_text(encoding="utf-8"))
    if args.exam not in exams:
        print(f"資格名 {args.exam} は autopost/exams.json にありません")
        return 2
    exam = exams[args.exam]
    entries = {p["date"]: p for p in json.loads((REPO / exam["ledger"]).read_text(encoding="utf-8"))["posts"]}
    today = dt.datetime.now(JST).date()

    if args.dry_run:
        date = dt.date.fromisoformat(args.date) if args.date else today + dt.timedelta(days=1)
        return dry_run(args.exam, exam, entries, date, [args.slot] if args.slot else ["morning", "evening"])

    if not args.slot:
        print("本番では --slot auto／morning／evening のどれかが必要です")
        return 2
    if args.date:
        print("本番では日付を指定できません（日本時間の今日の分だけを投稿します）")
        return 2
    only = [s.strip() for s in args.only.split(",") if s.strip()]
    bad = [s for s in only if s not in exam["platforms"]]
    if bad:
        print("--only に不明な投稿先があります: " + "、".join(bad))
        return 2
    slot = args.slot
    if slot == "auto":
        slot, today = due_slot(dt.datetime.now(JST), exam)
        print(f"（自動判定）今の時刻なら {today.isoformat()} の{SLOT_NAMES[slot]}の番です")
    return live(args.exam, exam, entries, today, slot, only, retry_limit=args.slot == "auto")


if __name__ == "__main__":
    sys.exit(main())

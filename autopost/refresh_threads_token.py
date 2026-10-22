"""Threads／Instagram の合鍵（60日で切れる）を延長し、新しい合鍵をファイルに書き出す。

GitHub Actions の「Threads合鍵の自動延長」「アプリ用合鍵の自動延長」から月1回呼ばれ、
書き出した合鍵はワークフローが金庫（Secrets）に上書きします。

使い方:
    python autopost/refresh_threads_token.py <書き出し先>
        … 環境変数 THREADS_ACCESS_TOKEN（ソムリエの Threads）を延長する（従来どおり）
    python autopost/refresh_threads_token.py <書き出し先> --kind threads --env APP_THREADS_ACCESS_TOKEN
    python autopost/refresh_threads_token.py <書き出し先> --kind instagram --env APP_IG_ACCESS_TOKEN
        … @millegrains_app の合鍵を延長する
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

sys.stdout.reconfigure(encoding="utf-8")

KINDS = {
    "threads": ("Threads", "https://graph.threads.net/refresh_access_token", "th_refresh_token"),
    "instagram": ("Instagram", "https://graph.instagram.com/refresh_access_token", "ig_refresh_token"),
}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("out", help="新しい合鍵の書き出し先")
    ap.add_argument("--kind", choices=list(KINDS), default="threads")
    ap.add_argument("--env", default="THREADS_ACCESS_TOKEN", help="今の合鍵が入っている環境変数の名前")
    args = ap.parse_args()

    label, url, grant = KINDS[args.kind]
    token = os.environ.get(args.env)
    if not token:
        print(f"::error::金庫に {args.env} が登録されていません")
        return 1
    query = urllib.parse.urlencode({"grant_type": grant, "access_token": token})
    try:
        with urllib.request.urlopen(f"{url}?{query}", timeout=60) as res:
            data = json.loads(res.read().decode())
    except urllib.error.HTTPError as e:
        try:
            msg = json.loads(e.read().decode()).get("error", {}).get("message", "")
        except Exception:
            msg = f"HTTP {e.code}"
        print(f"::error title={label}合鍵の延長に失敗::{label}の合鍵（{args.env}）を延長できませんでした。"
              "すでに期限切れの可能性があります。README の「合鍵の作り直し」を見て、"
              f"新しい合鍵を金庫に登録してください（Metaからの返答: {msg}）")
        return 1
    except urllib.error.URLError as e:
        print(f"::error::{label}につながりませんでした（通信エラー: {e.reason}）")
        return 1

    new_token = data.get("access_token")
    if not new_token:
        print(f"::error::{label}からの返答に新しい合鍵が入っていませんでした")
        return 1
    print(f"::add-mask::{new_token}")
    with open(args.out, "w", encoding="utf-8") as f:
        f.write(new_token)
    days = int(data.get("expires_in", 0)) // 86400
    print(f"✅ {label}の合鍵（{args.env}）を延長しました（新しい期限: 約{days}日後）")
    return 0


if __name__ == "__main__":
    sys.exit(main())

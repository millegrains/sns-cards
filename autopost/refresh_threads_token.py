"""Threadsの合鍵（60日で切れる）を延長し、新しい合鍵をファイルに書き出す。

GitHub Actions の「Threads合鍵の自動延長」から月1回呼ばれ、
書き出した合鍵はワークフローが金庫（Secrets）の THREADS_ACCESS_TOKEN に上書きします。
"""
from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

sys.stdout.reconfigure(encoding="utf-8")


def main() -> int:
    if len(sys.argv) != 2:
        print("使い方: python autopost/refresh_threads_token.py <新しい合鍵の書き出し先>")
        return 2
    token = os.environ.get("THREADS_ACCESS_TOKEN")
    if not token:
        print("::error::金庫に THREADS_ACCESS_TOKEN が登録されていません")
        return 1
    query = urllib.parse.urlencode({"grant_type": "th_refresh_token", "access_token": token})
    try:
        with urllib.request.urlopen(f"https://graph.threads.net/refresh_access_token?{query}", timeout=60) as res:
            data = json.loads(res.read().decode())
    except urllib.error.HTTPError as e:
        try:
            msg = json.loads(e.read().decode()).get("error", {}).get("message", "")
        except Exception:
            msg = f"HTTP {e.code}"
        print("::error title=Threads合鍵の延長に失敗::Threadsの合鍵を延長できませんでした。"
              "すでに期限切れの可能性があります。README「Threadsの合鍵を作り直す」を見て、"
              f"新しい合鍵を金庫に登録してください（Metaからの返答: {msg}）")
        return 1
    except urllib.error.URLError as e:
        print(f"::error::Threadsにつながりませんでした（通信エラー: {e.reason}）")
        return 1

    new_token = data.get("access_token")
    if not new_token:
        print("::error::Threadsからの返答に新しい合鍵が入っていませんでした")
        return 1
    print(f"::add-mask::{new_token}")
    with open(sys.argv[1], "w", encoding="utf-8") as f:
        f.write(new_token)
    days = int(data.get("expires_in", 0)) // 86400
    print(f"✅ Threadsの合鍵を延長しました（新しい期限: 約{days}日後）")
    return 0


if __name__ == "__main__":
    sys.exit(main())

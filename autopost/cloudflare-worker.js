// 外部の目覚まし（Cloudflare Workers のスケジュール機能で動かす）
//
// 「1分ごとに鳴る目覚まし」1つで動き、下の時刻表の時刻（日本時間）になったら、
// GitHub の自動投稿ワークフローを slot=auto・mode=live で起動する。
// GitHub 自前の目覚まし（schedule）は数時間遅れることがあるため、時刻どおりの起動はこちらが受け持つ。
// 何度起動しても、投稿済みの分は投稿記録を見てスキップされるので二重投稿にはならない。
// （各ワークフローのスイッチ AUTOPOST_ENABLED／CHINTAI_…／MANKAN_… が true でなければ投稿もしない）
//
// Cloudflare 側の設定（autopost/README.md 9章・10章）:
//   ・Secret  GITHUB_TOKEN … sns-cards の Actions を Read and write できる GitHub の個人用合鍵
//   ・Cron Triggers … "* * * * *"（毎分）を1つだけ
//
// 時刻表（日本時間 "時:分" → 起動するワークフロー）。後ろの時刻は予備（二重投稿はしない）
const TIMETABLE = {
  "7:00": ["sommelier-autopost.yml"],
  "7:05": ["sommelier-autopost.yml"],
  "7:25": ["chintai-autopost.yml"],
  "7:30": ["chintai-autopost.yml"],
  "7:55": ["mankan-autopost.yml"],
  "8:00": ["mankan-autopost.yml"],
  "20:25": ["chintai-autopost.yml"],
  "20:30": ["chintai-autopost.yml"],
  "20:50": ["sommelier-autopost.yml"],
  "20:55": ["sommelier-autopost.yml", "mankan-autopost.yml"],
  "21:00": ["mankan-autopost.yml"],
};

const API = "https://api.github.com/repos/millegrains/sns-cards/actions/workflows/";

async function dispatch(env, workflow) {
  const res = await fetch(`${API}${workflow}/dispatches`, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${env.GITHUB_TOKEN}`,
      Accept: "application/vnd.github+json",
      "X-GitHub-Api-Version": "2022-11-28",
      "User-Agent": "millegrains-autopost-alarm",
    },
    body: JSON.stringify({ ref: "main", inputs: { slot: "auto", mode: "live" } }),
  });
  if (res.status !== 204) {
    throw new Error(`${workflow} の起動に失敗しました（HTTP ${res.status}）: ${await res.text()}`);
  }
  console.log(`${workflow} を起動しました`);
}

export default {
  async scheduled(event, env, ctx) {
    // 目覚ましが鳴った時刻（世界標準時）を日本時間（+9時間）に直して、時刻表と照らす
    const jst = new Date(event.scheduledTime + 9 * 60 * 60 * 1000);
    const key = `${jst.getUTCHours()}:${String(jst.getUTCMinutes()).padStart(2, "0")}`;
    const workflows = TIMETABLE[key];
    if (!workflows) return; // この分は何もしない
    const results = await Promise.allSettled(workflows.map((w) => dispatch(env, w)));
    const failed = results.filter((r) => r.status === "rejected");
    if (failed.length) {
      throw new Error(failed.map((r) => r.reason.message).join(" ／ "));
    }
  },
};

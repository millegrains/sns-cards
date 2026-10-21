// 外部の目覚まし（Cloudflare Workers のスケジュール機能で動かす）
//
// 日本時間 7:00 と 20:50 ちょうどに、GitHub の「ソムリエ自動投稿」を slot=auto・mode=live で起動する。
// GitHub 自前の目覚まし（schedule）は数時間遅れることがあるため、時刻どおりの起動はこちらが受け持つ。
// 何度起動しても、投稿済みの分は state.json を見てスキップされるので二重投稿にはならない。
//
// Cloudflare 側の設定（autopost/README.md 9章）:
//   ・Secret  GITHUB_TOKEN … sns-cards の Actions を Read and write できる GitHub の個人用合鍵
//   ・Cron Triggers（世界標準時で指定）… "0 22 * * *"（朝7:00） "50 11 * * *"（夜20:50）
//                                       予備に "5 22 * * *"（7:05） "55 11 * * *"（20:55）

const WORKFLOW_URL =
  "https://api.github.com/repos/millegrains/sns-cards/actions/workflows/sommelier-autopost.yml/dispatches";

export default {
  async scheduled(event, env, ctx) {
    const res = await fetch(WORKFLOW_URL, {
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
      throw new Error(`GitHubの起動に失敗しました（HTTP ${res.status}）: ${await res.text()}`);
    }
    console.log(`GitHubの自動投稿を起動しました（${event.cron}）`);
  },
};

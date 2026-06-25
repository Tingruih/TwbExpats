# Cloudflare Worker 事件驅動更新 + JSON API Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 將 MLB 追蹤網站從每日 2 次排程更新改為「比賽結束後約 15 分鐘自動更新」，同時輸出結構化 JSON API 供自動發文 bot 使用。

**Architecture:** Cloudflare Worker 每 5 分鐘輪詢 MLB schedule API，偵測追蹤球員所在隊伍的比賽從 Live → Final，透過 GitHub `repository_dispatch` 觸發 GitHub Actions build。Builder 同時產生 `dist/watcher-config.json`（Worker 讀取現役隊伍 ID）和 `dist/api/recent-games.json`（bot 讀取最近 7 天比賽數據）。

**Tech Stack:** Cloudflare Workers (JavaScript ES Module), Cloudflare KV, Wrangler CLI, GitHub Actions `repository_dispatch`, Python (builder.py 修改)

---

## 延遲估算

| 階段 | 時間 |
|---|---|
| 比賽結束，MLB API 更新 | +1–5 分鐘 |
| Worker 偵測到 Final（cron 間隔） | +0–5 分鐘（Cloudflare cron 通常 <30s 延遲） |
| repository_dispatch → Actions 進入佇列 | +<1 分鐘 |
| Python setup + GDrive restore | +2–3 分鐘 |
| `python build.py refresh` | +3–10 分鐘 |
| GitHub Pages 部署 | +1–2 分鐘 |
| **總計（典型）** | **~10–25 分鐘** |

現有排程（2x/天）保留作為 fallback，dispatch-build.yml 是新增的快速路徑。

## 安全設計

- GitHub PAT 以 `wrangler secret put` 加密存入 Cloudflare，不寫進程式碼或 git
- Fine-grained PAT：只對 `tingruih/twbexpats` repo 開放 "Actions: Write" 權限
- KV 中的 `last_dispatch_time` 確保每 25 分鐘最多觸發一次 build，防止多場比賽同時結束造成 build 堆積
- `pages.yml` 不修改，保持每日 fallback

## JSON API 設計

**`dist/watcher-config.json`**（Worker 用）
```json
{
  "team_ids": [143, 147, 158],
  "generated_at": "2026-06-17T20:30:00+08:00"
}
```

**`dist/api/recent-games.json`**（Bot 用）
```json
{
  "generated_at": "2026-06-17T20:30:00+08:00",
  "days": 7,
  "games": [
    {
      "player_mlb_id": 678906,
      "player_name_tw": "林昱珉",
      "player_name_en": "Yu-Min Lin",
      "date": "2026-06-17",
      "game_id": 718934,
      "opponent": "NYY",
      "is_home": true,
      "sport_level": "MLB",
      "stats": { "ip": "6.0", "er": 1, "k": 8, "bb": 2 }
    }
  ]
}
```

---

## File Map

**修改：**
- `site_builder/builder.py` — 加 `import json`，加 `_write_watcher_config()` + `_write_recent_games_api()` 兩個 helper function，在 `build_static_site()` 的 `conn.close()` 之前呼叫它們

**新增：**
- `.github/workflows/dispatch-build.yml` — 監聽 `repository_dispatch` 事件的 workflow（複製 pages.yml 結構，只改 trigger）
- `cloudflare/worker.js` — Cloudflare Worker：輪詢 MLB → 比對 KV 狀態 → 觸發 dispatch
- `cloudflare/wrangler.toml` — Worker 設定：名稱、cron、KV binding

---

## Task 1: 修改 builder.py — 產生 watcher-config.json 和 api/recent-games.json

**Files:**
- Modify: `site_builder/builder.py`

- [ ] **Step 1: 在 builder.py 頂部加入 `import json`**

在第 4 行 `import datetime` 之後加入：

```python
import json
```

- [ ] **Step 2: 在 `build_static_site` 函數定義前（約第 825 行之前）加入兩個 helper function**

```python
def _write_watcher_config(out_dir: Path, bundles: list, now_utc8) -> None:
    team_ids = sorted({
        player.team_id
        for player, _, _ in bundles
        if player.team_id
    })
    config = {
        "team_ids": team_ids,
        "generated_at": now_utc8.isoformat(),
    }
    (out_dir / "watcher-config.json").write_text(
        json.dumps(config, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def _write_recent_games_api(out_dir: Path, bundles: list, days: int = 7) -> None:
    cutoff = datetime.date.today() - datetime.timedelta(days=days)
    recent = []
    for player, _, logs in bundles:
        for log in logs:
            if not log.date or log.date < cutoff:
                continue
            recent.append({
                "player_mlb_id": player.mlb_id,
                "player_name_tw": player.name_tw,
                "player_name_en": player.name_en,
                "date": log.date.isoformat(),
                "game_id": log.game_id,
                "opponent": log.opponent,
                "is_home": log.is_home,
                "sport_level": log.sport_level,
                "stats": log.stats_json or {},
            })
    recent.sort(key=lambda x: x["date"], reverse=True)
    api_dir = out_dir / "api"
    api_dir.mkdir(exist_ok=True)
    now_utc8 = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=8)))
    (api_dir / "recent-games.json").write_text(
        json.dumps(
            {"games": recent, "days": days, "generated_at": now_utc8.isoformat()},
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
```

- [ ] **Step 3: 在 `build_static_site()` 的 `conn.close()` 之前呼叫兩個 helper**

找到 `build_static_site()` 末尾（約第 1128 行）的 `conn.close()`，在它之前插入：

```python
    _write_watcher_config(out_dir, bundles, now_utc8)
    _write_recent_games_api(out_dir, bundles)
```

- [ ] **Step 4: 本地驗證**

```bash
python build.py build
```

預期：
```
Built XX player pages + index to .../dist
```

然後確認檔案存在：
```bash
python -m json.tool dist/watcher-config.json
python -m json.tool dist/api/recent-games.json | head -40
```

`watcher-config.json` 應有 `team_ids` 陣列（整數列表）。
`recent-games.json` 應有 `games` 陣列，每個元素有 `player_mlb_id`, `date`, `stats` 等欄位。

- [ ] **Step 5: Commit**

```bash
git add site_builder/builder.py
git commit -m "feat: generate watcher-config.json and api/recent-games.json on build"
```

---

## Task 2: 新增 `.github/workflows/dispatch-build.yml`

**Files:**
- Create: `.github/workflows/dispatch-build.yml`

- [ ] **Step 1: 建立檔案**

```yaml
name: Dispatch Build (event-driven)

on:
  repository_dispatch:
    types: [mlb-game-final]

permissions:
  contents: read
  pages: write
  id-token: write

concurrency:
  group: "pages"
  cancel-in-progress: false

env:
  DEFAULT_SEASON_YEAR: "2026"
  GDRIVE_CLIENT_ID: ${{ secrets.GDRIVE_CLIENT_ID }}
  GDRIVE_CLIENT_SECRET: ${{ secrets.GDRIVE_CLIENT_SECRET }}
  GDRIVE_REFRESH_TOKEN: ${{ secrets.GDRIVE_REFRESH_TOKEN }}
  GDRIVE_FILE_ID: ${{ secrets.GDRIVE_FILE_ID }}

jobs:
  build-and-deploy:
    runs-on: ubuntu-latest
    environment:
      name: github-pages
      url: ${{ steps.deployment.outputs.page_url }}

    steps:
      - uses: actions/checkout@v4

      - uses: actions/setup-python@v5
        with:
          python-version: "3.13.12"
          cache: "pip"

      - name: Install dependencies
        run: pip install -r requirements.txt

      - name: Resolve GitHub Pages base URL
        run: |
          REPO_NAME="${GITHUB_REPOSITORY#*/}"
          OWNER_NAME="${GITHUB_REPOSITORY_OWNER}"
          if [ "$REPO_NAME" = "$OWNER_NAME.github.io" ]; then
            echo "PAGES_BASE_URL=/" >> "$GITHUB_ENV"
          else
            echo "PAGES_BASE_URL=/$REPO_NAME/" >> "$GITHUB_ENV"
          fi

      - name: Restore DB from Google Drive
        run: |
          mkdir -p data
          TOKEN_JSON="$(curl -s -X POST https://oauth2.googleapis.com/token \
            -d client_id="$GDRIVE_CLIENT_ID" \
            -d client_secret="$GDRIVE_CLIENT_SECRET" \
            -d refresh_token="$GDRIVE_REFRESH_TOKEN" \
            -d grant_type=refresh_token)"
          ACCESS_TOKEN="$(echo "$TOKEN_JSON" | jq -r '.access_token')"
          if [ -z "$ACCESS_TOKEN" ] || [ "$ACCESS_TOKEN" = "null" ]; then
            echo "Failed to get access token"
            exit 1
          fi
          curl -fL \
            -H "Authorization: Bearer $ACCESS_TOKEN" \
            "https://www.googleapis.com/drive/v3/files/$GDRIVE_FILE_ID?alt=media" \
            -o data/tracker.sqlite3
          ls -lh data/tracker.sqlite3

      - name: Refresh & Build
        run: python build.py refresh --base-url "$PAGES_BASE_URL"

      - name: Upload DB to Google Drive
        if: success()
        run: |
          TOKEN_JSON="$(curl -s -X POST https://oauth2.googleapis.com/token \
            -d client_id="$GDRIVE_CLIENT_ID" \
            -d client_secret="$GDRIVE_CLIENT_SECRET" \
            -d refresh_token="$GDRIVE_REFRESH_TOKEN" \
            -d grant_type=refresh_token)"
          ACCESS_TOKEN="$(echo "$TOKEN_JSON" | jq -r '.access_token')"
          if [ -z "$ACCESS_TOKEN" ] || [ "$ACCESS_TOKEN" = "null" ]; then
            echo "Failed to get access token"
            exit 1
          fi
          curl -fL -X PATCH \
            -H "Authorization: Bearer $ACCESS_TOKEN" \
            -H "Content-Type: application/octet-stream" \
            --data-binary @data/tracker.sqlite3 \
            "https://www.googleapis.com/upload/drive/v3/files/$GDRIVE_FILE_ID?uploadType=media"

      - name: Setup Pages
        uses: actions/configure-pages@v5

      - name: Upload artifact
        uses: actions/upload-pages-artifact@v3
        with:
          path: dist

      - name: Deploy to GitHub Pages
        id: deployment
        uses: actions/deploy-pages@v4
```

- [ ] **Step 2: Push 並確認 workflow 出現**

```bash
git add .github/workflows/dispatch-build.yml
git commit -m "feat: add repository_dispatch workflow for event-driven builds"
git push
```

前往 GitHub → Actions 頁籤，確認 "Dispatch Build (event-driven)" 出現在 workflow 清單中。

---

## Task 3: 建立 `cloudflare/worker.js`

**Files:**
- Create: `cloudflare/worker.js`

- [ ] **Step 1: 建立 `cloudflare/` 目錄和 `worker.js`**

```javascript
const GITHUB_REPO = "tingruih/twbexpats";
const WATCHER_CONFIG_URL = "https://tingruih.github.io/twbexpats/watcher-config.json";
const DISPATCH_COOLDOWN_MS = 25 * 60 * 1000; // 25 分鐘冷卻，防止重複觸發

export default {
  async scheduled(_event, env, _ctx) {
    await checkAndDispatch(env);
  },
};

async function checkAndDispatch(env) {
  // 1. 從 GitHub Pages 取得目前追蹤球員的隊伍 ID 清單
  let teamIds;
  try {
    const resp = await fetch(WATCHER_CONFIG_URL, { cf: { cacheTtl: 300 } });
    if (!resp.ok) return;
    const cfg = await resp.json();
    teamIds = cfg.team_ids;
    if (!Array.isArray(teamIds) || teamIds.length === 0) return;
  } catch {
    return;
  }

  // 2. 冷卻時間檢查：25 分鐘內不重複 dispatch
  const lastDispatchStr = await env.WATCHER_KV.get("last_dispatch_time");
  if (lastDispatchStr && Date.now() - Number(lastDispatchStr) < DISPATCH_COOLDOWN_MS) {
    return;
  }

  // 3. 查詢 MLB schedule API — 使用美東時間的今日 + 昨日（避免跨日時區漏抓）
  const { yesterday, today } = getETDates();
  const scheduleUrl =
    `https://statsapi.mlb.com/api/v1/schedule` +
    `?teamId=${teamIds.join(",")}` +
    `&startDate=${yesterday}&endDate=${today}` +
    `&sportId=1,11,12,13,14,15,16` +
    `&fields=dates,games,gamePk,status,abstractGameState`;

  let currentGames;
  try {
    const resp = await fetch(scheduleUrl);
    if (!resp.ok) return;
    const data = await resp.json();
    currentGames = extractGames(data);
  } catch {
    return;
  }

  // 4. 從 KV 讀取上次已知的比賽狀態
  const prevStatesStr = await env.WATCHER_KV.get("game_states");
  const prevStates = prevStatesStr ? JSON.parse(prevStatesStr) : {};

  // 5. 偵測新出現的 Final 比賽（之前不是 Final，現在是）
  const newFinalPks = [];
  const nextStates = { ...prevStates };
  for (const { gamePk, status } of currentGames) {
    const key = String(gamePk);
    if (status === "Final" && prevStates[key] !== "Final") {
      newFinalPks.push(gamePk);
    }
    nextStates[key] = status;
  }

  // 6. 有新完賽比賽 → 觸發 GitHub Actions
  if (newFinalPks.length > 0) {
    const ok = await triggerDispatch(env.GITHUB_TOKEN, newFinalPks);
    if (ok) {
      await env.WATCHER_KV.put("last_dispatch_time", String(Date.now()));
      console.log(`Dispatched build. Finished game PKs: ${newFinalPks.join(", ")}`);
    }
  }

  // 永遠更新 KV 狀態（無論有無 dispatch）
  await env.WATCHER_KV.put("game_states", JSON.stringify(nextStates));
}

function extractGames(scheduleData) {
  const games = [];
  for (const dateEntry of scheduleData.dates ?? []) {
    for (const game of dateEntry.games ?? []) {
      games.push({
        gamePk: game.gamePk,
        status: game.status?.abstractGameState ?? "Unknown",
      });
    }
  }
  return games;
}

async function triggerDispatch(token, gamePks) {
  const resp = await fetch(
    `https://api.github.com/repos/${GITHUB_REPO}/dispatches`,
    {
      method: "POST",
      headers: {
        Authorization: `Bearer ${token}`,
        Accept: "application/vnd.github.v3+json",
        "Content-Type": "application/json",
        "User-Agent": "mlb-watcher/1.0",
      },
      body: JSON.stringify({
        event_type: "mlb-game-final",
        client_payload: { game_pks: gamePks },
      }),
    },
  );
  return resp.status === 204; // GitHub 成功回傳 204 No Content
}

function getETDates() {
  // 使用 UTC-5 保守估計美東時間（夏令時 EDT 是 UTC-4，用 UTC-5 不會漏掉當天晚間比賽）
  const etOffsetMs = -5 * 60 * 60 * 1000;
  const etNow = new Date(Date.now() + etOffsetMs);
  const today = etNow.toISOString().slice(0, 10);
  const yesterday = new Date(+etNow - 86_400_000).toISOString().slice(0, 10);
  return { today, yesterday };
}
```

- [ ] **Step 2: Commit**

```bash
git add cloudflare/worker.js
git commit -m "feat: add Cloudflare Worker for MLB game completion detection"
```

---

## Task 4: 建立 `cloudflare/wrangler.toml`

**Files:**
- Create: `cloudflare/wrangler.toml`

- [ ] **Step 1: 建立檔案（KV namespace ID 先留 placeholder，Task 5 填入）**

```toml
name = "mlb-watcher"
main = "worker.js"
compatibility_date = "2024-09-23"

[triggers]
crons = ["*/5 * * * *"]

[[kv_namespaces]]
binding = "WATCHER_KV"
id = "REPLACE_WITH_KV_NAMESPACE_ID"
```

- [ ] **Step 2: Commit**

```bash
git add cloudflare/wrangler.toml
git commit -m "chore: add wrangler config (KV ID to be filled in Task 5)"
git push
```

---

## Task 5: Cloudflare 帳號設定、KV 建立、部署（手動操作）

此 Task 必須在有 Cloudflare 帳號的環境中手動執行。

- [ ] **Step 1: 建立 Cloudflare 帳號**

前往 https://dash.cloudflare.com/sign-up 免費註冊（不需要信用卡）。

- [ ] **Step 2: 安裝 Wrangler CLI**

```bash
npm install -g wrangler
```

驗證：
```bash
wrangler --version
```
預期：`⛅️ wrangler X.X.X`

- [ ] **Step 3: 登入 Cloudflare**

```bash
cd cloudflare
wrangler login
```

瀏覽器開啟 Cloudflare OAuth 授權頁，點 Allow。Terminal 顯示 `✅ Successfully logged in.`

- [ ] **Step 4: 建立 KV namespace 並填入 wrangler.toml**

```bash
wrangler kv namespace create WATCHER_KV
```

預期輸出（範例）：
```
✅ Created namespace "mlb-watcher-WATCHER_KV"
[[kv_namespaces]]
binding = "WATCHER_KV"
id = "a1b2c3d4e5f6..."
```

將輸出中的 `id` 值填入 `cloudflare/wrangler.toml`，取代 `REPLACE_WITH_KV_NAMESPACE_ID`：

```bash
# 編輯 wrangler.toml，把 id 填進去
git add cloudflare/wrangler.toml
git commit -m "chore: fill in Cloudflare KV namespace ID"
git push
```

- [ ] **Step 5: 建立 GitHub Fine-grained PAT**

1. 前往 GitHub → Settings → Developer settings → Personal access tokens → Fine-grained tokens
2. Generate new token：
   - Token name: `mlb-watcher-cloudflare`
   - Expiration: 90 days（或自訂）
   - Repository access: Only select repositories → `tingruih/twbexpats`
   - Permissions → Repository permissions → **Actions: Read and write**
3. 複製產生的 token（只顯示一次）

- [ ] **Step 6: 將 PAT 存入 Worker secret**

```bash
wrangler secret put GITHUB_TOKEN
```

提示 `Enter a secret value:` 時貼上 PAT，按 Enter。預期：`✅ Successfully created secret GITHUB_TOKEN`

- [ ] **Step 7: 確認 watcher-config.json 已部署到 GitHub Pages**

先確認 Task 1 的 commit 已 push，且 pages.yml（或手動 trigger）已執行完一次：

```bash
curl -s https://tingruih.github.io/twbexpats/watcher-config.json | python -m json.tool
```

預期：回傳含 `team_ids` 的 JSON。若還沒部署，先手動 trigger pages.yml 一次。

- [ ] **Step 8: 部署 Worker**

```bash
wrangler deploy
```

預期輸出（節錄）：
```
✅ Uploaded mlb-watcher
✅ Published mlb-watcher
   https://mlb-watcher.<subdomain>.workers.dev
   schedule: */5 * * * *
```

---

## Task 6: 端到端驗證

- [ ] **Step 1: 在本地測試 Worker 執行（不觸發真正的 dispatch）**

```bash
cd cloudflare
wrangler dev --test-scheduled
```

開啟另一個 terminal：
```bash
curl "http://localhost:8787/__scheduled?cron=*+*+*+*+*"
```

觀察第一個 terminal 的 log。預期：Worker 正常執行，能 fetch MLB API 和 watcher-config.json。若今天沒有追蹤球員的比賽結束，Worker 靜默結束不 dispatch（正常行為）。

- [ ] **Step 2: 手動測試 repository_dispatch 觸發**

用 Step 5 建立的 PAT：

```bash
curl -X POST \
  -H "Authorization: Bearer <YOUR_PAT>" \
  -H "Accept: application/vnd.github.v3+json" \
  -H "Content-Type: application/json" \
  https://api.github.com/repos/tingruih/twbexpats/dispatches \
  -d '{"event_type":"mlb-game-final","client_payload":{"game_pks":[999999]}}'
```

預期：HTTP 204，GitHub Actions 頁面出現 "Dispatch Build (event-driven)" workflow 正在執行。

- [ ] **Step 3: 等待 Actions 完成後確認 JSON API**

```bash
curl -s https://tingruih.github.io/twbexpats/watcher-config.json | python -m json.tool
curl -s https://tingruih.github.io/twbexpats/api/recent-games.json | python -m json.tool | head -60
```

`recent-games.json` 應有最近 7 天比賽紀錄，每筆有 `player_name_tw`、`date`、`stats` 等欄位。

- [ ] **Step 4: 等待真實比賽完成（MLB 賽季期間）**

比賽結束後約 5–25 分鐘，觀察 GitHub Actions 頁面是否自動出現 "Dispatch Build" workflow。

---

## Bot 後續開發說明

Bot 只需要：
1. 訂閱 `dist/api/recent-games.json`（或定期 fetch）
2. 維護自己已發文的 `game_id` 集合（避免重複發文）
3. 當 `recent-games.json` 出現 bot 未處理過的 `game_id` 時，根據 `stats` 欄位組成貼文內容

Bot 可以是獨立的 GitHub Actions workflow（監聽 `repository_dispatch: mlb-game-final`，或另起 cron），也可以是 Cloudflare Worker（fetch `recent-games.json` 後比對自己的 KV state）。

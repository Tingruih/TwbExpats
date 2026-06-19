# 資料抓取與寫入流程分析報告（Taiwan MLB Tracker）

## Context

使用者想了解三件事：(1) API 抓取方式與所有端點全貌；(2) 以一位球員為例，哪些 API 提供的資料目前沒抓到；
(3) 抓取→寫入 DB 的流程哪裡可優化、如何提升處理效率。

本文件是**純分析報告（不改程式碼）**。所有結論都已對 `statsapi.mlb.com` 實際呼叫、並對現有 DB
（`data/tracker.sqlite3`：100 球員 / 689 季 / 15,870 場）實測驗證。使用者勾選的優化優先方向為四項全包：
減少 API 呼叫、DB 寫入效能、HTTP 層、補抓缺漏欄位。後續是否實作由使用者自行決定。

---

## 一、API 端點全覽（全部在 `site_builder/api.py`）

| 函式 | 端點 | 呼叫次數 / 成本 |
|---|---|---|
| `get_player_profile` (api.py:29) | `/people/{id}?hydrate=transactions,rosterEntries,currentTeam` + **額外** `/teams/{id}` (api.py:101) | 每位球員 **2 次**，第 2 次只為拿 sport level |
| `get_player_stats` (api.py:133) | `stats=yearByYear&group=hitting,pitching,fielding`（MLB + MiLB） | 2 次 |
| `get_player_advanced_stats` (api.py:164) | `stats=seasonAdvanced` **逐年迴圈** × (MLB + MiLB)（api.py:177） | ⚠️ **年份 × 2**。王建民 15 年 → 最多 30 次 |
| `get_game_logs` (api.py:207) | `stats=gameLog&season={y}` 逐季 × (MLB + MiLB) | 年份 × 2 |
| `get_player_sabermetrics` (api.py:369) | `stats=sabermetrics` 逐年迴圈（api.py:376） | statcast 年份數（量小） |
| `get_player_expected_stats` (api.py:391) | `stats=expectedStatistics` 逐年迴圈，僅 MLB（api.py:407） | statcast 年份數（量小） |
| `get_next_game` (api.py:241) | `/schedule?teamId=...&sportId=1,11,...` | 1 次 |
| `get_game_play_by_play` (api.py:302) | v1.1 `/game/{pk}/feed/live`（完整 live feed，payload 大） | 每場 1 次（已快取 + 並行） |
| `get_game_sport_level` (api.py:340) | v1.1 `feed/live?fields=...`（輕量） | 僅歷史 backfill |

**共通問題**：每個函式都直接用 `requests.get(...)`，沒有共用 `Session`，每次呼叫都重新 TCP/TLS 握手；也沒有 retry/backoff。

---

## 二、以鄧愷威 (mlb_id 678906) 為例：API 有、但目前沒抓的資料

### (A) Profile 層（`get_player_profile` 目前只取 api.py:110-130 的欄位）
實測 `/people/678906` 回傳但未擷取、且對球員頁有價值者：
- `mlbDebutDate`（實測 = `2024-03-31`）— MLB 初登板日
- `primaryNumber`（實測 = `17`）— 背號
- `draftYear` — 選秀年（此例為 None，但多數球員有）
- `nameSlug`（`kai-wei-teng-678906`）— 可用於連回 mlb.com 官方頁
- `pronunciation` — 英文發音
- `strikeZoneTop` / `strikeZoneBottom`（3.388 / 1.71）— 個人化好球帶上下緣
- `boxscoreName` / `useName` 等顯示用別名

### (B) Stats 群組 / type 層
- 目前 `group` 只有 `hitting,pitching,fielding`。捕手專屬 `catching` group、官方 `vs LHP/RHP`
  (`statSplits` + `sitCodes=vl,vr`)、官方 `hotColdZones`、官方 `pitchArsenal` 皆未使用
  （投打對位與 zone 目前都是自己從 play-by-play 重算，可考慮以官方數據交叉驗證或補充）。

### (C) Pitch-level 層（`extract_pitch_logs` 目前擷取 statcast.py:279-323）
實測一場 MLB 比賽的 `playEvents[].pitchData`，**有但沒抓**的欄位：
- `coordinates`: `vX0,vY0,vZ0`（初速向量）、`aX,aY,aZ`（加速度）— 目前只抓 `pfxX/Z, x0/z0, pX/pZ`
- `pitchData`: `plateTime`、`typeConfidence`、per-pitch `strikeZoneTop/Bottom/Width/Depth`
- `breaks`: `breakAngle`、`breakLength`、`breakVertical`（非 induced）、`breakY`
- play 層級的 `runners`（可算 RE24／推進）

> **最有價值的缺口**：要計算 **VAA / HAA（垂直/水平進壘角）**——當前最熱門的投手評估指標之一——
> 必須有 `vY0, vZ0, aY, aZ` + 釋放點，而這些正好都沒抓。目前的欄位**算不出 VAA**。

---

## 三、優化建議（依使用者勾選的四方向，依影響力排序）

### A. 減少 API 呼叫（影響最大，尤其全量 sync）

1. **`seasonAdvanced` 逐年迴圈 → 改用 `yearByYearAdvanced`（一次回傳所有年份）**
   - 實測：`stats=yearByYearAdvanced&group=pitching` 一次回傳 `2024,2025,2026` 全部。
   - 影響：`get_player_advanced_stats`（api.py:177 的 `for yr in fetch_years`）對王建民從「15 年 × 2 = 30 次」壓到「2 次」。
   - 注意：⚠️ 逗號多年 `season=2024,2025` 對 `seasonAdvanced`/`sabermetrics` **實測回傳空**，此路不通；
     只能靠 `yearByYear*` 變體。

2. **合併 stat type 到單一請求**
   - 實測：`stats=yearByYear,yearByYearAdvanced&group=...` 單一請求即回傳兩種 type。
   - 影響：`get_player_stats` + `get_player_advanced_stats` 可從「2 + (年份×2)」合併為「2 次」（MLB/MiLB 各一）。

3. **`get_player_profile` 的額外 `/teams/{id}` 呼叫（api.py:99-108）可移除**
   - 實測：`hydrate=currentTeam(sport)` **不會**帶出 sport，所以無法靠 hydrate 省。
   - 替代：sport level 其實已存在 `season_stats.sport_level`（sync 時寫入），或用 `currentTeam.id`
     做一次批次 `/teams?teamIds=...` 查詢（全 roster 合併成 1 次），取代每人 1 次。

4. **sabermetrics / expected**：逐年迴圈僅涉及「有 pitch data 的年份」，量小，優先度低；
   若要省可改抓 `yearByYear` 變體（sabermetrics 的 `yearByYear` type 實測可一次回傳多年）。

### B. DB 寫入效能

5. **開啟 WAL + 放寬 synchronous**（實測現有 DB `journal_mode=delete`）
   - 在 `_init_db`（sync.py:52）後加 `PRAGMA journal_mode=WAL; PRAGMA synchronous=NORMAL;`
   - 對 15,870 場的批量寫入，預設 rollback journal + `synchronous=FULL` 是主要瓶頸之一。

6. **消除 `_write_player_to_db` 的 N+1 read-modify-write**（sync.py:524-604）
   - 現況：yearByYear 迴圈與 seasonAdvanced 迴圈，對同一 `(player,year,team)` 各做一次
     `_load_season_row`（SELECT）+ `_save_season_row`（UPSERT）。
   - 建議：開頭一次撈出該球員所有 season rows 進記憶體 dict，全部在記憶體 merge，最後批次寫回。

7. **`game_logs` 改 `executemany`**（sync.py:650 目前每場一次 `cur.execute`）。

8. **commit 頻率**：`_write_player_to_db` 結尾每位球員 commit（sync.py:678）尚可；
   配合 WAL 後可考慮整批結束再 commit。

### C. HTTP 層

9. **共用 `requests.Session`**（目前每次 `requests.get` 都新建連線）
   - 用模組級 `Session` + `HTTPAdapter(pool_maxsize=MAX_WORKERS)` 啟用 keep-alive 連線池。
   - 掛上 `urllib3.util.Retry`（針對 429/5xx 做指數退避），補足目前完全沒有的重試機制。
   - 注意 `Session` 執行緒安全性：搭配既有 `ThreadPoolExecutor`（sync.py:743）使用 adapter 連線池即可。

### D. 補抓缺漏欄位

10. **Profile**：在 `get_player_profile` 回傳 dict 增補 `mlbDebutDate`、`primaryNumber`、`draftYear`、
    `nameSlug` 等；對應在 `players` 資料表（sync.py:54 schema）加欄位 + forward-migration（仿 sync.py:117 既有 `ALTER TABLE` 模式）+ 在 `player_detail.j2` 顯示。
11. **Pitch-level（高價值）**：在 `extract_pitch_logs`（statcast.py:279）增補 `vX0,vY0,vZ0,aX,aY,aZ,plateTime`，
    即可在 `statcast.py` 新增 VAA/HAA 計算（投手 arsenal 表新欄位）。
    - 注意：`pitches_json` 是既有快取，新欄位只會出現在「之後重抓」的場次；
      需要對歷史場次重跑 `build.py statcast`（`_pitches_need_hit_coord_backfill` at sync.py:878 是現成的「偵測舊資料需重抓」模式，可仿照新增一個 VAA 欄位偵測）。

### 額外觀察（statcast sync）
- `sync_statcast` Phase 3 為了拿年份，對每個 `(mlb_id, gpk)` 再 SELECT 一次 date（sync.py:1206），
  但 Phase 1（sync.py:1149）已掃過同一批列 → 可在 Phase 1 順手保留 date，省去 Phase 3 的重查。
- Phase 4「無條件對全 roster 全年份重算」（sync.py:1255 註解「this is cheap」）：在已有 `affected_years_by_player`
  （sync.py:1237）的情況下，可只重算受影響年份，省下大量 `compute_*_statcast` CPU 與 saber/expected 呼叫。

---

## 影響量化（以現有資料估算）

- 全量 `sync`：advanced 改 `yearByYearAdvanced` + 合併 type 後，**多年球員的 stats 相關呼叫**
  從「年份×2 + 2」降到「2」。以 roster 中多位 10–15 年老將計算，單次全量 sync 可省下數百次 HTTP 請求。
- 每人省去 1 次 `/teams` → 100 球員省 100 次。
- WAL + 批次寫入 + Session 連線重用：對 15,870 場規模的 I/O 與連線開銷有明顯加成（與 API 省量相乘）。

## 驗證方式（給後續實作時參考，本報告本身不改碼）

```bash
# 確認 yearByYearAdvanced 一次回傳多年
python3 -c "import requests;print([s.get('season') for s in requests.get('https://statsapi.mlb.com/api/v1/people/678906/stats?stats=yearByYearAdvanced&group=pitching').json()['stats'][0]['splits']])"

# 確認 profile 缺漏欄位存在
python3 -c "import requests;p=requests.get('https://statsapi.mlb.com/api/v1/people/678906?hydrate=currentTeam').json()['people'][0];print(p['mlbDebutDate'],p['primaryNumber'],p['nameSlug'])"

# 實作 API 省量後：比對單一球員 sync 前後的 HTTP 請求次數（可在 api.py 暫時加計數器）
# 實作 DB 優化後：time python build.py build  比較前後耗時；PRAGMA journal_mode 應為 wal
```

## 範圍備註
本次依使用者選擇僅輸出分析報告，**不修改任何程式碼**。若之後要實作，建議落地順序：
A1（yearByYearAdvanced）→ B5（WAL）→ C9（Session）→ B6（批次寫入）→ D（補欄位，VAA 最具價值）。

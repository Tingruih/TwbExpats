# TODO — Code Review 改進清單

> 最後更新：2026-05-08　完整逐檔 review（`git ls-files` 追蹤的所有檔案）。  
> 狀態說明：`[ ]` 未解決，`[x]` 已解決或已不存在。

---

## 🔴 Critical — 必須修正

### 安全性

- [ ] **`src/templates/player_detail.j2:1335-1368, 1408` — pitch log 使用 `innerHTML` 注入未跳脫字串（XSS）**
  - 問題：`_buildPitchTable()` 直接把 `p.pitch_name`、`p.result`、`p.pa_event` 串入 HTML 字串，再由 `_renderPitchLog()`（line 1408）用 `container.innerHTML` 注入 DOM。Plinko 區塊（line 1653-1659）已有本地 `escapeHtml()`，pitch log 區塊缺少同樣處理。
  - 修正：在 `_buildPitchTable()` 開頭加 `escapeHtml()`，並對 class token 做 whitelist 過濾。

```js
function escapeHtml(value) {
    return String(value == null ? "" : value)
        .replace(/&/g, "&amp;").replace(/</g, "&lt;")
        .replace(/>/g, "&gt;").replace(/"/g, "&quot;")
        .replace(/'/g, "&#39;");
}
function safeClassToken(value) {
    return String(value || "").toLowerCase().replace(/[^a-z0-9_-]/g, "");
}
// 使用：
var pt = safeClassToken(p.pitch_type);
var pn = escapeHtml(p.pitch_name || p.pitch_type || "—");
h += '<td><span class="pitch-tag pitch-' + pt + '">' + pn + '</span></td>';
```

- [ ] **`site_builder/jinja_env.py:51-53` — `tojson_safe` 未跳脫 script context 危險字元**
  - 問題：`Markup(json.dumps(value, ensure_ascii=False))` 不跳脫 `</script>`、`<`、`>`、`&`，用於 `player_detail.j2:1188, 1967-1968` 的 `<script type="application/json">` 時，惡意資料可提前關閉 script tag 並注入任意 HTML/JS。
  - 修正：改用 `htmlsafe_json_dumps`。

```python
from jinja2.utils import htmlsafe_json_dumps
from markupsafe import Markup

def tojson_safe(value):
    return Markup(htmlsafe_json_dumps(value, ensure_ascii=False))
```

### 資料安全性

- [ ] **`site_builder/builder.py:633-638` — `build_static_site()` 無條件 `rmtree(output_dir)` 無安全 guard**
  - 問題：`out_dir = Path(output_dir).resolve()` 後若存在就直接 `shutil.rmtree(out_dir)`，誤傳 `--output .`、`/`、`$HOME` 等路徑會造成不可逆刪除。
  - 修正：限制輸出目錄必須在專案內且不可等於專案根目錄。

```python
out_dir = Path(output_dir).resolve()
project_root = _PROJECT_ROOT.resolve()
if out_dir == project_root or project_root not in out_dir.parents:
    raise SystemExit(f"Refusing to delete unsafe output directory: {out_dir}")
if out_dir.exists():
    shutil.rmtree(out_dir)
```

- [ ] **`site_builder/api.py:120-127` — MiLB `yearByYear` 無 `try/except`，失敗時整批丟失 MLB 資料**
  - 問題：`get_player_stats()` 先成功 append MLB stats，接著 MiLB request（line 125-127）若 timeout/HTTP error 直接拋出，外層 `_fetch_player_data()` 捕捉後 `stats_groups` 保持空 list，MLB + MiLB 資料全部失效。
  - 修正：MiLB endpoint 同樣包 `try/except`。

```python
try:
    resp = requests.get(url, timeout=TIMEOUT)
    resp.raise_for_status()
    all_stats.extend(resp.json().get("stats", []))
except Exception as e:
    logger.warning("MiLB yearByYear failed for %s: %s", mlb_id, e)
```

---

## 🔴 Data Correctness Bugs — 數據錯誤

- [ ] **`site_builder/statcast.py:1155-1177` / `site_builder/sync.py:914-925` — FIP 分母使用棒球小數 IP，系統性算錯 FIP**
  - 問題：`compute_fip()` 直接用 `ip` 當分母（line 1176），但 `7.2` 代表 7⅔ 局，不是 7.2 局。`sync.py:914-925` 把原始 `ip` 欄位傳入而未轉換。
  - 修正：先轉成 outs，再換成真實局數（`ip_to_outs` 已在 `helpers.py` 可用）。

```python
from site_builder.helpers import ip_to_outs

ip_actual = ip_to_outs(ip) / 3.0
if ip_actual <= 0:
    return None
fip = (13 * hr + 3 * (bb + hbp) - 2 * k) / ip_actual + c_fip
```

- [ ] **`site_builder/sync.py:87, 165` — `season_stats` UNIQUE key 缺少 `sport_level`，同年同隊多層級可能互蓋**
  - 問題：schema `UNIQUE(player_mlb_id, year, team_name)` + `ON CONFLICT(player_mlb_id, year, team_name)` — 同球員同年在同名球隊但不同層級時會 collision 或覆蓋。
  - 修正：migration 加入 `sport_level`。

```sql
UNIQUE(player_mlb_id, year, team_name, sport_level)
-- 同步更新 ON CONFLICT 條件
```

- [ ] **`site_builder/helpers.py:269-281` — `compute_season_combined()` 缺少 `_compute_advanced_stats()`**
  - 問題：合計賽季列只呼叫 `_aggregate_stats()` (line 275)，未補算 ISO、BABIP、K%、BB%、P/PA 等進階欄位；跨層級球員的 bio combined 會出現空值。`compute_year_groups()` 已在 `helpers.py:558-559` 對 summary 做同樣處理，兩路不一致。
  - 修正：回傳前加 `_compute_advanced_stats(combined)`。

```python
combined["year"] = year
_compute_advanced_stats(combined)
return combined
```

- [ ] **`site_builder/statcast.py:626-629` — switch hitter（`"S"`）擊球方向被歸為右打邏輯**
  - 問題：`_spray_direction_from_coordinates()` 用 `if bat == "L": ...` else 預設右打（line 627-629）。`"S"` 或未知值都走右打邏輯，spray chart 百分比會偏移。
  - 修正：只在 bat 為明確 `"L"` 或 `"R"` 時計算；否則回傳 `None` 讓呼叫端跳過。

```python
if bat not in ("L", "R"):
    return None
if bat == "L":
    return "pull" if field == "RF" else "oppo"
return "pull" if field == "LF" else "oppo"
```

- [ ] **`site_builder/statcast.py:1036` — EV90 percentile index 對 10 的倍數樣本有 off-by-one**
  - 問題：`idx = min(int(len(ev_values) * 0.9), len(ev_values) - 1)` — `n=10` 時 `int(10*0.9)=9`，取到最大值（index 9），nearest-rank 90th percentile 應是 index 8。
  - 修正：用 ceiling nearest-rank 定義。

```python
import math
idx = max(0, math.ceil(len(ev_values) * 0.9) - 1)
ev90 = round(ev_values[idx], 1)
```

- [ ] **`site_builder/statcast.py:1162-1169` — FIP constant fallback 靜默使用舊年度常數**
  - 問題：目前只有 2024 年常數；其他年份靜默 fallback 到同層級 2024 值或最終 `3.2`，使用者不知道數字不是當年度常數。
  - 修正：fallback 時 log warning。

```python
logger.warning("FIP constant missing for %s/%s; using fallback %.3f", sport_level, year, c_fip)
```

- [ ] **`site_builder/builder.py:746-753` — `next_game` 快照有效性條件過寬（`>=` 當年）**
  - 問題：`(player.next_game_for_season or 0) >= datetime.date.today().year` 讓未來任意賽季快照都視為有效，可能顯示錯誤賽季賽程。
  - 修正：只接受等於 build 年度或當前真實年度。

```python
current_year = datetime.date.today().year
snapshot_valid = (
    isinstance(player.next_game_json, dict)
    and bool(player.next_game_json)
    and player.next_game_for_season in {year, current_year}
)
```

- [ ] **`site_builder/sync.py:99` — `game_logs UNIQUE(player_mlb_id, game_id)` 二刀流同場資料互蓋**
  - 問題：同球員同場兼任投打時，同一 `game_pk` 會有打擊與投球兩筆 game log；`ON CONFLICT DO UPDATE` 會讓後一筆覆蓋前一筆，等於丟失一個身份的逐場資料。
  - 修正：UNIQUE key 加入 `role` 欄位（`"batter"` / `"pitcher"`），或改為 `(player_mlb_id, game_id, stat_type)`。

- [ ] **`site_builder/sync.py:102-105, 1036-1060` — `playbyplay_processed` 以 game-pk 為單位，新球員加入後無法補抓**
  - 問題：若球員在某場比賽後才加入 roster，此 game_pk 已在 processed set，`pitches_json` 仍是 `[]`；line 1056-1060 只 `pass` 後繼續加入 `game_to_players`，但已 processed 的 game 在 Phase 2 會重複 fetch 整場 feed，浪費流量。真正需要的是 per-player-game 的 processed state。
  - 修正：在 `game_logs` 加 `pitches_processed_at TEXT` 欄位，以此判斷是否已處理。

```sql
ALTER TABLE game_logs ADD COLUMN pitches_processed_at TEXT;
```

---

## 🟡 架構 / 維護性

- [ ] **`site_builder/api.py:393` — `parse_roster_from_file()` 與 API client 職責不符**
  - 讀取本機 JSON 與 MLB HTTP API 無關，應移至 `helpers.py` 或 `roster.py`。

- [ ] **`site_builder/builder.py:80-481` — Statcast 合併邏輯放在 builder（計算層混入展示層）**
  - `_combine_pitch_type_data()`、`_combine_vs_pitch_types()`、`_combine_pitch_arsenal()`、`_combine_pitch_outcomes()`、`_combine_pitch_usage_by_count()`、`_combine_pitcher_bat_side_splits()`、`_combine_pitch_plinko()`、`_combine_statcast_dicts()` 都是數據合併，應移至 `statcast.py` 或 `statcast_aggregation.py`。

- [ ] **`site_builder/statcast.py:1199-1217` — `summarize_pitch_for_display()` 是展示 projection，放在計算模組職責不符**
  - 只被 `builder.py` 使用，應移至 `builder.py` 或 `display.py`。

- [ ] **`site_builder/builder.py:40-47` vs `site_builder/statcast.py:104-135` — `_COUNT_USAGE_BUCKETS` 定義不同步**
  - builder 有 `"all"` bucket（6 個），statcast 只有 5 個；`_combine_pitch_usage_by_count()` 的 `"all"` bucket 永遠是 0 pitches（因 statcast 輸出沒有 `"all"` key），屬於 dead code。兩者應共用同一個定義來源。

- [ ] **`site_builder/helpers.py:284-296` — `_compute_advanced_stats()` 型別不一致（float vs 字串）**
  - `_fmt_avg()` 回傳字串（`".333"`），其他欄位回傳 float；排序、加權平均、測試時會型別不一致。建議計算層統一保留 float，模板用 filter 格式化。

- [ ] **`site_builder/builder.py:587` 與 `site_builder/helpers.py:332-336` — ISO 計算重複**
  - builder 在 `_load_player_bundle()` 手動算 `data.iso`，`_compute_advanced_stats()` 之後也會補算。刪除 builder 中的冗餘計算。

- [ ] **`site_builder/statcast.py:835-840, 905-909, 1121-1126` — Put Away% 邏輯三重重複**
  - 投手 arsenal、投手 outcomes、打者 vs pitch types 各自有相同的兩好球三振計算邏輯，應抽出共用 helper `_compute_put_away_pct(pitches)`。

- [ ] **`site_builder/jinja_env.py:32-41` — `default_if_none` 與 `num_dash` 功能重疊**
  - 兩者都處理空值 fallback，只差空字串行為略不同。考慮合併為 `num_dash(value, fallback="-")`。

- [ ] **`site_builder/api.py:17-26` / `site_builder/helpers.py:11-20` — sport level 對照表分散**
  - ID、名稱、排序分散在兩個模組，新增層級時容易漏改。集中到 `helpers.py` 或 `levels.py`。

- [ ] **`site_builder/sync.py`（1238 行）職責過多，建議拆分**
  - 同一檔案同時負責 schema/migration、API orchestration、DB write、Statcast fetch、aggregation merge。
  - 建議拆成：`db.py`（schema + CRUD）、`sync.py`（一般資料同步）、`statcast_sync.py`（play-by-play + Statcast pipeline）。

- [ ] **`site_builder/builder.py:633-878` — `build_static_site()` 245 行，建議拆出 player context builder**
  - 建議抽出 `_build_player_context(player, all_stats, all_logs, year, out_dir, base_url) -> dict`。

- [ ] **`site_builder/helpers.py:25-32` — `Obj.__getattr__` 靜默吞掉 typo**
  - 任何拼錯欄位回傳 `None`，模板只顯示空白，debug 困難。至少在 debug 模式 log warning。

- [ ] **`site_builder/api.py:242` / `site_builder/builder.py:649` — UTC+8 timezone 重複硬編碼**
  - `datetime.timezone(datetime.timedelta(hours=8))` 兩處重複，應定義共用常數 `TW_TZ`。

- [ ] **`site_builder/helpers.py:135-148` / `site_builder/builder.py:856-857` — `height_to_cm` / `lbs_to_kg` 更適合作為 Jinja filter**
  - 單位換算是展示層格式化，可移至 `jinja_env.py` 並減少 context 欄位。

- [ ] **`site_builder/sync.py:727-729` — `_build_roster_map()` 單行 function 無意義抽象**
  - 只呼叫一次，inline 或擴充成真正的 roster validation。

---

## 🟡 前端效能 / 可快取性

- [ ] **`src/templates/player_detail.j2:1205-2051` — ~800 行 inline JS 無法跨頁快取**
  - 建議拆成 `src/static/js/player_detail.js`，用 `data-*` 或 `<script type="application/json">` 傳入頁面資料。

- [ ] **`src/templates/index.j2:93-118` — `sortCards()` 應抽出為靜態 JS**
  - 移至 `src/static/js/index.js`，button 改用 `data-sort` + event listener，配合 CSP 禁用 inline script。

- [ ] **`src/templates/player_detail.j2:79-1203` — 所有 tab panels 一次全部 render，hidden panels 也佔 parse/memory**
  - 首次只 render active tab，其他 tab 切換時 lazy render（或至少 lazy init Chart.js / Plinko）。

- [ ] **`src/templates/player_detail.j2:1966` — Chart.js 未 pin 版本且無 SRI**
  - `https://cdn.jsdelivr.net/npm/chart.js` 無 `@version`、無 `integrity`，部署不可重現且有供應鏈風險。

```html
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.9/dist/chart.umd.min.js"
        integrity="sha384-..." crossorigin="anonymous"></script>
```

- [ ] **`src/templates/base.j2:89` — Cloudflare Insights beacon 每頁載入，有第三方 JS/privacy overhead**
  - 考慮只在 production build 時注入，或移至 CSP report-only。

- [ ] **`src/static/css/style.css:1-1911` — 單一 global CSS 包含 index/detail/chart/pitch-log/404 全部樣式**
  - 所有頁面都下載並解析全部 1911 行 CSS。考慮拆分 per-page CSS 或移除 dead selectors。

---

## 🟡 CI / 安全性 / 基礎設施

- [ ] **`.github/workflows/pages.yml:67, 92` — OAuth token 失敗時印出完整 `TOKEN_JSON`**
  - `echo "$TOKEN_JSON"` 會把完整 OAuth error response 寫入 CI log。改為只印 error code。

```bash
echo "Failed to get access token; HTTP error in token exchange"
```

- [ ] **`.github/workflows/pages.yml:21-26` — Google Drive secrets 放 job-level env，所有 steps 都能讀取**
  - 應移到需要的 step 的 `env:` 區塊，最小化 secret 可見範圍。

- [ ] **`.github/workflows/pages.yml:56-101` — `curl` 無 `--max-time`、無 `--retry`，job 無 `timeout-minutes`**
  - 網路故障時 CI 可能永久 hang，加入 `--max-time 60 --retry 3 --retry-delay 5`。

- [ ] **`.github/workflows/pages.yml:40` — `python-version: "3.13.12"` exact patch pin 容易 break**
  - minor version 更新後 setup-python 找不到會直接失敗，改為 `"3.13"`。

- [ ] **`requirements.txt:1-7` — pinned 版本但無 hash lock**
  - 有 pin 但無 `--require-hashes`，transitive dependency 升級時 CI 行為可能不可重現。
  - 考慮改用 `pip-compile --generate-hashes` 產生 lock file。

- [ ] **`.gitignore:1-11` — 缺少 `.env`、`.venv/` 等常見 ignore pattern**

```gitignore
.env
.env.*
.venv/
*.sqlite3
```

---

## 🟡 測試缺口

- [ ] **整個 repo 無自動化測試（無 `tests/` 目錄）**
  - 核心統計邏輯（FIP、IP 轉換、EV90、spray direction、wOBA、MiLB fallback）都是高價值 regression target，目前完全沒有 regression guard。
  - 建議最低覆蓋：

```python
def test_compute_fip_converts_baseball_ip(): ...        # 7.2 IP → 7.667 真實局數
def test_get_player_stats_keeps_mlb_when_milb_fails(): ...
def test_ev90_nearest_rank_n10(): ...                  # n=10 → index 8, not 9
def test_switch_hitter_spray_skipped(): ...            # bat="S" → None
def test_season_stats_unique_includes_sport_level(): ...
def test_tojson_safe_escapes_script_tag(): ...         # "</script>" → safe
```

---

## 📌 保留參考：TJStats / Park Factor 筆記

以下是先前整理的資料來源與公式，保留作為未來實作 wOBA+ / TJBat+ 的背景。

### Park Factors 表（每支球隊，每年）

| 欄位 | 說明 |
|------|------|
| Team | 球隊名 |
| League | 所屬聯盟 |
| Home G | 主場場次 |
| Road G | 客場場次 |
| `pf_raw_1y` | 今年原始 Park Factor |
| `pf_raw_3y` | 3 年原始均值 |
| `pf_wgt_3y` | 3 年加權（近年 3:2:1 權重） |
| `pf_reg_3y` | 3 年加權後往 1.00 回歸 50% |
| `pf_reg_wgt_3y` | 最終使用值，用於 wOBA+ 和 TJBat+ |

### League Constants 表（每個聯盟，每年）

| 欄位 | 說明 |
|------|------|
| PA | 樣本打席數 |
| `lg_wOBA` | 聯盟平均 wOBA |
| `lg_OBP` | 聯盟平均 OBP |
| `lg_R/PA` | 每打席得分率 |
| `woba_scale` | wOBA → 得分的換算係數，TJStats 固定 1.240 |

### TJStats 固定 wOBA 線性權重

| 事件 | 權重 |
|------|------|
| BB | 0.689 |
| HBP | 0.720 |
| 1B | 0.881 |
| 2B | 1.254 |
| 3B | 1.589 |
| HR | 2.048 |
| IBB / 犧牲觸擊 / Out | 0 |

### 可計算數據

`wOBA+ = 100 * (wOBA / PF) / lg_wOBA`

`PF_m = 1 + (PF - 1) * 0.5`

`wRC/PA = ((wOBA - lg_wOBA) / woba_scale) + lg_R/PA`

`TJBat+ = 100 * ((wRC/PA / PF_m) / lg_R/PA)`

### 對現有代碼的影響

| 現有代碼 | 需要補充的資料 |
|---------|-------------|
| `statcast.py` 計算 wOBA，但用 FanGraphs 年份權重 | 若要與 TJStats 對齊，需改為固定權重 |
| `FIP_CONSTANTS` 只有 level，無 park factor | Park Factor 需加入 `(team, year)` 對應表 |
| `LEAGUE_RA9` 用 level 分 | TJStats 更細：同 level 不同聯盟值不同 |
| `statcast.py` 無 wOBA+ / TJBat+ | 需引入 park factors + league constants |



現在我有完整的資料了，讓我整理結果：

---

## 調查結果

---

### 一、哪些層級有每球被擊出的落點資料

**所有層級都有 `hit_coord_x` / `hit_coord_y`（Gameday 落點座標）**，包含 MLB、AAA、AA、A+、A、ROK。

這些座標由 MLB Gameday 人工記錄員輸入，只針對擊出球（in-play），約佔全部投球的 15–20%。

| 層級 | 落點座標 | 球種分類 GB/LD/FB/PU | 接觸強度 soft/med/hard |
|------|----------|---------------------|----------------------|
| MLB  | ✅ | ✅ | ✅ |
| AAA  | ✅ | ✅ | ✅ |
| AA   | ✅ | ✅ | ✅ |
| A+   | ✅ | ✅ | ✅ |
| A    | ✅ | ✅ | ✅ |
| ROK  | ✅ | ✅ | ✅ |

**重要備注**：落點座標是 Gameday 座標系（原點在本壘板附近），不是真實球場距離。`exit velocity` 和 `launch angle` 則不同，屬於 Hawk-Eye/Statcast 量測資料。

---

### 二、各層級可爬到的所有資料及 API 端點

#### 端點總覽

| 端點 | 可用層級 | 說明 |
|------|----------|------|
| `GET /api/v1/people/{id}?hydrate=transactions,rosterEntries,currentTeam` | 全部 | 球員基本資料 |
| `GET /api/v1/people/{id}/stats?stats=yearByYear&group=hitting,pitching,fielding` | MLB | 逐年賽季統計（MLB） |
| `GET /api/v1/people/{id}/stats?stats=yearByYear&leagueListId=milb_all&group=hitting,pitching,fielding` | 全部小聯盟 | 逐年賽季統計（MiLB） |
| `GET /api/v1/people/{id}/stats?stats=seasonAdvanced&group=hitting,pitching&season={year}` | MLB | 進階賽季統計（MLB） |
| `GET /api/v1/people/{id}/stats?stats=seasonAdvanced&leagueListId=milb_all&group=hitting,pitching&season={year}` | 全部小聯盟 | 進階賽季統計（MiLB） |
| `GET /api/v1/people/{id}/stats?stats=gameLog&season={year}&group=hitting,pitching` | MLB | 逐場比賽統計（MLB） |
| `GET /api/v1/people/{id}/stats?stats=gameLog&season={year}&leagueListId=milb_all&group=hitting,pitching` | 全部小聯盟 | 逐場比賽統計（MiLB） |
| `GET /api/v1.1/game/{pk}/feed/live` | **全部層級** | **逐球資料（最詳細）** |
| `GET /api/v1/people/{id}/stats?stats=sabermetrics&group=pitching,hitting&season={year}` | **MLB 限定** | WAR / wRC+ / wOBA |
| `GET /api/v1/people/{id}/stats?stats=expectedStatistics&group=pitching&season={year}` | **MLB 限定** | xBA / xSLG / xwOBA |
| `GET /api/v1/schedule?teamId={id}&startDate=…&endDate=…&sportId=1,11,12,13,14,15,16` | 全部 | 賽程 |

---

#### 各層級資料詳細說明

##### **逐賽季統計**（`yearByYear` + `seasonAdvanced`）— 全層級相同

打者：`gp, pa, ab, runs, hits, doubles, triples, hr, rbi, tb, bb, so, hbp, ibb, sb, cs, gdp, sac_bunts, sac_flies, avg, obp, slg, ops, iso, babip, k_pct, bb_pct, go_ao, p_per_pa`

投手：`era, whip, ip, so, bb, wins, losses, sv, hld, gs, gp, bf, hr, hbp, wp, balks, cg, sho, k_per_9, bb_per_9, h_per_9, hr_per_9, k_bb_ratio, babip, p_per_ip, avg, obp, slg, ops`

守備：`gp, gs, innings, putouts, assists, errors, dp, fielding_pct, range_factor_9, range_factor_game`

##### **逐賽場統計**（`gameLog`）— 全層級，打者/投手分開

`atBats, plateAppearances, hits, doubles, triples, homeRuns, rbi, baseOnBalls, intentionalWalks, strikeOuts, hitByPitch, stolenBases, caughtStealing, groundOuts, airOuts, groundIntoDoublePlay, numberOfPitches, avg, obp, slg, ops, leftOnBase, babip, sacBunts, sacFlies`

投手另有：`inningsPitched, earnedRuns, era, whip, battersFaced, wins, losses, saves, holds, gamesStarted, blownSaves, strikesPer9, walksPer9, strikePercentage`

##### **逐球資料**（`/api/v1.1/game/{pk}/feed/live`）— 依層級有差異

| 欄位 | MLB | AAA | AA | A+ | A | ROK |
|------|-----|-----|----|----|---|-----|
| `result_code` 球結果代碼 | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| `is_strike / is_ball / is_in_play` | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| `hit_coord_x / hit_coord_y` 落點座標 | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| `trajectory` 球種 (GB/LD/FB/PU) | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| `hardness` 接觸強度 | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| `hit_location` 守備區位號碼 | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| `inning` 局數 | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| `count` 球數好球數 | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| `pitch_type / pitch_name` 球種代碼 | ✅ | ✅ | ❌ | ❌ | △ 部分 | △ 極少 |
| `start_speed` 球速 | ✅ | ✅ | ❌ | ❌ | △ 部分 | △ 極少 |
| `zone` 好球帶區域 | ✅ | ✅ | ❌ | ❌ | △ 部分 | △ 極少 |
| `pfx_x / pfx_z` 投球位移 | ✅ | ✅ | ❌ | ❌ | △ 部分 | △ 極少 |
| `px / pz` 過本壘板座標 | ✅ | ✅ | ❌ | ❌ | △ 部分 | △ 極少 |
| `spin_rate` 轉速 | ✅ | ✅ | ❌ | ❌ | △ 部分 | △ 極少 |
| `ivb / hb` 垂直/水平移動量 | ✅ | ✅ | ❌ | ❌ | △ 部分 | △ 極少 |
| `extension` 出手延伸距離 | ✅ | ✅ | ❌ | ❌ | △ 部分 | △ 極少 |
| `ev` 出棒速度 (exit velocity) | ✅ | ✅ | ❌ | ❌ | △ 部分 | △ 極少 |
| `la` 擊球仰角 (launch angle) | ✅ | ✅ | ❌ | ❌ | △ 部分 | △ 極少 |
| `hit_distance` 擊球距離 | ✅ | ✅ | ❌ | ❌ | △ 部分 | △ 極少 |

**△ 部分** = 取決於球場是否有 Hawk-Eye 裝置。A 聯盟約 2021–2022 年起部分球場有安裝，但覆蓋率不穩定。

##### **Statcast 進階（MLB 限定）**

| 端點 | 資料 |
|------|------|
| `sabermetrics` | WAR, wRC+, wOBA, wRAA, spd, ubr, wGDP, wSB, batting/fielding/baserunning 分解 |
| `expectedStatistics` | xBA, xSLG, xwOBA, xwOBACon |

這兩個端點在 MiLB 使用 `leagueListId=milb_all` 時回傳全 0 或空值，**MiLB 無官方 Statcast 期望值**。
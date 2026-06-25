# Taiwan MLB Tracker — site_builder 程式碼審查報告

> 產出日期：2026-06-25
> 審查範圍：`site_builder/` 下 6 個核心 Python 檔案
> 審查方式：每個檔案由獨立 reviewer 進行最詳細的 code review，檢查 **Deadcode**、**程式碼邏輯錯誤**、**數據計算正確性**、**常數管理** 四大面向。

---

## 目錄

1. [整體摘要](#整體摘要)
2. [跨檔案優先處理清單](#跨檔案優先處理清單)
3. [api.py](#apipy)
4. [builder.py](#builderpy)
5. [helpers.py](#helperspy)
6. [jinja_env.py](#jinja_envpy)
7. [statcast.py](#statcastpy)
8. [sync.py](#syncpy)

---

## 整體摘要

整體程式碼品質良好：命名清楚、docstring 詳盡、錯誤處理普遍到位（try/except + logging、`_ratio` 安全除法、None 防護）。**沒有發現會立即導致程式崩潰或資料損毀的高嚴重度錯誤**。

主要改善空間集中在三類：

- **數據計算的「定義一致性」**：部分棒球進階統計的分子/分母母體不一致，或與業界（Baseball Savant / FanGraphs）慣例有偏差（集中於 `statcast.py` 與 `helpers.py`）。
- **常數管理**：大量 magic number / magic string 散落各處（FIP 係數、wOBA 權重門檻、單位換算係數、SQL 表名、timeout、URL、`"_combined"` 等），應抽成具名模組常數。
- **少量 Deadcode 與 docstring / 實作落差**：`helpers.highest_level()`、`jinja_env.slice_prefix`、`sync.playbyplay_processed`（只寫不讀）等。

各檔案嚴重度分布概覽：

| 檔案 | 高 | 中 | 低 | 備註 |
|------|----|----|----|------|
| api.py | 0 | 5 | 7 | 無 deadcode；以常數管理與時區正確性為主 |
| builder.py | 0 | 4 | 7 | 聚合計數膨脹 bug 為最需注意項 |
| helpers.py | 1 | 4 | 6 | WHIP 守護條件、投手 BABIP 公式 |
| jinja_env.py | 0 | 2 | 8 | NaN 未當缺值處理 |
| statcast.py | 1 | 8 | 9 | 統計定義一致性與業界對齊 |
| sync.py | 0 | 7 | 7 | playbyplay_processed 只寫不讀 |

---

## 跨檔案優先處理清單

依嚴重度與影響面排序，建議優先處理：

### 高 / 數據正確性
1. **helpers.py WHIP 守護條件不對稱**（helpers.py:340-344）— 當 `bb` 為 None 而 `p_hits` 有值時靜默低估 WHIP。
2. **statcast.py ev90 百分位用 nearest-rank 近似**（statcast.py:1234）— 小樣本把 max 當 ev90，與 Savant/TJStats 不符（程式碼註解亦自承）。
3. **helpers.py 投手 BABIP 分母公式**（helpers.py:573-583）— 未扣除 HBP/SF，與打者版不對稱，造成數值偏差。

### 中 / 數據正確性與一致性
4. **statcast.py sweet-spot% 分子母體不一致**（statcast.py:1238/1250）— 分子用全 in-play、分母用有 LA 的 BBE，系統性高估。
5. **statcast.py barrel% / hard-hit% 分母定義不一致**（barrel 用 `n_ip`、hard-hit 用 `bbe_ev`）— 建議統一以 BBE 為分母對齊業界。
6. **builder.py `_combine_pitch_usage_by_count` 計數膨脹**（builder.py:242-243）— `totals_by_type` 雙重來源累加，可能造成計數膨脹、`pct` 偏低。
7. **sync.py sabermetrics 寫入條件冗餘矛盾**（sync.py:1061-1063）— 特定 merge 順序下 MLB 列可能遺漏 sabermetrics。
8. **sync.py `any([xba, xslg, xwoba, xwobacon])` 把合法 0.0 當無資料**（sync.py:1167）— 應改用 `is None` 判定。

### 中 / 邏輯與 docstring 落差
9. **sync.py `playbyplay_processed` 表只寫不讀**（sync.py:1379-1384 vs docstring 1206-1209）— 去重機制實作未啟用。
10. **jinja_env.py NaN 未當缺值處理**（jinja_env.py:25-32, 69-84）— `nan` 會印成 `"nan"` / `"NaN%"`。
11. **builder.py `snapshot_valid` 用 `today().year` 而非傳入 `year`**（builder.py:1068-1075）— 舊年份重建時可能顯示不符年度的下一場。

### 中 / 常數管理（共通主題）
12. 統一抽出散落的 magic number / string：
    - statcast.py：hard-hit 95、barrel 門檻、FIP 係數、wOBA 權重、`{"EP","FA"}` 重複。
    - helpers.py：單位換算 `2.54` / `0.453592`、棒球規則 `9` / `3`。
    - sync.py：DB timeout、schema 表名、`EMPTY_PITCHES`（`'[]'`/`'null'` 判定三處不一致）、`ELSE 50` 應引用 `_UNKNOWN_RANK`。
    - api.py：v1.1 base URL、timeout=30、sportId 清單、UTC+8。
    - builder.py：`"_combined"`、`max_points=900`、headshot URL/timeout。
    - jinja_env.py：缺值佔位字串 `"-"`。

### 低 / Deadcode 清理
13. `helpers.highest_level()`（helpers.py:236-247）未被呼叫；`.levels` re-export 除 `level_rank` 外多為冗餘。
14. `jinja_env.slice_prefix`（jinja_env.py:47-51）模板 0 次使用。
15. `statcast.py:1157` `if count_set is None` 為永不成立的死分支。

---

## api.py

### 檔案概述
`site_builder/api.py` 是 Taiwan MLB Tracker 專案的 MLB Stats API client，封裝對 `statsapi.mlb.com` 各個 endpoint 的 HTTP 呼叫。負責抓取球員 profile、年度基礎/進階數據、賽程、game logs、play-by-play live feed、sabermetrics、expected stats、以及解析 roster JSON 檔。所有 function 皆回傳結構化的 dict / list，由上層 `sync.py` 消費。檔案使用 `requests` 同步呼叫，錯誤多以 try/except + logging 處理。

### Function 與常數清單

| 名稱 | 類型 | 分類 | 功用說明 |
|------|------|------|----------|
| `BASE_URL` | 常數 | URL | API v1 base URL `https://statsapi.mlb.com/api/v1` |
| `TIMEOUT` | 常數 | 設定 | requests timeout 秒數 (15) |
| `logger` | 模組層級變數 | logging | 模組 logger |
| `get_player_profile(mlb_id)` | function | 球員資料 | 抓 profile + transactions + rosterEntries + currentTeam，並額外查 team 取得 level |
| `get_player_stats(mlb_id)` | function | 數據 | yearByYear 基礎數據 (MLB + MiLB) |
| `get_player_advanced_stats(mlb_id, years)` | function | 數據 | seasonAdvanced 進階數據 (MLB + MiLB)，可按年份 |
| `get_game_logs(mlb_id, season)` | function | 數據 | 單季 gameLog (MLB + MiLB) |
| `get_next_game(team_id)` | function | 賽程 | 未來 7 天內下一場 Preview 狀態比賽 |
| `get_game_play_by_play(game_pk)` | function | 數據 | 單場 live feed 完整 JSON (v1.1) |
| `sport_obj_to_abbr(sport)` | function | 轉換 | sport object → level 縮寫 (走 levels registry) |
| `get_game_sport_level(game_pk)` | function | 數據 | 用 fields-filter 取單場 sport 縮寫 |
| `get_player_sabermetrics(mlb_id, years)` | function | 數據 | sabermetrics (FIP/xFIP/WAR)，MLB only |
| `get_player_expected_stats(mlb_id, years, group)` | function | 數據 | expectedStatistics (xwOBA/xBA/xSLG)，MLB only |
| `parse_roster_from_file(filepath)` | function | I/O | 讀取 roster JSON 回傳 players list |

### 發現的問題

#### 1. Deadcode
此檔 deadcode 很少。所有 function 都被 `sync.py` / `builder.py` 實際引用，無未使用的 import。**未發現真正不可達或未使用的程式碼。** 唯 `groups` 同名區域變數在不同 function 內值不同（api.py:132 為 `"hitting,pitching,fielding"`、api.py:165 為 `"hitting,pitching"`），容易誤讀，建議抽成模組常數（見常數管理）。

#### 2. 邏輯錯誤 / 潛在 bug
- **api.py:286-290（低-中）** `get_next_game` 的 `except` 內 `return None`（288）與函式結尾 `return None`（290）其一冗餘，可移除 288 讓 except 自然 fall through。
- **api.py:110（中）** `"is_active": p.get("active", True)` 缺失時預設 `True`，與 `roster_is_active`（行 75/82）缺失預設 `False` 不一致，可能讓已離隊球員被誤判為現役。建議統一預設或加註解。
- **api.py:90-99（中）** `get_player_profile` 內查 `/teams/{team_id}` 取 level 時用 `status_code == 200` 判斷，非 200 時 `current_team_level` 靜默留空字串且不 log，與其他地方 `raise_for_status()` 風格不一致。
- **api.py:59 / 64（低）** transactions 排序用 `t.get("date","")`，但輸出 `date` 用 `effectiveDate or date`，排序鍵與顯示日期欄位不一致。
- **api.py:317（低）** `sport.get("id", 0)` 的 fallback `0` 仰賴下游容錯（`levels.py` 對 0 回 None），可移除不必要的 magic number。

#### 3. 數據計算正確性
- **api.py:332-335（已驗證正確）** `?fields` filter 採扁平逗號分隔白名單，實測回傳結構正確；唯會連帶帶出 `away.sport`（同名 key），payload 略大，影響極小。
- **api.py:237-244（中）** `today = datetime.date.today()` 使用本機時區，但比賽時間後續用 UTC+8 轉換。在 UTC 的 CI 環境（GitHub Actions）「未來 7 天」窗口起點可能與台灣/美東日期錯開一天，極端情況漏算邊界日比賽。建議明確指定時區。
- **api.py:264-272（低）** `gameDate` 解析失敗時 `game_time = game_date_str[:16]` 的 fallback 格式（UTC、帶 `T`）與正常路徑 `"%m/%d %H:%M (UTC+8)"` 完全不同，可能誤導。
- 其餘 URL 參數組裝（`group`、`season`、`leagueListId=milb_all`、`sportId=1,11,12,13,14,15,16`）皆正確。

#### 4. 常數管理
- **api.py:299, 333（中）** v1.1 base URL 硬編碼且重複兩次，建議新增 `BASE_URL_V11`。
- **api.py:301（中）** `timeout=30`（live feed）為散落 magic number，建議抽 `LIVE_FEED_TIMEOUT`；`get_game_sport_level`（337）的 15 也應統一引用 `TIMEOUT`。
- **api.py:244（低）** `sportId=1,11,12,13,14,15,16` 與 `levels.py` 的 sport_ids 重複，建議從 `levels.py` 衍生。
- **api.py:132/165/209/220/363（低）** `groups` 字串多處硬編碼且順序不一（sabermetrics 為 `"pitching,hitting"`），建議抽 `GROUPS_ALL`、`GROUPS_HIT_PITCH`。
- **api.py:238（低）** `days=7` 賽程窗口、**api.py:267（低）** `timedelta(hours=8)` UTC+8 建議抽具名常數。

### 總結
此檔整體品質良好，**無真正 deadcode**。優先：(1) 常數抽取（v1.1 URL、timeout=30、sportId、UTC+8）；(2) `get_next_game` 時區正確性；(3) `is_active` 預設值一致性；(4) team level 巢狀請求錯誤處理風格統一。無發現會導致錯誤計算結果的嚴重 bug。

---

## builder.py

### 檔案概述
`builder.py` 是 Taiwan MLB Tracker 的靜態網站渲染器，負責：從 SQLite 讀取 `players` / `season_stats` / `game_logs` 三張表組裝 player bundle（`_load_player_bundle`）；將同一年度跨 level 的 Statcast 資料以 count-weighted average 合併（一系列 `_combine_*`）；區分 active / retired 球員並渲染 index、retired、player detail、404 頁面；產生 SEO 結構化資料（JSON-LD）、sitemap.xml、robots.txt、headshot 快取。

### Function 與常數清單

| 名稱 | 類型 | 分類 | 功用說明 |
|------|------|------|----------|
| `_PROJECT_ROOT` | 常數 | 路徑 | 專案根目錄 |
| `_SITE_TITLE` / `_SITE_DESCRIPTION` / `_SITE_SAME_AS` | 常數 | SEO | 站台標題、描述、社群連結 |
| `_BAT_SIDE_SPLITS` | 常數 | 分組 | 打者左右打 split 定義 |
| `_COUNT_USAGE_BUCKETS` | 常數 | 分組 | 球數情境 bucket 定義 |
| `_PLINKO_COUNTS` / `_PLINKO_EDGES` | 常數 | 分組 | Pitch Plinko 節點/邊定義 |
| `_ratio` | function | 計算 | 安全除法回傳 round 4 位比率 |
| `_is_unknown_pitch_type` | function | 工具 | 判斷球種是否未知 |
| `_combine_pitch_type_data` | function | 聚合 | 通用 count-weighted 球種合併核心 |
| `_combine_vs_pitch_types` | function | 聚合 | 打者 vs 球種合併 |
| `_combine_pitch_outcomes` | function | 聚合 | 投手 pitch_outcomes 合併 |
| `_combine_pitch_arsenal` | function | 聚合 | 投手球種武器庫合併 |
| `_combine_pitch_usage_by_count` | function | 聚合 | 依球數情境合併球種使用 |
| `_combine_pitcher_bat_side_splits` | function | 聚合 | 跨 level 合併左右打 split |
| `_combine_pitch_plinko` | function | 聚合 | 合併 Plinko 節點/邊 |
| `_combine_pitch_movement` | function | 聚合 | 合併投球軌跡散點圖 |
| `_combine_statcast_dicts` | function | 聚合 | 跨 level 加權合併整份 statcast |
| `_prefetch_headshots` | function | IO | 下載/快取/複製球員頭像 |
| `_pick_display_stat` | function | 邏輯 | 挑選卡片顯示用 stat row |
| `_player_display_name` | function | 工具 | 組合中英文名 |
| `_player_canonical_path` | function | 路由 | 球員頁 canonical 路徑 |
| `_player_description` | function | SEO | 球員頁 meta description |
| `_index_structured_data` | function | SEO | 首頁 JSON-LD |
| `_player_structured_data` | function | SEO | 球員頁 JSON-LD |
| `_write_robots` | function | IO | 寫 robots.txt |
| `_write_sitemap` | function | IO | 寫 sitemap.xml |
| `_load_player_bundle` | function | DB | 載入單一球員完整資料 |
| `build_static_site` | function | 主流程 | 整站建置主入口 |

### 發現的問題

#### 1. Deadcode
整體未發現明確的未使用 import / function / 變數。所有 `_combine_*` 都透過 `_combine_statcast_dicts` 串接使用。`statcast_available`（builder.py:1184）、`movement_pitches_by_year_level`（1131-1147）均屬正常使用。**此類大致無問題。**

#### 2. 程式碼邏輯錯誤
- **builder.py:242-243（中）** `_combine_pitch_usage_by_count` 的補洞邏輯：`totals_by_type` 跨所有 entries 累加，當第一個 entry 的 `pitch_types` 為空但有 rows 時以 all-row 回填，若後續 entry 的 top-level `pitch_types` 才有該 type，會造成同一 type 被**重複累加**，總數膨脹、`pct` 偏低。建議改為「僅當所有 entry 都沒有 top-level pitch_types 時才以 all-row 回填」。
- **builder.py:451（中）** `_combine_pitch_movement` 當各 level 都沒有 `total_pitches` 時，用抽樣前 `len(points)` 當分母；後續 900 點抽樣會改變 `len(points)`。內部分子分母一致（皆抽樣前），但 `shown_pitches` 與 `total_pitches` 語意在無 total 時混淆，建議釐清或加註解。
- **builder.py:401（低）** Plinko 節點 `pct` 分母用 `node_bucket["pitches"]`，若某 level node 有 `type_counts` 卻 `pitches=0`，`_ratio` 回 None 而非 0，分子分母不一致。
- **builder.py:1068-1075（中）** `snapshot_valid` 用 `datetime.date.today().year`（2026）而非傳入 `year` 參數。以舊年份重建站台時，`next_game_for_season=2026` 的快照仍會被判為有效並顯示在舊年份頁面。建議改用 `year`。
- **builder.py:608-622 / 794 / 941 / 1088（低，需核對）** 排序鍵使用 `level_order`，但 `_pick_display_stat` 的 fallback `stats_current[0]` 是否真為「最高 level」取決於 `helpers.level_rank` 的排序方向，需交叉核對與 docstring 一致。
- **builder.py:960（低）** index 排序用 `player.level`（字串 badge），需確認 `level_rank(None)` / `"N/A"` 行為不致例外。

#### 3. 數據計算正確性
- **builder.py:144-146（低，正確）** `put_away_pct` 以 two_strike_count 加權，正確。
- **builder.py:510-514 vs 161/163/86（低）** rate 精度不一致：`_combine_statcast_dicts` round 3 位、`_combine_pitch_type_data` 與 `_ratio` round 4 位，summary row 與細項 row 尾數可能對不上，建議統一精度常數。
- **builder.py:548-549（正確）** `max_ev` 取各 level 最大值，語意正確。
- **builder.py:791（正確）** `iso = slg - avg`，僅在兩者非 None 時計算，正確。

#### 4. 常數管理
- **builder.py:458（中）** `max_points = 900` 抽樣上限應抽成 `_MOVEMENT_MAX_POINTS`。
- **builder.py:577-579（中）** headshot URL `img.mlbstatic.com` 與 `w_180,q_auto:best` 參數硬編碼，建議抽常數。
- **builder.py:581（低）** `timeout=10` 與專案慣用 15s 不一致且為 magic number。
- **builder.py:多處（中）** magic string `"_combined"`（119/218/283/328/1178…）、`"合計"`（1179）重複出現，建議抽 `_COMBINED_LEVEL_KEY`。
- **builder.py:710/917/1108-1109/1250（低）** `img/players`、`data/pitchlogs` 等輸出路徑片段散落多處，須一致（否則 SEO 圖片 404），建議集中管理。
- **builder.py:1082（低）** `"%Y-%m-%d %H:%M UTC"` 與 build_time（875）用 UTC+8 不一致，需確認 `next_game_updated_at` 實際時區。
- **builder.py:1006-1011（低）** retired 頁 SEO 標題/描述 inline 定義，與 index 的模組常數風格不一致。

### 總結
結構清晰、聚合邏輯經深思（加權平均、period-accurate badge、demotion 處理皆有註解），**無 deadcode**。優先：(1) builder.py:242-243 計數膨脹 bug（唯一明確影響顯示數據正確性）；(2) snapshot_valid 年份判斷；(3) 核對 `level_rank` 排序方向；(4) 常數抽取與 rate 精度統一。需交叉核對 `helpers.py` 的 `level_rank` / `compute_career` / `compute_season_combined` / `highest_level_row`。

---

## helpers.py

### 檔案概述
`site_builder/helpers.py` 是共用工具模組：(1) 將 league/level 邏輯從 `site_builder.levels` re-export 維持向後相容；(2) 安全型別轉換（`safe_float`/`safe_int`）；(3) JSON 序列化/反序列化；(4) 日期與單位換算（英呎吋→公分、磅→公斤、IP↔outs）；(5) 棒球進階統計計算（AVG/OBP/SLG/OPS/ERA/WHIP/ISO/BABIP/K%/BB% 等）與球季/生涯聚合；(6) roster 狀態分類與現役判定。

### Function 與常數清單

| 名稱 | 類型 | 分類 | 功用說明 |
|------|------|------|---------|
| `Obj` | class | 容器 | 屬性存取式 dict，供 Jinja 模板使用 |
| `DEFAULT_SEASON_YEAR` | 常數 | 設定 | 預設球季年份（可由環境變數覆寫，預設 2026） |
| `ROSTER_INJURED_CODES` | 常數 | roster | 傷兵名單狀態碼集合 |
| `ROSTER_RESTRICTED_CODES` | 常數 | roster | 受限/休假名單狀態碼集合 |
| `ROSTER_OTHER_CODES` | 常數 | roster | 過渡性名單異動狀態碼（DES） |
| `ROSTER_INACTIVE_CODES` | 常數 | roster | 已離隊狀態碼集合 |
| `_COUNTING_FIELDS` | 常數 | 聚合 | 生涯/球季聚合時需加總的計數型欄位清單 |
| `_NATIONAL_TEAM_KEYWORD` | 常數 | 現役判定 | 國家隊召集關鍵字（"chinese taipei"） |
| `_HEIGHT_RE` | 常數 | 單位換算 | 解析英呎吋身高字串的 regex |
| `categorize_roster_status` | function | roster | 將最近 roster entry 映射為狀態 pill 分類 |
| `safe_float` / `safe_int` | function | 型別轉換 | 安全轉 float / int |
| `loads_json` / `loads_json_dict` / `loads_json_list` | function | JSON | 字串→物件 / dict / list |
| `dumps_json` | function | JSON | 物件→緊湊 UTF-8 JSON 字串 |
| `parse_date` | function | 日期 | ISO 字串→`date` |
| `ip_to_outs` / `outs_to_ip` | function | 單位換算 | 棒球小數 IP ↔ 出局數 |
| `height_to_cm` / `lbs_to_kg` | function | 單位換算 | 英呎吋→公分 / 磅→公斤 |
| `calc_obp` | function | 統計 | 計算上壘率 OBP |
| `highest_level_row` / `highest_level` | function | level | 最高 level 的 stat row / tier key |
| `_is_national_team_tx` | function | 現役判定 | 判斷交易是否為國家隊召集 |
| `is_active_player` | function | 現役判定 | 判斷球員在指定年是否現役 |
| `has_appearance` | function | 統計 | 判斷 stat row 是否有實際出賽 |
| `_sum_counting` | function | 聚合 | 加總 `_COUNTING_FIELDS` |
| `_compute_rate_stats` / `_aggregate_stats` | function | 統計/聚合 | 計算率統計 / 加總+衍生 |
| `compute_career` / `compute_season_combined` | function | 聚合 | 生涯聚合 / 單一年跨隊聚合 |
| `_fmt_avg` | function | 格式化 | float→無前導 0 的棒球小數字串 |
| `_compute_advanced_stats` / `annotate_computed_stats` | function | 統計 | 填衍生進階統計 / 為每筆 row 加衍生欄位 |
| `compute_year_groups` | function | 聚合 | 依年分組產生 summary + 每隊明細列 |
| re-export | — | level | `is_mlb`, `level_display`, `level_rank`, `resolve_tier`, `sport_id_to_code`, `tier_keys_ordered`（來自 `.levels`） |

### 發現的問題

#### 1. Deadcode
- **helpers.py:236-247（中）** `highest_level()` 在整個 codebase **從未被呼叫**（外部只用 `highest_level_row`）。建議移除。
- **helpers.py:15-22（低）** re-export 中除 `level_rank`（被 `builder.py` 透過 helpers 使用）外，`is_mlb`/`level_display`/`resolve_tier`/`sport_id_to_code`/`tier_keys_ordered` 皆無 call site 透過 helpers 取用（使用者皆直接 `from .levels import`）。建議精簡 re-export。
- **helpers.py:246（低）** `resolve_tier` 僅在 deadcode 的 `highest_level()` 內使用，移除後 import 可一併移除。

#### 2. 程式碼邏輯錯誤
- **helpers.py:124-128（中）** `safe_int` 與 `safe_float` 行為不一致：`safe_int("3.0")` 會拋 `ValueError` 回 default（而非 3），對字串型整數靜默變 default。建議對齊（先 `safe_float` 再 `int`）。
- **helpers.py:171-176（中）** `ip_to_outs` 對非法值（如 `7.5`）`thirds = round(5)` 會產生不合理 outs，缺乏 clamp。建議 clamp 至 0–2 或記錄警告。
- **helpers.py:174（低）** `int(ip_value)` 對負 IP 向 0 取整會產生錯誤符號結果（防禦性問題）。
- **helpers.py:187/193（低）** `_HEIGHT_RE` 用 `re.match` 未錨定結尾；要求必有吋數，`"6'"`（無吋）會回 None。
- **helpers.py:30-31（低，已知 trade-off）** `Obj.__getattr__` 對缺失 key 回 None 而非拋 `AttributeError`，會掩蓋拼字錯誤。

#### 3. 數據計算正確性
- **helpers.py:340-344（高）** WHIP 守護條件不對稱：只在 `p_hits is not None` 時計算，分子 `(p_hits or 0) + (bb or 0)`。當 `p_hits` 有值但 `bb` 為 None 時把 BB 當 0，**低估 WHIP**。建議同時檢查 `p_hits` 與 `bb` 皆非 None。
- **helpers.py:573-583（中）** 投手 BABIP 分母 `(BF - SO - HR - BB)` 未扣除 HBP/SF/SH，會**高估分母、低估 p_babip**。打者版（458-468）以 AB 為基礎則正確。建議改為與打者版對稱的公式或補扣 HBP/SF/SH。
- **helpers.py:494-498 / 501-505 / 553-564（中）** K%/BB% 回傳 float、其它比率（SB%/Strike%/Win%/p_avg…）回傳 `_fmt_avg` 字串，型別不一致，模板需各自處理。建議統一同類百分比型的輸出策略。
- **helpers.py:332-339 / 206-215 / 311-330 / 452-456 / 471-475（正確）** ERA、OBP、AVG/SLG/OPS、ISO、AB/HR 公式皆正確，None 防護到位。**此類無計算錯誤。**

#### 4. 常數管理
- **helpers.py:196/203（中）** 單位換算係數 `2.54`、`12`、`0.453592` 硬編碼，建議抽 `_CM_PER_INCH`、`_INCHES_PER_FOOT`、`_KG_PER_LB`。
- **helpers.py:339/524-543（中）** 棒球規則常量 `9`（每九局）、`3`（每局出局數）大量重複，建議抽 `_OUTS_PER_INNING`、`_INNINGS_PER_GAME`。
- **helpers.py:多處（低）** 四捨五入精度位數（OBP/AVG/SLG/OPS 用 3、ERA/WHIP 用 2、IP 用 1…）以 magic number 散布，建議集中。
- **helpers.py:254（良好）** `_NATIONAL_TEAM_KEYWORD` 已正確抽成常數。

### 總結
結構清晰、註解詳盡、多數棒球公式正確、None 防護到位。優先：(1) **WHIP 守護條件**（高）；(2) 投手 BABIP 公式（中）；(3) `safe_int`/`safe_float` 一致性；(4) `ip_to_outs` clamp；(5) 單位/棒球規則係數抽常數；(6) 移除 `highest_level()` 與精簡 re-export。WHIP 與投手 BABIP 涉及對外數值正確性，建議優先驗證並補單元測試。

---

## jinja_env.py

### 檔案概述
此檔案是 Jinja2 環境組態中心：(1) 定義一組自訂 filters（數字／百分比／JSON／字串格式化與安全嵌入）；(2) 提供 URL factory，依 `base_url`／`site_origin` 產生相對與絕對連結；(3) 透過 `create_jinja_env()` 組裝 `Environment` 並註冊所有 filters 與 globals。是 `builder.py` 渲染 HTML 前的唯一環境設定來源。

### Function 與常數清單

| 名稱 | 類型 | 分類 | 功用說明 |
|------|------|------|----------|
| `_PROJECT_ROOT` (18) | 常數 | 路徑 | 專案根目錄絕對路徑 |
| `_TEMPLATE_DIR` (19) | 常數 | 路徑 | 預設模板目錄 `src/templates` |
| `floatformat` (25) | filter | 數字格式化 | 固定小數位格式化，None 回 `-`（模板使用 150 次）|
| `default_if_none` (35) | filter | 預設值 | None 時回 fallback（使用 36 次）|
| `num_dash` (40) | filter | 預設值 | None／空字串回 `-`（使用 254 次）|
| `slice_prefix` (47) | filter | 字串 | 取前 n 字元（模板 **0 次使用**）|
| `_json_html_safe` (54) | function | 安全 | 將 `</` 轉義避免提前關閉 `<script>` |
| `tojson_safe` (59) | filter | JSON | 序列化 JSON 並標記安全（使用 8 次）|
| `jsonld` (64) | filter | JSON | 緊湊 JSON-LD 序列化（使用 1 次）|
| `pct_fmt` (69) | filter | 百分比 | 小數分數轉百分比字串（使用 119 次）|
| `_make_url_helpers` (90) | function | URL | 產生 player/retired/static URL helper |
| `_make_absolute_url` (105) | function | URL | 產生 site_root 與 absolute_url helper |
| `create_jinja_env` (117) | function | 環境 | 組裝並回傳 Jinja2 Environment |

### 發現的問題

#### 1. Deadcode
- **jinja_env.py:47-51, 143（低）** `slice_prefix` 在所有模板 0 次使用，建議移除 function 與註冊。
- **jinja_env.py:156（低）** `site_origin` global 模板 0 次使用（僅內部建構 `site_url` 用到參數），建議確認是否為 SEO 預留，否則移除 global 註冊。
- 其餘 import 皆有實際使用。

#### 2. 程式碼邏輯錯誤
- **jinja_env.py:25-32, 69-84（中）** NaN 未被當缺值：`floatformat(nan)` 回 `"nan"`、`pct_fmt(nan)` 回 `"NaN%"`。Statcast/expected stats（除以 0、缺樣本）極易產生 nan，會直接印到頁面。建議在兩 filter 開頭加 NaN 偵測（`f != f`），`pct_fmt` 走 Decimal 路徑需顯式擋掉。
- **jinja_env.py:40-44（低）** `num_dash` 只比對 None 與 `""`，nan 會原樣回傳。
- **jinja_env.py:105-111（低）** `_make_absolute_url` 對 `base_url` 的處理依賴呼叫端已正規化的隱性前置條件，建議於 docstring 註明（目前功能無 bug）。

#### 3. 數據計算正確性
- **jinja_env.py:78-82（正確）** `pct_fmt` 用字串建構 Decimal + `ROUND_HALF_UP`，正確避免二進位浮點誤差（`0.345 → 34.5%`）。良好實作。
- **jinja_env.py:30（低）** `floatformat` 用 f-string `:.{digits}f` 採 banker's rounding，與 `pct_fmt` 的 HALF_UP 捨入策略不一致。對棒球數據多數差異不可見，視需求決定是否統一。
- 此檔**並未**提供日期格式化 filter（CLAUDE.md 描述與實際不符）。

#### 4. 常數管理
- **jinja_env.py:28/32/37/43/75/84（中）** 缺值佔位字串 `"-"` 硬編碼於四個 filter，建議抽 `_MISSING = "-"`。
- **jinja_env.py:25/69（低）** 預設 digits（floatformat 2、pct_fmt 1）建議命名常數。
- **jinja_env.py:120（低）** `site_origin` 預設值 `"https://tingruih.github.io"` 寫死在簽章，建議抽 `_DEFAULT_SITE_ORIGIN`。
- **jinja_env.py:61/66（低）** 兩 JSON filter 重複 `ensure_ascii=False`，可抽共用包裝。

### 總結
品質良好：URL factory 閉包設計清晰、`pct_fmt` 用 Decimal + HALF_UP 是亮點、JSON 的 `</` 轉義有正確處理。優先：(1) **NaN 缺值處理**（中，最可能造成使用者可見錯誤）；(2) 抽出缺值常數 `"-"`；(3) 移除死碼 `slice_prefix` 並確認 `site_origin` global；(4) 捨入策略一致性；(5) 修正 CLAUDE.md 關於「日期 filter」的文件落差。

---

## statcast.py

### 檔案概述
`site_builder/statcast.py` 是進階數據分析核心，兩層職責：(1) **萃取**：`extract_pitch_logs()` 從 `game/{pk}/feed/live` JSON 走訪每個 play 的 `playEvents`，過濾指定球員的逐球資料，快取於 `game_logs.pitches_json`；(2) **聚合與指標計算**：計算 whiff%、chase/O-Swing、CSW%、barrel%、hard-hit%、spray、wOBA、FIP、xWPCT、pitch movement chart、Pitch Plinko 等，分供投手（`compute_pitcher_statcast`）與打者（`compute_batter_statcast`）。外部呼叫者為 `sync.py` 與 `builder.py`。

### Function 與常數清單

| 名稱 | 類型 | 分類 | 功用說明 |
|------|------|------|---------|
| `SWING_CODES` / `WHIFF_CODES` / `CALLED_STRIKE_CODES` | 常數 | 結果碼分類 | 揮棒 / 揮空 / 看著好球的 `details.code` 集合 |
| `_W` / `_WOBA_FALLBACK` | 常數 | wOBA 權重 | 各年度 FanGraphs wOBA 權重表 / 後備(2019) |
| `get_woba_weights` | function | wOBA | 回傳指定年度的 wOBA 權重 |
| `WOBA_EVENT_MAP` | 常數 | wOBA | `eventType` → wOBA 分類鍵對照 |
| `FIP_CONSTANTS` | 常數 | FIP | 各 (層級, 年度) 的 FIP 常數 |
| `LEAGUE_RA9` | 常數 | xWPCT | 各層級的聯盟 RA/9 |
| `_NON_PA_EVENTS` | 常數 | wOBA/AB | 不算 PA 的跑壘事件 |
| `_BAT_SIDE_SPLITS` / `_COUNT_USAGE_BUCKETS` | 常數 | 分組 | 打者慣用手 / 球數桶 |
| `_PLINKO_COUNTS` / `_PLINKO_EDGES` / `_*_PLINKO_SPLITS` / `_BATTER_PLINKO_SKIP_TYPES` | 常數 | Plinko | Plinko 節點/邊/分組/排除球種 |
| `_GB/_LD/_FB/_PU/_AIR/_PULL_AIR_TRAJECTORIES` | 常數 | 擊球分類 | 滾地/平飛/高飛/內野飛球軌跡集合 |
| `_BATTED_BALL_RATE_DIGITS` | 常數 | 四捨五入 | 擊球率小數位數 (6) |
| `_GAMEDAY_*` / `_HIT_LOCATION_ZONE` | 常數 | 噴射角/方向 | Gameday 噴射角公式參數 / 守備位置→LF/CF/RF |
| `extract_pitch_logs` | function | 萃取 | 從 live-feed 萃取逐球資料 |
| `_ensure_pre_strikes` | function | 萃取 | 為舊快取補算 pre-count |
| `_is_swing/_is_whiff/_is_called_strike/_is_in_zone/_is_out_of_zone` | function | 分類 | 單球分類判斷 |
| `_is_barrel` / `_is_sweet_spot` | function | 分類 | barrel / sweet spot 判定 |
| `_ratio/_mean/_mean_round/_float_or_none` | function | 數學工具 | 安全除法、平均、轉 float |
| `_is_unknown_pitch_type/_filter_known_pitch_events` | function | 工具 | 未知球種過濾 |
| `_pre_count_tuple/_post_count_tuple/_count_label` | function | 工具 | 球數 tuple/label |
| `_empty_plinko_nodes/_empty_plinko_edges/_compute_pitch_plinko` | function | Plinko | Plinko 資料建構 |
| `compute_pitch_movement_chart` | function | 圖表 | 逐球進壘移動點 |
| `_spray_direction_from_location/_from_coordinates/_compute_spray` | function | 噴射 | 噴射方向分類與彙總 |
| `_aggregate_pitches` | function | 聚合 | 將 pitch 清單分類為各類別 |
| `_compute_woba` | function | wOBA | 計算 wOBA 分子/分母 |
| `_discipline_metrics/_batted_ball_metrics` | function | 指標 | 選球 / 擊球指標 dict |
| `compute_pitcher_statcast` | function | 投手 | 投手季度聚合主入口 |
| `_compute_pitch_arsenal_pitcher/_compute_pitch_outcomes_pitcher/_compute_pitch_usage_by_count_pitcher/_compute_pitcher_bat_side_splits` | function | 投手 | 投手球種細項 |
| `compute_batter_statcast` | function | 打者 | 打者季度聚合主入口 |
| `_compute_vs_pitch_types_batter` | function | 打者 | 打者對各球種細項 |
| `compute_fip` | function | FIP | FIP 計算 |
| `compute_xwpct` | function | xWPCT | 由 FIP 推估期望勝率 |
| `summarize_pitch_for_display` | function | 顯示 | 逐球顯示投影 |

### 發現的問題

#### 1. Deadcode
- **statcast.py:1157（低）** `_compute_pitch_usage_by_count_pitcher` 內 `if count_set is None:` 永不成立（所有 bucket 的 `counts` 皆非空 set），對應的「全部」桶邏輯從未執行。若原意要有彙總列應新增 `counts: None` bucket，否則移除分支。
- **statcast.py:1270 vs 165（中）** 區域變數 `_SKIP_TYPES = {"EP","FA"}` 與模組常數 `_BATTER_PLINKO_SKIP_TYPES = {"EP","FA"}` 重複，應合併共用。
- **statcast.py:171-172（低）** `_PULL_AIR_TRAJECTORIES = _AIR_TRAJECTORIES` 為 alias，各只用一次，可考慮合併以減少間接層。
- **statcast.py:648-651（低）** `compute_pitch_movement_chart` 內 `type_names.setdefault` 緊接條件覆寫，邏輯重疊可簡化。
- 已確認無未使用 import。

#### 2. 程式碼邏輯錯誤
- **statcast.py:311-312 / 368-369（高，語意風險）** `balls`/`strikes` 欄位語意為 post-pitch count，`_ensure_pre_strikes` 補算舊資料時假設其為 post-count。對新產出資料成立，但需確認所有快取資料一致，否則 pre-count 補算錯位。建議欄位改名為 `post_balls` 降低混淆。
- **statcast.py:1234（中）** ev90 用 nearest-rank 近似 `idx = min(int(len*0.9), len-1)`，n=10 時取索引 9（最大值），把 max_ev 當 ev90，明顯偏高（程式碼註解亦自承）。建議改用線性內插。
- **statcast.py:1238/1250（中）** sweet-spot% 分子 `sweet_spots` 對全部 in-play 計算，分母 `len(la_values)` 為有 LA 值的 BBE，母體不一致，高估 sweet-spot%。建議統一母體。
- **statcast.py:858/954（中）** barrel% 分母用 `n_ip`（所有 in-play），而 hard-hit% 分母用 `bbe_ev`（有 ev 的 BBE）。Savant 慣例兩者皆以 BBE 為分母，缺量測資料（MiLB）時 barrel% 會被低估。建議統一。
- **statcast.py:1362-1367（中）** `compute_fip` 後備迴圈遍歷 `FIP_CONSTANTS` 找同層級任一年度（`break` 取迭代首筆），未來多年度時不保證取最接近年度。建議改「同層級最新/最近年度」。
- **statcast.py:1082/1239/1293（中，定義性）** strike% 定義 `is_strike or is_in_play`，可能與 `isStrike` 重複（布林 or 不重複計數，影響為定義是否符合慣例）。
- **statcast.py:1108/1117（已驗證正確）** zone whiff%：whiff ⊂ swing，分子分母母體一致。
- **statcast.py:1247（正確）** `max_ev` 的 `ev` 已保證非 None。

#### 3. 數據計算正確性（重點）
- **wOBA 分母（statcast.py:902-918）** 排除 IBB、sac_bunt、非 PA 事件，保留 SF 在分母，與標準 FanGraphs wOBA 一致 ✅。建議於註解明確 SF 有意保留。
- **wOBA 權重表（statcast.py:31-40）** 核對 FanGraphs 2024 值一致 ✅；2026 為預估值需未來校正。
- **FIP 公式（statcast.py:1374）** `(13*HR + 3*(BB+HBP) - 2*K)/IP + cFIP` ✅ 標準正確。IP 需為小數局數，已驗證 caller（sync.py:1077）傳入 true innings。
- **barrel 判定（statcast.py:399-419）** EV≥98、98mph→[26°,30°]、每多 1mph 下界 −1°（地板 8°）上界 +1.5°（天花板 50°）：核對 100mph→[24,33]、116mph 飽和 [8,50] ✅。
- **sweet-spot（422-426）** 8°–32° ✅；**hard-hit（858）** EV≥95 ✅；**噴射角（715-778）** `atan2(hc_x−125.42, 198.27−hc_y)×0.75` ±15° 為標準公式 ✅。
- **whiff% / swstr% / CSW%（926-928）** 皆符合慣例 ✅。**put-away%（1032-1038）** 定義正確 ✅。
- **xWPCT（statcast.py:1380-1389）** `1/(1+(FIP/lgRA)^1.83)`：指數 1.83 實為傳統固定指數 Pythagorean，但 docstring 寫「Pythagenpat」**矛盾**（Pythagenpat 指數應動態計算）。公式可用但註解誤導，建議更正。
- **HR/FB%（statcast.py:993）** 分母 `agg["fb"]` 只含 `fly_ball`（不含 line_drive/popup），少數標為 line_drive 的 HR 會使 HR/FB 理論上可 >100%（邊角情況，低）。

#### 4. 常數管理
- **statcast.py:1270 vs 165（中）** 重複的 `{"EP","FA"}` 應合併為單一模組常數。
- **statcast.py:多處（中）** magic number 未抽常數：hard-hit `95`（858）、barrel 門檻 `98/26/30/1.5/8/50`（414-418）、sweet-spot `8/32`（426）、FIP 係數 `13/3/2`（1374）、FIP 後備 `3.2`（1367）、xWPCT 後備 `4.5`（1384）與指數 `1.83`（1386）、百分位 `0.9`（1234）。
- **statcast.py:391/396（低）** zone 範圍 `1<=z<=9`、`11<=z<=14` 建議具名；zone 10 未被任一邊涵蓋，建議註明（非標準 zone）。
- **statcast.py:48（低）** `get_woba_weights` 中 `max(_W)` 取最新年度作為 None 預設，建議加註解。
- **statcast.py:32（低）** 2026 wOBA 權重為預估占位值，建議加 `PROVISIONAL` 標記。

### 總結
結構清晰、註解詳盡（噴射角與 barrel 數學說明完整），核心棒球公式（FIP、wOBA 權重、barrel、sweet-spot、hard-hit、whiff/CSW、put-away、噴射角）**大多正確**。優先：(1) **ev90 百分位**（中高，最影響對外準確度）；(2) sweet-spot% 母體一致；(3) barrel%/hard-hit% 分母統一；(4) compute_fip 後備迴圈；(5) 移除死分支（1157）；(6) 合併重複 `{"EP","FA"}` 與抽 magic number；(7) 修正 xWPCT docstring。無發現會造成崩潰的 bug；除以零均由 `_ratio` 妥善處理。

---

## sync.py

### 檔案概述
`site_builder/sync.py` 是資料同步核心：(1) 初始化 SQLite schema 與 forward-migration；(2) 從 MLB Stats API 平行抓取球員 profile、yearByYear / seasonAdvanced 統計、game logs、next game 並寫入 SQLite；(3) 提供 `sync_database()`（完整歷史同步）與 `update_database()`（當前球季快速更新），兩者共用 `_run_pipeline()`；(4) Statcast 子系統（`sync_statcast()`）：抓取 playByPlay、抽取 pitch logs、回填 sport_level、平行計算 Statcast 聚合與 sabermetrics / expected stats，merge 回 `season_stats`。

### Function 與常數清單

| 名稱 | 類型 | 分類 | 功用說明 |
|------|------|------|----------|
| `MAX_WORKERS` | 常數 | ThreadPool | 所有平行階段的執行緒數（= 10） |
| `logger` | 常數 | 日誌 | 模組層級 logger |
| `_init_db` | function | Schema | 建立資料表/索引並執行 forward-migration |
| `_load_season_row` | function | DB 讀取 | 讀取單一 season_stats 列，反序列化 JSON |
| `_save_season_row` | function | DB 寫入 | UPSERT season_stats 列 |
| `_players_with_existing_stats` | function | DB 讀取 | 回傳已有 season_stats 的 mlb_id 集合 |
| `_warn_orphaned_players` | function | 維運 | 警告 DB 中不在 roster 的孤兒球員 |
| `_is_first_sync` | function | 判斷 | 判斷球員是否第一次同步 |
| `_apply_yearbyyear_fields` | function | 欄位對應 | yearByYear API 欄位 → stat_doc |
| `_apply_advanced_fields` | function | 欄位對應 | seasonAdvanced API 欄位 → stat_doc |
| `_fetch_player_data` | function | 平行抓取 | 抓取單一球員所有 API 資料（無 DB 寫入） |
| `_write_player_to_db` | function | DB 寫入 | 將一個 bundle 寫入 SQLite |
| `_run_pipeline` | function | 流程 | sync/update 共用的抓取+寫入 pipeline |
| `sync_database` / `update_database` | function | 進入點 | 完整歷史同步 / 當前球季快速更新 |
| `_build_roster_map` | function | 工具 | `{mlb_id: pconf}` 對照表 |
| `_fetch_and_extract_game` | function | Statcast | 抓取一場 live feed 並抽取 pitches |
| `_pitches_need_hit_coord_backfill` | function | Statcast | 判斷 pitches 是否需回填打擊座標 |
| `_load_all_pitches_for_player` | function | Statcast | 載入並依 (year, level) 分組所有 pitches |
| `_merge_statcast_into_season` | function | Statcast | merge statcast/saber/expected 進 season_stats |
| `_compute_player_statcast_bundle` | function | Statcast | 平行 worker：載入 pitches + 抓 API + 計算 |
| `sync_statcast` | function | 進入點 | Statcast 同步主流程 |

### 發現的問題

#### 1. Deadcode
- 本檔無明顯「完全不會執行」的死碼或未使用 import。所有 import（`get_game_sport_level`, `compute_xwpct`, `TIERS` 等）皆有使用。
- 較明確的失效機制見「邏輯錯誤」中的 `playbyplay_processed` 表（只寫不讀）。

#### 2. 程式碼邏輯錯誤
- **sync.py:653-657（中）** `level_order_sql` 用 f-string 把 `t.aliases` 內插進 SQL（`WHEN '{alias}' THEN {t.rank}`）。目前 aliases 不含單引號暫時安全，但脆弱；任何含 `'` 的新 alias 會破壞 SQL。建議移到 `levels.py` 提供受控 `level_case_sql()` helper。
- **sync.py:1061-1063（中）** sabermetrics 寫入條件冗餘：外層已是 `row_sport_level == "MLB"`，內層又限制 `not sport_level or row_sport_level == sport_level`。當 merge 由 AAA pitches 觸發（`sport_level="AAA"`）時，MLB 列不會寫入 sabermetrics（須等 MLB pitches 那次補上）。建議 sabermetrics 只看 `row_sport_level == "MLB"`。
- **sync.py:1379-1384 vs docstring 1206-1209（中）** `playbyplay_processed` 表**只寫不讀**：Phase 1 的 `needs_fetch` 判斷（1286-1303）只看 `game_logs.pitches_json` / `hit_coord_checked`，未查此表，docstring 與實作不符。建議啟用過濾或移除該表。
- **sync.py:1167（中）** `if not any([xba, xslg, xwoba, xwobacon])` 把合法 `0.0` 當無資料（`any()` 視 0.0 為 False），整筆 `continue` 略過。建議改 `if all(v is None for v in (...))`。
- **sync.py:1120 vs 743/1217（中）** worker 連線 `timeout=30`，主連線用預設 5s，鎖等待時間不一致。建議主連線也設 `timeout` 並考慮 `PRAGMA journal_mode=WAL` 改善讀寫並行。
- **sync.py:1071-1072（低-中）** `sport_level` 為空且多列時 expected_stats 不寫（無 else），屬刻意防重複，標註為已知資料遺失點。

#### 3. 數據計算正確性
- **sync.py:585-586（低）** two-way 球員同年同隊既投又打時 `stat_doc["gp"]` 會被後處理的 group 覆寫，最終值取決於處理順序。建議分開存 `gp_hitting` / `gp_pitching`。
- **sync.py:1087-1092（低）** MLB FIP 取自 sabermetrics 並 `round(,2)`，MiLB FIP 由 `compute_fip` 計算未在此 round，精度處理不一致。
- **sync.py:278-279/307-311/349-350（低）** `win_pct`/`strike_pct`/`p_avg`/`sb_pct` 以 `str(...)` 存原始字串而非數值，與其他欄位用 `safe_float` 不一致（僅顯示則 OK）。
- **sync.py:608-611（正確）** fielding entry 先移除同 position 舊 entry 再 append，避免重複，良好。

#### 4. 常數管理
- **sync.py:53-114（中）** 整段 schema DDL 為 inline 字串，表名（"season_stats"/"game_logs"/"players"/"playbyplay_processed"）、column 名（"sport_level"/"pitches_json"/"stat_json"）數十處硬編碼，建議至少抽出表名常數。
- **sync.py:953 / 1246 / 1295（中）** 「空 pitches」判定三處不一致：953 未排除 `'null'`、1246 排除、1295 `in (None,"[]")` 未排除 `'null'`（而 1360 會寫 `"null"`）。建議抽 `EMPTY_PITCHES = ("[]", "null", None)` 統一。
- **sync.py:1120 vs 743/1217（中）** DB connect timeout 不一致且 magic number `30`，建議抽 `DB_TIMEOUT`。
- **sync.py:661（低）** SQL CASE 的 fallback rank `50` 硬編碼，levels.py:73 已有 `_UNKNOWN_RANK = 50`（私有未匯出），建議引用同一常數。
- **sync.py:1328（低）** 進度列印間隔 `25` 為 magic number，建議 `PROGRESS_LOG_INTERVAL`。
- **sync.py:545-546/669/675-678（低）** 預設字串 `"Minors"` / `"N/A"` 多處硬編碼（也出現在 DDL DEFAULT），建議常數化。
- **sync.py:47（良好）** `MAX_WORKERS = 10` 已抽常數並有註解。

### 總結
結構清晰、註解詳盡、平行抓取/序列寫入模式正確，UPSERT 與 UNIQUE 衝突處理大致妥當。優先：(1) **`playbyplay_processed` 只寫不讀**（docstring 與行為不符）；(2) sabermetrics 寫入條件冗餘矛盾；(3) 「空 pitches」判定三處不一致統一為 `EMPTY_PITCHES`；(4) `any([...])` 把合法 0.0 當無資料；(5) level CASE f-string 拼接與 `ELSE 50` 引用 `_UNKNOWN_RANK`；(6) DB timeout 一致化與表名常數化（考慮 WAL）。無發現會立即導致資料損毀的高嚴重度錯誤。需交叉核對 `levels.py`（CASE rank / `_UNKNOWN_RANK`）與 `helpers.py`（safe_*/loads_*）。

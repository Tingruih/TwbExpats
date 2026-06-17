# site_builder Function List

這份文件整理目前 `site_builder/` 目錄內所有 Python 檔案的模組用途、模組級常數/變數、class 與 module-level function。

範圍：
- `site_builder/__init__.py`
- `site_builder/api.py`
- `site_builder/builder.py`
- `site_builder/helpers.py`
- `site_builder/jinja_env.py`
- `site_builder/statcast.py`
- `site_builder/sync.py`

註記：
- 以目前程式碼內容為準。
- 這份文件只整理 module-level symbol，不展開函式內的區域變數。
- 私有 helper（底線開頭）也一併列入，因為它們是整個 site builder 內部資料流的重要組件。

---

## `site_builder/__init__.py`

### 模組用途
`site_builder` package 初始化檔。目前沒有額外邏輯，主要用途是標示目錄為 Python package。

### 常數 / 變數
- 無。

### Classes
- 無。

### Functions
- 無。

---

## `site_builder/api.py`

### 模組用途
封裝 MLB Stats API 呼叫，負責把球員、比賽、賽程、sabermetrics 與 expected stats 等外部資料抓回來，提供 `sync.py` 與其他同步流程使用。

### 常數 / 變數
- `logger`
  - 模組 logger。
  - 用來記錄 API 失敗、fallback 與讀檔錯誤。
- `BASE_URL`
  - MLB Stats API 根網址（`/api/v1`）。
  - 所有主要 REST endpoint 都以它為基底。
- `TIMEOUT`
  - 預設 HTTP timeout 秒數（15）。
  - 統一控制 requests 呼叫逾時行為。
- `_SPORT_ID_MAP`
  - `sport.id -> 等級簡稱` 對照表。
  - 將 API 回傳的 numeric sport id 轉成 `MLB`、`AAA`、`AA`、`A+`、`A`、`A-`、`ROK`。
- `_SPORT_NAME_TO_ABBR`
  - `sport.name -> 等級簡稱` 對照表。
  - 當 sport id 不可用時，作為文字型 fallback。

### Classes
- 無。

### Functions
- `get_player_profile(mlb_id: int) -> dict`
  - 取得球員基本資料、交易紀錄、roster 狀態與目前球隊資訊。
  - 會額外查一次 team endpoint，把目前球隊轉成對應 level。

- `get_player_stats(mlb_id: int) -> list`
  - 取得球員 year-by-year 的 hitting、pitching、fielding 統計。
  - 會同時打 MLB 與 MiLB endpoint，避免 shuttle player 資料遺漏。

- `get_player_advanced_stats(mlb_id: int, years: Optional[list[int]] = None) -> list`
  - 取得 `seasonAdvanced` 類型的打擊與投球進階統計。
  - 可指定年份；未指定時抓預設範圍。

- `get_game_logs(mlb_id: int, season: int) -> list`
  - 取得指定球季的逐場出賽紀錄。
  - 一樣同時查 MLB 與 MiLB，確保跨等級球員資料完整。

- `get_next_game(team_id: int) -> Optional[dict]`
  - 查詢球隊未來 7 天內的下一場賽程。
  - 回傳對手、主客、時間、球場與狀態等前端卡片需要的資訊。

- `get_game_play_by_play(game_pk: int) -> dict`
  - 取得單場比賽完整 live feed JSON（`api/v1.1` endpoint）。
  - 提供 `statcast.py` 的 pitch extraction 使用。

- `sport_obj_to_abbr(sport: dict) -> str`
  - 將 API 的 `sport` 物件轉成站內使用的 level 簡稱。
  - 先用 id 對照，失敗再退回 name 對照。

- `get_game_sport_level(game_pk: int) -> str`
  - 只抓單場比賽的 sport level。
  - 用 fields-filtered endpoint 減少 payload，主要給歷史 game log backfill 使用。

- `get_player_sabermetrics(mlb_id: int, years: Optional[list[int]] = None) -> list`
  - 取得 `sabermetrics` 類型資料（MLB only）。
  - 主要用在 FIP、xFIP、WAR、wRC+ 等 MLB-only 欄位補寫。

- `get_player_expected_stats(mlb_id: int, years: Optional[list[int]] = None, group: str = "pitching") -> list`
  - 取得 `expectedStatistics` 類型資料，例如 xBA、xSLG、xwOBA、wobaCon。
  - 只打 MLB endpoint，因為 MiLB endpoint 目前對 expected stats 一律回 0.0。

- `parse_roster_from_file(filepath: str) -> list`
  - 讀取 `roster.json`。
  - 回傳 `players` 陣列，提供同步與 statcast pipeline 建立球員清單。

---

## `site_builder/builder.py`

### 模組用途
從 SQLite 載入球員、球季、逐場與 statcast 資料，經過整併與整理後，套用 Jinja2 模板輸出靜態網站 HTML，並產生 SEO 結構化資料、sitemap 與 robots。

### 常數 / 變數
- `_PROJECT_ROOT`
  - 專案根目錄 `Path`。
  - 用來定位 `src/static`、`data/headshots` 等資源。
- `_SITE_TITLE`
  - 首頁／站台預設標題。
- `_SITE_DESCRIPTION`
  - 站台預設 SEO 描述。
- `_SITE_SAME_AS`
  - 站台關聯外部連結（Threads、GitHub），用於 schema.org `sameAs`。
- `_BAT_SIDE_SPLITS`
  - 投手面對打者側別的 split 定義（all / L / R）。
- `_COUNT_USAGE_BUCKETS`
  - 球數情境分群定義（含 `all`、`early`、`pitcher_ahead`、`pitcher_behind`、`pre_two_strikes`、`two_strikes`）。
- `_PLINKO_COUNTS`
  - Pitch Plinko 節點清單（字串型 `"B-S"`）。
- `_PLINKO_EDGES`
  - Pitch Plinko 連線清單（合法 count-to-count 轉移）。

### Classes
- 無。

### Functions

#### 通用 helper
- `_ratio(num: int, den: int) -> float | None`
  - 安全除法 helper（四位小數）。
- `_is_unknown_pitch_type(pitch_type, pitch_name=None) -> bool`
  - 判斷球種是否屬於未知 placeholder（`UN` / `UNKNOWN`）。

#### 跨等級 statcast 整併
- `_combine_pitch_type_data(entries, sc_key, rate_fields, include_pct=False) -> list[dict]`
  - 球種資料通用合併器。
  - 將多個 level 的球種資料按 `count` 做加權平均，並以 `two_strike_count` 正確加權 `put_away_pct`。
- `_combine_vs_pitch_types(entries) -> list[dict]`
  - 整併打者 `vs_pitch_types`。
- `_combine_pitch_outcomes(entries) -> list[dict]`
  - 整併投手 `pitch_outcomes`。
- `_combine_pitch_arsenal(entries) -> list[dict]`
  - 整併投手 `pitch_arsenal`（速度、位移、轉速、extension 與各 rate）。
- `_combine_pitch_usage_by_count(entries) -> dict`
  - 合併不同層級的 `pitch_usage_by_count`，逐情境加總後重算比例。
- `_combine_pitcher_bat_side_splits(entries) -> dict`
  - 合併投手面對 `all / L / R` 打者的 split statcast 資料。
- `_combine_pitch_plinko(entries) -> dict`
  - 合併多 level 的 Plinko 節點、連線與球種分布。
- `_combine_pitch_movement(entries) -> dict`
  - 合併跨等級 pitch movement chart 點集（含 900 點上限抽樣）。
- `_combine_statcast_dicts(entries) -> dict`
  - 把多層級 statcast summary 合成 `_combined` 列，依欄位性質選用 `total_pitches` / `bbe` / `pa_count` 加權，並整併所有 pitch-level 子結構。

#### 資源 / 顯示挑選
- `_prefetch_headshots(mlb_ids, cache_dir, dest_dir) -> None`
  - 預抓球員頭像到本地 cache，再複製到輸出目錄。
- `_pick_display_stat(stats_current, player)`
  - 從同年多筆 stat row 挑出要顯示的那筆（當前球隊 → 當前層級 → 最高有出賽層級）。

#### SEO / 探索檔
- `_player_display_name(player) -> str`
  - 組合中英文顯示名稱。
- `_player_canonical_path(player) -> str`
  - 產生球員頁的 canonical 相對路徑。
- `_player_description(player) -> str`
  - 產生球員頁 SEO 描述。
- `_index_structured_data(absolute_url, player_data) -> list`
  - 產生首頁的 schema.org JSON-LD（WebSite + ItemList）。
- `_player_structured_data(absolute_url, player) -> list`
  - 產生球員頁的 schema.org JSON-LD（Person + BreadcrumbList）。
- `_write_robots(out_dir, sitemap_url) -> None`
  - 寫出 `robots.txt`。
- `_write_sitemap(out_dir, urls) -> None`
  - 寫出 `sitemap.xml`。

#### 資料載入與主入口
- `_load_player_bundle(cur, player_row) -> tuple`
  - 從 SQLite 一次載入單一球員完整資料包（profile、season stats、fielding、game logs、statcast JSON、roster 狀態分類）。
- `build_static_site(db_path, year, output_dir, base_url="/") -> None`
  - 靜態網站主入口。
  - 建立輸出資料夾、複製靜態資源、載入 DB、渲染首頁與所有球員頁、寫出逐場 pitch log JSON、`404.html`、`sitemap.xml`、`robots.txt` 與 `.nojekyll`。

---

## `site_builder/helpers.py`

### 模組用途
集中放置共用工具：roster 狀態分類、安全型別轉換、JSON 序列化、日期與單位轉換、球季/生涯彙總，以及進階統計衍生欄位計算。

### 常數 / 變數
- `SPORT_LEVEL_ORDER`
  - 站內統一使用的等級排序表（MLB=0 … Minors=99）。
- `DEFAULT_SEASON_YEAR`
  - 預設球季年份（來自環境變數，未設定則 `2026`）。
- `ROSTER_INJURED_CODES`
  - 代表球員在傷兵名單（或復健指派）的 roster status code 集合。
- `ROSTER_RESTRICTED_CODES`
  - 代表球員在個人／紀律性離隊的 roster status code 集合（停賽、保留名單、喪假等）。
- `ROSTER_OTHER_CODES`
  - 代表過渡型名單異動（如 DFA limbo）的 code 集合。
- `ROSTER_INACTIVE_CODES`
  - 代表球員已離開組織（Released / Retired / Voluntarily Retired）的 code 集合。
- `_COUNTING_FIELDS`
  - 聚合時計入加總的欄位名單（橫跨 hitting、pitching 與部分 advanced counting）。
- `_HEIGHT_RE`
  - 身高字串解析用 regex。

### Classes
- `Obj`
  - `dict` 的薄包裝，提供 `obj.key` 與 `obj["key"]` 兩種存取方式。

### Functions

#### Roster 狀態分類
- `categorize_roster_status(code, is_active_entry, player_is_active) -> str`
  - 把球員最新 roster entry 映射成 status-pill 分類。
  - 回傳 `"active"` / `"injured"` / `"restricted"` / `"inactive"` / `"other"`。

#### 安全型別轉換
- `safe_float(value, default=None)`
  - 安全轉成 `float`，失敗回 `default`。
- `safe_int(value, default=None)`
  - 安全轉成 `int`，失敗回 `default`。

#### JSON helpers
- `loads_json(text, default)`
  - JSON 字串解析器，支援原本就是 `dict/list` 的情況。
- `loads_json_dict(text) -> dict`
  - 保證回傳 `dict`（失敗回 `{}`）。
- `loads_json_list(text) -> list`
  - 保證回傳 `list`（失敗回 `[]`）。
- `dumps_json(value) -> str`
  - 以緊湊 separators 序列化為 JSON 字串。

#### 日期 / 單位
- `parse_date(text)`
  - 把 ISO 字串轉成 `datetime.date`，格式錯誤回 `None`。
- `ip_to_outs(ip_value) -> int`
  - 將棒球小數局數轉為 out 數（`7.2` → 23 outs）。
- `outs_to_ip(outs) -> Optional[float]`
  - 將 outs 轉回棒球顯示用局數（23 outs → `7.2`）。
- `height_to_cm(height_str)`
  - 把英尺英吋字串轉為公分。
- `lbs_to_kg(weight_lbs)`
  - 把磅數轉為公斤。
- `calc_obp(hits, bb, hbp, ab, sac_flies)`
  - 計算 OBP。
- `has_appearance(stat) -> bool`
  - 判斷某 row 是否真的有出賽（GP/PA/AB/BF/IP 任一成立）。

#### 統計聚合
- `_sum_counting(stats, result)`
  - 對 `_COUNTING_FIELDS` 逐欄加總。
- `_compute_rate_stats(agg)`
  - 由聚合後 counting stats 補算 rate stats（AVG/OBP/SLG/OPS/ERA/WHIP）。
- `_aggregate_stats(stats)`
  - 聚合多筆 stat row 的通用流程（加總 → IP → rate）。
- `compute_career(stats, level_filter=None)`
  - 計算生涯累計（可只算 MLB / MiLB / 全部）。
- `compute_season_combined(stats, year)`
  - 計算單一球季跨隊合併 row。
- `_fmt_avg(value)`
  - 把小數格式化成棒球慣用打擊率字串（`0.333` → `.333`）。
- `_compute_advanced_stats(s)`
  - 依現有欄位補齊衍生進階統計（打者與投手皆涵蓋，例如 ISO、BABIP、K%、BB%、P/PA、GO/AO、/9 rates、對戰打擊線等）。
- `annotate_computed_stats(all_stats)`
  - 對整份 stat row 清單逐筆套用 `_compute_advanced_stats`（並設 `np` alias）。
- `compute_year_groups(all_stats)`
  - 把球季資料整理成「按年份分組」結構（summary row + per-team detail rows）。

---

## `site_builder/jinja_env.py`

### 模組用途
建立 Jinja2 Environment，註冊模板 filters 與全域 helper（含 URL 生成與絕對網址、JSON-LD），讓靜態網站渲染時有一致的格式化與連結行為。

### 常數 / 變數
- `_PROJECT_ROOT`
  - 專案根目錄路徑。
- `_TEMPLATE_DIR`
  - 預設模板目錄路徑（`src/templates`）。

### Classes
- 無。

### Functions
- `floatformat(value, digits=2)`
  - 將數字格式化成固定小數位，`None`/錯誤回 `-`。
- `default_if_none(value, fallback="-")`
  - 值為 `None` 時回 fallback。
- `num_dash(value)`
  - 顯示數字；空值顯示 `-`。
- `slice_prefix(value, n)`
  - 取字串前 `n` 個字元。
- `_json_html_safe(s) -> str`
  - 把 `</` 轉義成 `<\/`，避免內嵌 JSON 提前關閉 `<script>`。
- `tojson_safe(value)`
  - 轉 JSON 並標記為 HTML safe（給 `<script>` 內嵌資料）。
- `jsonld(value)`
  - 以緊湊格式序列化 JSON-LD 並標記為 HTML safe。
- `pct_fmt(value, digits=1)`
  - 將 `0.xxx` 小數格式化為百分比字串（`Decimal + ROUND_HALF_UP`）。
- `_make_url_helpers(base_url) -> tuple`
  - 產生 `player_url()` 與 `static_url()` 兩個 helper。
- `_make_absolute_url(site_origin, base_url) -> tuple`
  - 產生站台根網址與 `absolute_url()`，用於 canonical / og / sitemap 絕對連結。
- `create_jinja_env(template_dir=None, base_url="/", site_origin="https://tingruih.github.io")`
  - 建立完整設定好的 Jinja2 environment。
  - 註冊全部 filters、URL/absolute_url/site_url 等 global，並 normalize `base_url`。

---

## `site_builder/statcast.py`

### 模組用途
處理 pitch-level 資料提取、分類、指標計算與前端展示資料整形。包含打者/投手 statcast summary、pitch movement、spray、pitch plinko、FIP 與 xWPCT 等公式。

### 常數 / 變數
- `SWING_CODES` / `WHIFF_CODES` / `CALLED_STRIKE_CODES`
  - 結果代碼分類集合（swing / whiff / called strike）。
- `_W`
  - 各年份 wOBA 權重表。
- `_WOBA_FALLBACK`
  - 年份不在表內時的 fallback 權重。
- `WOBA_EVENT_MAP`
  - `pa_event -> wOBA 權重鍵值` 對照。
- `FIP_CONSTANTS`
  - `(sport_level, year) -> FIP constant`。
- `LEAGUE_RA9`
  - 各 level 用於 xWPCT 的聯盟 RA/9 基準。
- `_NON_PA_EVENTS`
  - 不視為正式 plate appearance outcome 的事件集合。
- `_BAT_SIDE_SPLITS`
  - 投手面對打者側別的 split 定義。
- `_COUNT_USAGE_BUCKETS`
  - 球數情境分類定義（含 counts 集合）。
- `_PLINKO_COUNTS`
  - Pitch Plinko 節點定義（tuple 型 `(balls, strikes)`）。
- `_PLINKO_EDGES`
  - Pitch Plinko 邊定義。
- `_BATTER_PLINKO_SPLITS` / `_PITCHER_PLINKO_SPLITS`
  - 打者（vs LHP/RHP）與投手（vs LHB/RHB）Plinko 的 split 規則。
- `_BATTER_PLINKO_SKIP_TYPES`
  - 打者 Plinko 要略過的球種（`EP` / `FA`）。
- `_GB_TRAJECTORIES` / `_LD_TRAJECTORIES` / `_FB_TRAJECTORIES` / `_PU_TRAJECTORIES` / `_AIR_TRAJECTORIES` / `_PULL_AIR_TRAJECTORIES`
  - 各 batted-ball trajectory 分類集合。
- `_BATTED_BALL_RATE_DIGITS`
  - batted-ball rate 的 rounding 精度。
- `_GAMEDAY_HOME_X` / `_GAMEDAY_HOME_Y` / `_GAMEDAY_SPRAY_CORRECTION` / `_GAMEDAY_LEFT_FIELD_THRESHOLD_DEG` / `_GAMEDAY_RIGHT_FIELD_THRESHOLD_DEG`
  - Gameday spray chart 的本壘座標基準、角度修正係數與左右外野判定門檻。
- `_HIT_LOCATION_ZONE`
  - `hit_location -> 大致落點區域` 對照，用於 fallback spray 分類。

### Classes
- 無。

### Functions

#### wOBA 權重
- `get_woba_weights(year=None) -> dict`
  - 取得指定年份的 wOBA 權重（含 fallback）。

#### 資料提取與前處理
- `extract_pitch_logs(game_data, player_id, role) -> list[dict]`
  - 從單場 live feed 提取球員逐球資料（依 pitcher / batter 過濾，含 pre-count 追蹤）。
- `_ensure_pre_strikes(pitches) -> None`
  - 回填舊資料缺少的 `pre_balls` / `pre_strikes`。

#### 分類函式
- `_is_swing(p) -> bool`
- `_is_whiff(p) -> bool`
- `_is_called_strike(p) -> bool`
- `_is_in_zone(p) -> bool` / `_is_out_of_zone(p) -> bool`
- `_is_barrel(ev, la) -> bool`
- `_is_sweet_spot(la) -> bool`

#### 通用數值 helper
- `_ratio(num, den, digits=3)`
- `_mean(values)` / `_mean_round(values, digits=1)`
- `_float_or_none(value) -> Optional[float]`
- `_is_unknown_pitch_type(pitch_type, pitch_name=None) -> bool`
- `_filter_known_pitch_events(pitches) -> list[dict]`
- `_pre_count_tuple(p)` / `_post_count_tuple(p)`
- `_count_label(count) -> str`
- `_empty_plinko_nodes()` / `_empty_plinko_edges()`

#### Plinko / movement / spray 圖表資料
- `_compute_pitch_plinko(pitches, *, split_field, split_specs, skip_types=None) -> dict`
  - 計算 Pitch Plinko 的 split、node、edge 與 node 內球種分布。
- `compute_pitch_movement_chart(pitches, max_points=700) -> dict`
  - 將逐球資料轉成 pitch movement chart 用的輕量點集（含點數上限抽樣）。
- `_spray_direction_from_location(p) -> Optional[str]`
  - 依 `hit_location` 做簡化 spray 分類 fallback。
- `_spray_direction_from_coordinates(p) -> Optional[str]`
  - 依 Gameday hit coordinates 計算 spray 方向。
- `_compute_spray(in_play) -> dict`
  - 綜合計算 `pull / straight / oppo / pull_air` 數量。

#### 共享聚合流程
- `_aggregate_pitches(pitches) -> dict`
  - 把逐球資料切成 swing、whiff、called、in-zone、in-play 等分類集合。
- `_compute_woba(pa_final, woba_w) -> tuple[float, int]`
  - 從 PA 結束球計算 wOBA numerator 與 denominator。
- `_discipline_metrics(agg) -> dict`
  - 由 `_aggregate_pitches()` 結果組出 discipline metrics。
- `_batted_ball_metrics(agg, sport_level="") -> dict`
  - 由 `_aggregate_pitches()` 結果組出 batted-ball metrics。

#### 投手 statcast
- `compute_pitcher_statcast(pitches, year=None, sport_level="") -> dict`
  - 投手端 statcast 主入口。
- `_compute_pitch_arsenal_pitcher(pitches, year=None) -> list[dict]`
- `_compute_pitch_outcomes_pitcher(pitches, year=None) -> list[dict]`
- `_compute_pitch_usage_by_count_pitcher(pitches) -> dict`
- `_compute_pitcher_bat_side_splits(pitches, year=None) -> dict[str, dict]`

#### 打者 statcast
- `compute_batter_statcast(pitches, year=None, sport_level="") -> dict`
  - 打者端 statcast 主入口。
- `_compute_vs_pitch_types_batter(pitches, year=None) -> list[dict]`

#### 公式與展示 helper
- `compute_fip(hr, bb, hbp, k, ip, sport_level, year, c_fip=None) -> Optional[float]`
  - 計算 FIP（含常數 fallback）。
- `compute_xwpct(fip, sport_level) -> Optional[float]`
  - 依 FIP 與聯盟 RA/9 推估 xWPCT。
- `summarize_pitch_for_display(p) -> dict`
  - 把完整 pitch dict 投影成逐場展開表格需要的輕量欄位。

---

## `site_builder/sync.py`

### 模組用途
負責資料同步與 SQLite 寫入，包含完整同步、快速更新，以及 statcast pitch-level 同步與聚合回寫。

### 常數 / 變數
- `logger`
  - 模組 logger。
- `MAX_WORKERS`
  - 平行抓取的最大 worker 數（8）。

### Classes
- 無。

### Functions

#### 資料庫 schema 與 row I/O
- `_init_db(conn) -> None`
  - 初始化 SQLite schema，建立 `players`、`season_stats`、`game_logs`、`playbyplay_processed` 與索引，並做 forward migration（`pitches_json`、`sport_level`、`roster_status_code`、`roster_is_active`）。
- `_load_season_row(cur, mlb_id, year, team_name) -> dict`
  - 讀取單一 `season_stats` row，不存在則回傳空白預設結構。
- `_save_season_row(cur, mlb_id, year, team_name, league_name, sport_level, stat_json, fielding_json) -> None`
  - 以 upsert 寫入 `season_stats`。
- `_players_with_existing_stats(conn) -> set[int]`
  - 回傳已有 `season_stats` 紀錄的 mlb_id 集合，用來判斷哪些球員是首次同步。
- `_is_first_sync(mlb_id, synced_ids) -> bool`
  - 判斷某球員是否為首次同步（沒有任何 season_stats row）。

#### API 欄位對應
- `_apply_yearbyyear_fields(stat_doc, group_name, stat) -> None`
  - 把 API `yearByYear` 欄位映射進站內欄位（依 hitting / pitching / fielding）。
- `_apply_advanced_fields(stat_doc, group_name, stat) -> None`
  - 把 API `seasonAdvanced` 欄位映射進站內欄位。

#### 球員同步主流程
- `_fetch_player_data(pconf, year, fetch_all_years=True) -> Optional[dict]`
  - 平行抓取單一球員所需 API 資料（不寫 DB）；對已離隊且非首次同步者只刷新 profile。
- `_write_player_to_db(conn, bundle, year) -> None`
  - 將 `_fetch_player_data()` 的 bundle 寫入 DB（profile、season stats、advanced、fielding、game logs、next game snapshot、level/team）。
- `_run_pipeline(db_path, roster_file, year, only_player=None, fetch_all_years=True, mode_label="Sync") -> None`
  - 共用同步主流程：先平行抓資料，再序列寫入 DB；對首次同步者強制完整 backfill。
- `sync_database(db_path, roster_file, year, only_player=None) -> None`
  - 完整同步入口（抓所有歷史年份 game log）。
- `update_database(db_path, roster_file, year, only_player=None) -> None`
  - 快速更新入口（只刷新當季 game log，但仍更新球員檔與球季統計）。

#### Statcast 同步輔助
- `_build_roster_map(roster_file) -> dict`
  - 從 roster 設定建立 `{mlb_id: player_config}` 對照。
- `_fetch_and_extract_game(game_pk, players_in_game) -> tuple[dict[int, list[dict]], str]`
  - 抓取單場 live feed 並替涉及的 roster player 提取 pitch logs，同時回傳該場 sport level。
- `_pitches_need_hit_coord_backfill(pitches) -> bool`
  - 判斷某批 pitch 是否缺少 hit coordinates。
- `_load_all_pitches_for_player(cur, mlb_id) -> dict[tuple, list[dict]]`
  - 從 `game_logs.pitches_json` 載入單一球員所有 pitch cache，依 `(year, sport_level)` 分組（含空 level 解析）。
- `_merge_statcast_into_season(cur, mlb_id, year, position, statcast_data, sport_level="", sabermetrics=None, expected_stats=None) -> None`
  - 把重算完的 statcast / sabermetrics / expected stats 回寫到對應 sport level 的 `season_stats.stat_json`（含 MiLB FIP/xWPCT、MLB FIP/xFIP/WAR、wRC+ 計算）。
- `sync_statcast(db_path, roster_file, year, only_player=None) -> None`
  - Statcast 專用同步入口：sport_level backfill → 補抓 play-by-play → 提取 pitches → 更新 `game_logs.pitches_json` → 重算整季 statcast 並回寫 DB。

---

## site_builder 內部資料流總覽

### 1. 外部資料抓取
- `api.py` 負責呼叫 MLB Stats API。
- `sync.py` 以 roster 為起點，平行抓回 player profile、season stats、advanced stats、game logs、next game 與 play-by-play。

### 2. 資料落地
- `sync.py` 將資料寫入 SQLite：`players`、`season_stats`、`game_logs`、`playbyplay_processed`。

### 3. 統計與聚合
- `helpers.py` 處理 roster 狀態分類、一般球季、生涯與進階欄位衍生。
- `statcast.py` 處理 pitch-level extraction 與 statcast 指標計算。
- `builder.py` 把多層級、多球隊資料整成前端真正需要的顯示結構（含跨等級 `_combine_*`）。

### 4. 模板輸出
- `jinja_env.py` 提供模板環境、filters 與 URL/absolute_url helper。
- `builder.py` 使用 templates 將首頁與球員頁渲染到 `dist/`，並輸出 sitemap、robots、結構化資料與逐場 pitch log JSON。

### 5. 前端圖表資料
- `statcast.py` 產出 pitch plinko、pitch movement、vs pitch types 等圖表資料。
- `builder.py` 再將不同層級資料整併成 `_combined` 與前端可直接嵌入的 JSON payload。

---

## 模組依賴關係摘要

- `sync.py`
  - 依賴 `api.py` 抓資料
  - 依賴 `helpers.py` 做型別轉換、JSON 轉換與 roster 狀態分類
  - 依賴 `statcast.py` 提取 pitches 與計算 statcast

- `builder.py`
  - 依賴 `helpers.py` 做 career / season / year-group 聚合與 roster 狀態分類
  - 依賴 `jinja_env.py` 建立模板環境
  - 依賴 `statcast.py` 生成 pitch-level 展示資料（movement chart、pitch 展開）

- `jinja_env.py`
  - 幾乎不依賴其他站內模組，主要是渲染層共用基礎設施

- `helpers.py`
  - 為其他模組提供通用資料處理、roster 分類與統計函式

- `api.py`
  - 專注外部 API 層，不依賴其他 `site_builder` 模組

- `statcast.py`
  - 專注 pitch-level 運算與展示資料整理，供 `sync.py` 與 `builder.py` 使用
</content>
</invoke>

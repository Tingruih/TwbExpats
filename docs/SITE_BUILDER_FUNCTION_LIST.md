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
  - MLB Stats API 根網址。
  - 所有主要 REST endpoint 都以它為基底。
- `TIMEOUT`
  - 預設 HTTP timeout 秒數。
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
  - 取得單場比賽完整 live feed JSON。
  - 提供 `statcast.py` 的 pitch extraction 使用。

- `sport_obj_to_abbr(sport: dict) -> str`
  - 將 API 的 `sport` 物件轉成站內使用的 level 簡稱。
  - 先用 id 對照，失敗再退回 name 對照。

- `get_game_sport_level(game_pk: int) -> str`
  - 只抓單場比賽的 sport level。
  - 用 fields-filtered endpoint 減少 payload，主要給歷史 game log backfill 使用。

- `get_player_sabermetrics(mlb_id: int, years: Optional[list[int]] = None) -> list`
  - 取得 `sabermetrics` 類型資料。
  - 主要用在 FIP、xFIP、WAR 等 MLB-only 欄位補寫。

- `get_player_expected_stats(mlb_id: int, years: Optional[list[int]] = None, group: str = "pitching") -> list`
  - 取得 `expectedStatistics` 類型資料，例如 xBA、xSLG、xwOBA。
  - 只打 MLB endpoint，因為 MiLB endpoint 目前不會回有效 expected stats。

- `parse_roster_from_file(filepath: str) -> list`
  - 讀取 `roster.json`。
  - 回傳 `players` 陣列，提供同步與 statcast pipeline 建立球員清單。

---

## `site_builder/builder.py`

### 模組用途
從 SQLite 載入球員、球季、逐場與 statcast 資料，經過整併與整理後，套用 Jinja2 模板輸出靜態網站 HTML。

### 常數 / 變數
- `_PROJECT_ROOT`
  - 專案根目錄 `Path`。
  - 用來定位 `src/static`、`data/headshots` 等資源。
- `_BAT_SIDE_SPLITS`
  - 投手面對打者側別的 split 定義。
  - 給 arsenal / outcomes / usage by count 的跨層級合併使用。
- `_COUNT_USAGE_BUCKETS`
  - 球數情境分群定義。
  - 例如 `early`、`pitcher_ahead`、`pitcher_behind`、`two_strikes`。
- `_PLINKO_COUNTS`
  - Pitch Plinko 節點清單。
  - 定義會出現在圖上的所有 count 狀態。
- `_PLINKO_EDGES`
  - Pitch Plinko 連線清單。
  - 定義合法的 count-to-count 轉移。

### Classes
- 無。

### Functions
- `_ratio(num: int, den: int) -> float | None`
  - 安全除法 helper。
  - 分母為 0 時回傳 `None`，否則回傳四位小數。

- `_is_unknown_pitch_type(pitch_type: str | None, pitch_name: str | None = None) -> bool`
  - 判斷球種是否屬於未知 placeholder。
  - 用來在建站整併階段排除 `UN` / `UNKNOWN` 類型。

- `_combine_pitch_type_data(entries: list[dict], sc_key: str, rate_fields: list[str], include_pct: bool = False) -> list[dict]`
  - 球種資料通用合併器。
  - 將多個 level 的球種資料按 `count` 做加權平均，並正確處理 `put_away_pct` 的兩好球權重。

- `_combine_vs_pitch_types(entries: list[dict]) -> list[dict]`
  - 專門整併打者 `vs_pitch_types`。
  - 用在同一年跨等級的 `_combined` 顯示列。

- `_combine_pitch_outcomes(entries: list[dict]) -> list[dict]`
  - 專門整併投手 `pitch_outcomes`。
  - 會保留每種 pitch type 的 outcome rate 與計數。

- `_combine_pitch_arsenal(entries: list[dict]) -> list[dict]`
  - 專門整併投手 `pitch_arsenal`。
  - 合併速度、位移、轉速、extension 與各種 pitch-level rate。

- `_combine_pitch_usage_by_count(entries: list[dict]) -> dict`
  - 合併不同層級的 `pitch_usage_by_count`。
  - 對每個球數情境直接加總 pitch count，再重新計算每種球的比例。

- `_combine_pitcher_bat_side_splits(entries: list[dict]) -> dict`
  - 合併投手面對 `all / L / R` 打者的 split statcast 資料。
  - 讓跨層級球季也能正確顯示打者側別分析。

- `_combine_pitch_plinko(entries: list[dict]) -> dict`
  - 合併多個 level 的 Pitch Plinko 節點、連線與球種分布。
  - 會先加總 raw count，再重算 split/node 內的比例。

- `_combine_pitch_movement(entries: list[dict]) -> dict`
  - 合併跨等級的 pitch movement chart 資料。
  - 目標是把不同 level 的點集壓成前端可直接消化的單一圖表資料結構。

- `_combine_statcast_dicts(entries: list[dict]) -> dict`
  - 把多層級 statcast summary 合成 `_combined` 列。
  - 依欄位性質選擇 `total_pitches`、`bbe`、`pa_count` 等不同權重來源，並把 pitch-level 子結構一併整併。

- `_prefetch_headshots(mlb_ids: list, cache_dir: Path, dest_dir: Path) -> None`
  - 預抓球員頭像到本地 cache，再複製到輸出目錄。
  - 減少前端首次載入時對 MLB CDN 的依賴。

- `_pick_display_stat(stats_current, player)`
  - 從同一年多筆 stat row 中，挑出要顯示在 index / hero 的那一筆。
  - 優先順序是：當前球隊、當前層級、再退回最高層級有出賽的 row。

- `_load_player_bundle(cur, player_row: sqlite3.Row)`
  - 從 SQLite 一次載入單一球員完整資料包。
  - 包含 player profile、season stats、fielding、game logs、已儲存的 statcast JSON。

- `build_static_site(db_path: str, year: int, output_dir: str, base_url: str = "/") -> None`
  - 靜態網站主入口。
  - 會建立輸出資料夾、複製靜態資源、載入 DB、渲染首頁與所有球員頁、輸出 `404.html` 與 `.nojekyll`。

---

## `site_builder/helpers.py`

### 模組用途
集中放置共用工具：安全型別轉換、JSON 序列化、日期與單位轉換、球季/生涯彙總，以及進階統計衍生欄位計算。

### 常數 / 變數
- `SPORT_LEVEL_ORDER`
  - 站內統一使用的等級排序表。
  - 用來決定 MLB、AAA、AA、A+、A… 在 UI 與資料整併時的優先順序。
- `DEFAULT_SEASON_YEAR`
  - 預設球季年份。
  - 來自環境變數；若未設定則使用 `2026`。
- `_COUNTING_FIELDS`
  - 聚合時計入加總的欄位名單。
  - 橫跨 hitting、pitching 與一些 advanced counting stats。
- `_HEIGHT_RE`
  - 身高字串解析用 regex。
  - 例如把 `6'2"` 之類格式轉成英尺英吋。

### Classes
- `Obj`
  - `dict` 的薄包裝。
  - 提供 `obj.key` 與 `obj["key"]` 兩種存取方式，方便模板與資料處理共用。

### Functions
- `safe_float(value: Any, default=None)`
  - 安全轉成 `float`。
  - 失敗時回傳 `default`，避免 API 髒值讓同步流程中斷。

- `safe_int(value: Any, default=None)`
  - 安全轉成 `int`。
  - 用途與 `safe_float` 類似。

- `loads_json(text: Any, default: Any)`
  - JSON 字串解析器。
  - 支援原本就是 `dict/list` 的情況，失敗時回傳 `default`。

- `loads_json_dict(text: Any) -> dict`
  - 專門把 JSON 內容轉為 `dict`。
  - 失敗時保證回傳 `{}`。

- `loads_json_list(text: Any) -> list`
  - 專門把 JSON 內容轉為 `list`。
  - 失敗時保證回傳 `[]`。

- `dumps_json(value: Any) -> str`
  - 將 Python 結構序列化為 JSON 字串。
  - 使用緊湊 separators，減少 DB 與輸出檔案大小。

- `parse_date(text: Optional[str])`
  - 把 ISO 字串轉成 `datetime.date`。
  - 若格式不合法則回傳 `None`。

- `ip_to_outs(ip_value) -> int`
  - 將棒球小數局數轉為 out 數。
  - 例如 `7.2` 代表 7 局 2 出局，實際上是 23 outs。

- `outs_to_ip(outs: int)`
  - 將 outs 數轉回棒球顯示用局數格式。
  - 例如 23 outs 轉為 `7.2`。

- `height_to_cm(height_str)`
  - 把英尺英吋字串轉為公分。
  - 用在球員資料頁顯示。

- `lbs_to_kg(weight_lbs)`
  - 把磅數轉為公斤。
  - 用在球員資料頁顯示。

- `calc_obp(hits, bb, hbp, ab, sac_flies)`
  - 計算 OBP。
  - 給彙總後沒有 API 現成欄位的 row 使用。

- `has_appearance(stat) -> bool`
  - 判斷某 row 是否真的有出賽。
  - 只要 GP、PA、AB、BF 或 IP 任一成立，就視為有效 row。

- `_sum_counting(stats, result)`
  - 對 `_COUNTING_FIELDS` 逐欄加總。
  - 聚合函式的第一階段核心。

- `_compute_rate_stats(agg)`
  - 根據聚合後的 counting stats 補算 rate stats。
  - 例如 `AVG`、`OBP`、`SLG`、`OPS`、`ERA`、`WHIP`。

- `_aggregate_stats(stats)`
  - 聚合多筆 stat row 的通用流程。
  - 會先加總 counting stats，再處理 IP 與 rate stats。

- `compute_career(stats, level_filter=None)`
  - 計算生涯累計資料。
  - 支援只算 MLB、只算 MiLB 或全部。

- `compute_season_combined(stats, year)`
  - 計算單一球季跨隊合併 row。
  - 用在同一年轉隊、升降級時的總計顯示。

- `_fmt_avg(value)`
  - 把小數格式化成棒球慣用打擊率字串。
  - 例如 `0.333` 轉成 `.333`。

- `_compute_advanced_stats(s)`
  - 依現有欄位補齊衍生進階統計。
  - 涵蓋打者與投手，例如 `ISO`、`BABIP`、`K%`、`BB%`、`P/PA`、`GO/AO` 等。

- `annotate_computed_stats(all_stats)`
  - 對整份 stat row 清單逐筆套用 `_compute_advanced_stats`。
  - 讓前端模板能直接吃到完整欄位。

- `compute_year_groups(all_stats)`
  - 把球季資料整理成「按年份分組」的結構。
  - 每個年份同時保留 summary row 與 detail rows，給前端可展開的 table 使用。

---

## `site_builder/jinja_env.py`

### 模組用途
建立 Jinja2 Environment，註冊模板 filters 與全域 helper，讓靜態網站渲染時有一致的格式化與 URL 生成功能。

### 常數 / 變數
- `_PROJECT_ROOT`
  - 專案根目錄路徑。
  - 用來推導模板路徑。
- `_TEMPLATE_DIR`
  - 預設模板目錄路徑。
  - 若沒有外部指定，就從這裡載入 `.j2` 模板。

### Classes
- 無。

### Functions
- `floatformat(value, digits=2)`
  - 將數字格式化成固定小數位。
  - 對 `None` 或錯誤值回傳 `-`。

- `default_if_none(value, fallback="-")`
  - 值為 `None` 時回傳 fallback。
  - 給模板避免到處寫 if/else。

- `num_dash(value)`
  - 顯示數字；若為空值則顯示 `-`。

- `slice_prefix(value, n)`
  - 取字串前 `n` 個字元。
  - 常用於姓名縮寫或短標籤。

- `tojson_safe(value)`
  - 轉 JSON 並標記為 HTML safe。
  - 主要讓前端 `<script type="application/json">` 內嵌資料。

- `pct_fmt(value, digits=1)`
  - 將 `0.xxx` 類型的小數格式化為百分比字串。
  - 使用 `Decimal + ROUND_HALF_UP`，避免浮點四捨五入偏差。

- `_make_url_helpers(base_url: str)`
  - 產生 `player_url()` 與 `static_url()` 兩個 helper。
  - 讓模板依 `base_url` 自動輸出正確網址。

- `create_jinja_env(template_dir=None, base_url="/")`
  - 建立完整設定好的 Jinja2 environment。
  - 會註冊 filters、全域 URL helper，以及 normalize `base_url`。

---

## `site_builder/statcast.py`

### 模組用途
處理 pitch-level 資料提取、分類、指標計算與前端展示資料整形。包含打者/投手 statcast summary、pitch movement、spray、pitch plinko、FIP 與 xWPCT 等公式。

### 常數 / 變數
- `SWING_CODES`
  - 視為 swing 的結果代碼集合。
- `WHIFF_CODES`
  - 視為 whiff 的結果代碼集合。
- `CALLED_STRIKE_CODES`
  - 視為 called strike 的結果代碼集合。
- `_W`
  - 各年份 wOBA 權重表。
- `_WOBA_FALLBACK`
  - 當年份不在表內時的 fallback 權重。
- `WOBA_EVENT_MAP`
  - `pa_event -> wOBA 權重鍵值` 對照。
- `FIP_CONSTANTS`
  - `(sport_level, year) -> FIP constant`。
- `LEAGUE_RA9`
  - 各 level 用於 xWPCT 的聯盟 RA/9 基準。
- `_NON_PA_EVENTS`
  - 不應被視為正式 plate appearance outcome 的事件集合。
- `_BAT_SIDE_SPLITS`
  - 投手面對打者側別的 split 定義。
- `_COUNT_USAGE_BUCKETS`
  - 球數情境分類定義。
- `_PLINKO_COUNTS`
  - Pitch Plinko 節點定義。
- `_PLINKO_EDGES`
  - Pitch Plinko 邊定義。
- `_BATTER_PLINKO_SPLITS`
  - 打者 Plinko 的 split 規則（`vs LHP` / `vs RHP`）。
- `_PITCHER_PLINKO_SPLITS`
  - 投手 Plinko 的 split 規則（`vs LHB` / `vs RHB`）。
- `_BATTER_PLINKO_SKIP_TYPES`
  - 打者 Plinko 中要略過的球種，例如 position player pitching 產生的 `EP` / `FA`。
- `_GB_TRAJECTORIES`
  - 視為 ground-ball 的 trajectory 集合。
- `_LD_TRAJECTORIES`
  - 視為 line-drive 的 trajectory 集合。
- `_FB_TRAJECTORIES`
  - 視為 fly-ball 的 trajectory 集合。
- `_PU_TRAJECTORIES`
  - 視為 popup 的 trajectory 集合。
- `_AIR_TRAJECTORIES`
  - air-ball 類 trajectory 合集。
- `_PULL_AIR_TRAJECTORIES`
  - 用於 pull-air 類型計算的 trajectory 合集。
- `_BATTED_BALL_RATE_DIGITS`
  - batted-ball 類 rate 的 rounding 精度。
- `_GAMEDAY_HOME_X`
  - Gameday spray chart 的 home plate X 基準。
- `_GAMEDAY_HOME_Y`
  - Gameday spray chart 的 home plate Y 基準。
- `_GAMEDAY_SPRAY_CORRECTION`
  - spray angle 修正係數。
- `_GAMEDAY_LEFT_FIELD_THRESHOLD_DEG`
  - 左外野判定角度門檻。
- `_GAMEDAY_RIGHT_FIELD_THRESHOLD_DEG`
  - 右外野判定角度門檻。
- `_HIT_LOCATION_ZONE`
  - `hit_location -> 大致落點區域` 對照，用於 fallback spray 分類。

### Classes
- 無。

### Functions

#### 資料提取與前處理
- `extract_pitch_logs(game_data: dict, player_id: int, role: str) -> list[dict]`
  - 從單場 live feed 提取球員逐球資料。
  - 會依 `pitcher` 或 `batter` 身分過濾，並產出 pitch-level 結構供快取與後續 statcast 計算使用。

- `_ensure_pre_strikes(pitches: list[dict]) -> None`
  - 回填舊資料缺少的 `pre_balls` / `pre_strikes`。
  - 讓新舊 cache 都能共用同一套計算邏輯。

#### 分類函式
- `_is_swing(p: dict) -> bool`
  - 判斷這顆球是否屬於 swing。

- `_is_whiff(p: dict) -> bool`
  - 判斷這顆球是否屬於揮空。

- `_is_called_strike(p: dict) -> bool`
  - 判斷是否為主審判定好球。

- `_is_in_zone(p: dict) -> bool`
  - 判斷球是否在 zone 1-9。

- `_is_out_of_zone(p: dict) -> bool`
  - 判斷球是否在 zone 11-14。

- `_is_barrel(ev: Optional[float], la: Optional[float]) -> bool`
  - 依 EV 與 LA 判斷是否為 barrel。

- `_is_sweet_spot(la: Optional[float]) -> bool`
  - 判斷 launch angle 是否落在 sweet spot 範圍。

#### 通用數值 helper
- `_ratio(num, den, digits=3)`
  - 安全除法並回傳四捨五入結果。

- `_mean(values)`
  - 計算非 `None` 值的平均數。

- `_mean_round(values, digits=1)`
  - 計算平均數後再 round。

- `_float_or_none(value) -> Optional[float]`
  - 嘗試轉 float，失敗回傳 `None`。

- `_is_unknown_pitch_type(pitch_type: Optional[str], pitch_name: Optional[str] = None) -> bool`
  - 判斷球種是否屬於未知 placeholder。

- `_filter_known_pitch_events(pitches: list[dict]) -> list[dict]`
  - 過濾掉未知球種事件。

- `_pre_count_tuple(p: dict) -> Optional[tuple[int, int]]`
  - 取出投球前球數 tuple。

- `_post_count_tuple(p: dict) -> Optional[tuple[int, int]]`
  - 取出投球後球數 tuple。

- `_count_label(count: tuple[int, int]) -> str`
  - 把 `(balls, strikes)` 轉為 `"B-S"` 字串。

- `_empty_plinko_nodes() -> list[dict]`
  - 建立空白的 Plinko nodes 結構。

- `_empty_plinko_edges() -> list[dict]`
  - 建立空白的 Plinko edges 結構。

#### Plinko / movement / spray 圖表資料
- `_compute_pitch_plinko(pitches: list[dict], split_field: str, split_specs: tuple[tuple[str, str], ...], skip_types: Optional[set[str]] = None) -> dict`
  - 從逐球資料計算 Pitch Plinko 的 split、node、edge 與 node 內球種分布。
  - 是前端 Plinko 圖的主資料來源。

- `compute_pitch_movement_chart(pitches: list[dict], max_points: Optional[int] = 700) -> dict`
  - 將逐球資料轉成 pitch movement chart 用的輕量點集。
  - 會控制點數上限，避免前端圖表過重。

- `_spray_direction_from_location(p: dict) -> Optional[str]`
  - 依 `hit_location` 做簡化 spray 分類 fallback。

- `_spray_direction_from_coordinates(p: dict) -> Optional[str]`
  - 依 Gameday hit coordinates 計算更精確的 spray 方向。

- `_compute_spray(in_play: list[dict]) -> dict`
  - 綜合 spray direction 計算 `pull / straight / oppo` 比例。

#### 共享聚合流程
- `_aggregate_pitches(pitches: list[dict]) -> dict`
  - 把逐球資料切成 swing、whiff、called、in-zone、in-play 等分類集合。
  - 是 hitter / pitcher statcast 計算共同依賴的核心聚合器。

- `_compute_woba(pa_final: list[dict], woba_w: dict) -> tuple[float, int]`
  - 從 PA 結束球計算 wOBA numerator 與 denominator。

- `_discipline_metrics(agg: dict) -> dict`
  - 由 `_aggregate_pitches()` 的結果組出 discipline metrics。

- `_batted_ball_metrics(agg: dict, sport_level: str = "") -> dict`
  - 由 `_aggregate_pitches()` 的結果組出 batted-ball metrics。

#### 投手 statcast
- `compute_pitcher_statcast(pitches: list[dict], year: Optional[int] = None, sport_level: str = "") -> dict`
  - 投手端 statcast 主入口。
  - 計算 season-level 的 discipline、batted-ball、pitch arsenal、pitch outcomes、usage by count、pitch plinko 與 pitch movement 等資料。

- `_compute_pitch_arsenal_pitcher(pitches: list[dict], year: Optional[int] = None) -> list[dict]`
  - 依球種整理投手 arsenal 資料。
  - 包含速度、位移、轉速、release 與 pitch-level outcome rate。

- `_compute_pitch_outcomes_pitcher(pitches: list[dict], year: Optional[int] = None) -> list[dict]`
  - 依球種整理投手 outcome summary。
  - 聚焦 strike、CSW、AVG against、wOBA、barrel%、hard-hit% 等。

- `_compute_pitch_usage_by_count_pitcher(pitches: list[dict]) -> dict`
  - 計算不同球數情境下，各球種使用率。

- `_compute_pitcher_bat_side_splits(pitches: list[dict], year: Optional[int] = None) -> dict[str, dict]`
  - 依 `all / L / R` 打者側別建出投手 split 資料。

#### 打者 statcast
- `compute_batter_statcast(pitches: list[dict], year: Optional[int] = None, sport_level: str = "") -> dict`
  - 打者端 statcast 主入口。
  - 計算 swing / contact / batted-ball、spray、vs_pitch_types、pitch plinko 與 pitch movement 等資料。

- `_compute_vs_pitch_types_batter(pitches: list[dict], year: Optional[int] = None) -> list[dict]`
  - 依球種整理打者面對不同球種的結果。
  - 包含 strike%、zone%、swing%、whiff%、AVG、wOBA、barrel%、hard-hit% 等。

#### 公式與展示 helper
- `get_woba_weights(year: Optional[int] = None) -> dict`
  - 取得指定年份的 wOBA 權重。

- `compute_fip(hr, bb, hbp, k, ip, sport_level: str, year: int, c_fip: Optional[float] = None) -> Optional[float]`
  - 計算 FIP。
  - 若找不到對應常數，會依規則 fallback。

- `compute_xwpct(fip: Optional[float], sport_level: str) -> Optional[float]`
  - 依 FIP 與聯盟 RA/9 推估 xWPCT。

- `summarize_pitch_for_display(p: dict) -> dict`
  - 把完整 pitch dict 投影成逐場展開表格需要的輕量欄位。

---

## `site_builder/sync.py`

### 模組用途
負責資料同步與 SQLite 寫入，包含完整同步、快速更新，以及 statcast pitch-level 同步與聚合回寫。

### 常數 / 變數
- `logger`
  - 模組 logger。
  - 用來記錄同步過程中的 API / DB 錯誤。
- `MAX_WORKERS`
  - 平行抓取的最大 worker 數。
  - 目前用於球員資料與比賽 play-by-play 的平行請求。

### Classes
- 無。

### Functions

#### 資料庫 schema 與 row I/O
- `_init_db(conn: sqlite3.Connection) -> None`
  - 初始化 SQLite schema。
  - 建立 `players`、`season_stats`、`game_logs`、`playbyplay_processed`，並做必要的 forward migration。

- `_load_season_row(cur, mlb_id: int, year: int, team_name: str) -> dict`
  - 讀取單一 `season_stats` row。
  - 若不存在則回傳空白預設結構。

- `_save_season_row(cur, mlb_id, year, team_name, league_name, sport_level, stat_json, fielding_json) -> None`
  - 以 upsert 方式寫入 `season_stats`。
  - 確保同一球員 / 年度 / 球隊只保留一列。

#### API 欄位對應
- `_apply_yearbyyear_fields(stat_doc: dict, group_name: str, stat: dict) -> None`
  - 把 API `yearByYear` 欄位映射進站內欄位。
  - 依 hitting / pitching / fielding 分別寫入對應 key。

- `_apply_advanced_fields(stat_doc: dict, group_name: str, stat: dict) -> None`
  - 把 API `seasonAdvanced` 欄位映射進站內欄位。
  - 只補充 advanced 欄位，不重複處理基礎統計。

#### 球員同步主流程
- `_fetch_player_data(pconf: dict, year: int, fetch_all_years: bool = True) -> Optional[dict]`
  - 平行抓取單一球員所需 API 資料。
  - 不直接寫 DB，只組成 bundle 給下一階段使用。

- `_write_player_to_db(conn: sqlite3.Connection, bundle: dict, year: int) -> None`
  - 將 `_fetch_player_data()` 產出的 bundle 寫入 DB。
  - 涵蓋 player profile、season stats、advanced、fielding、game logs 與 next game snapshot。

- `_run_pipeline(db_path: str, roster_file: str, year: int, only_player: Optional[int] = None, fetch_all_years: bool = True, mode_label: str = "Sync") -> None`
  - 共用的同步主流程。
  - 先平行抓資料，再序列寫入 DB；`sync_database()` 與 `update_database()` 都透過它執行。

- `sync_database(db_path: str, roster_file: str, year: int, only_player: Optional[int] = None) -> None`
  - 完整同步入口。
  - 會抓所有歷史年份的 game log，適合初始化或完整重建資料庫。

- `update_database(db_path: str, roster_file: str, year: int, only_player: Optional[int] = None) -> None`
  - 快速更新入口。
  - 只刷新當季 game log，但仍會更新球員檔與球季統計。

#### Statcast 同步輔助
- `_build_roster_map(roster_file: str) -> dict`
  - 從 roster 設定建立 `{mlb_id: player_config}` 對照。

- `_fetch_and_extract_game(game_pk: int, players_in_game: list[tuple[int, str]]) -> tuple[dict[int, list[dict]], str]`
  - 抓取單場比賽 live feed，並替該場涉及的 roster player 提取 pitch logs。
  - 會一併回傳該場 sport level。

- `_pitches_need_hit_coord_backfill(pitches: list[dict]) -> bool`
  - 判斷某批 pitch 是否缺少 hit coordinates。
  - 用於舊 cache 與新資料結構兼容時的 backfill 判斷。

- `_load_all_pitches_for_player(cur, mlb_id: int) -> dict[tuple, list[dict]]`
  - 從 `game_logs.pitches_json` 載入單一球員所有 pitch-level cache。
  - 會依 `(year, sport_level)` 分組，供 statcast 重算使用。

- `_merge_statcast_into_season(cur, mlb_id: int, year: int, position: str, statcast_data: dict, sport_level: str = "", sabermetrics: Optional[dict] = None, expected_stats: Optional[dict] = None) -> None`
  - 把重算完成的 statcast / sabermetrics / expected stats 回寫到 `season_stats.stat_json`。
  - 會盡量精準寫到對應的 sport level row，避免跨等級污染。

- `sync_statcast(db_path: str, roster_file: str, year: int, only_player: Optional[int] = None) -> None`
  - Statcast 專用同步入口。
  - 負責補抓 play-by-play、提取 pitches、更新 `game_logs.pitches_json`，再重算整季 statcast summary 並回寫 DB。

---

## site_builder 內部資料流總覽

### 1. 外部資料抓取
- `api.py` 負責呼叫 MLB Stats API。
- `sync.py` 以 roster 為起點，平行抓回 player profile、season stats、advanced stats、game logs、next game 與 play-by-play。

### 2. 資料落地
- `sync.py` 將資料寫入 SQLite：
  - `players`
  - `season_stats`
  - `game_logs`
  - `playbyplay_processed`

### 3. 統計與聚合
- `helpers.py` 處理一般球季、生涯與進階欄位衍生。
- `statcast.py` 處理 pitch-level extraction 與 statcast 指標計算。
- `builder.py` 負責把多層級、多球隊資料整成前端真正需要的顯示結構。

### 4. 模板輸出
- `jinja_env.py` 提供模板環境、filters 與 URL helper。
- `builder.py` 使用 templates 將首頁與球員頁渲染到 `dist/`。

### 5. 前端圖表資料
- `statcast.py` 產出 pitch plinko、pitch movement、vs pitch types 等圖表資料。
- `builder.py` 再將不同層級資料整併成 `_combined` 與前端可直接嵌入的 JSON payload。

---

## 模組依賴關係摘要

- `sync.py`
  - 依賴 `api.py` 抓資料
  - 依賴 `helpers.py` 做型別轉換與 JSON 轉換
  - 依賴 `statcast.py` 提取 pitches 與計算 statcast

- `builder.py`
  - 依賴 `helpers.py` 做 career / season / year-group 聚合
  - 依賴 `jinja_env.py` 建立模板環境
  - 依賴 `statcast.py` 生成 pitch-level 展示資料（例如 movement chart）

- `jinja_env.py`
  - 幾乎不依賴其他站內模組，主要是渲染層共用基礎設施

- `helpers.py`
  - 為其他模組提供通用資料處理與統計函式

- `api.py`
  - 專注外部 API 層，不依賴其他 `site_builder` 模組

- `statcast.py`
  - 專注 pitch-level 運算與展示資料整理，供 `sync.py` 與 `builder.py` 使用
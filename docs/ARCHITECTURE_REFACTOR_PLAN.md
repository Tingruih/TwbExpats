# Architecture Refactor Plan

> 目的：整理 `site_builder/` 內所有 Python function 的職責歸屬，規劃新的檔案架構，找出重複功能與常數治理方式，並檢查 `src/` 目錄的前端檔案職責是否過度混雜。

---

## Refactor 原則

1. `api` 只處理 MLB Stats API HTTP 邊界，不讀寫本機檔案、不做 DB 寫入、不做統計計算。
2. `db` 只處理 SQLite schema、migration、CRUD，不抓 API、不產生 HTML context。
3. `sync` 只負責 orchestration：決定流程順序、平行化、錯誤隔離與呼叫 API/DB/計算模組。
4. `stats` / `statcast` 只做純計算，盡量輸入 dict/list、輸出 dict/list，不依賴 Jinja 或 SQLite cursor。
5. `build` / `presentation` 只負責模板 context、靜態資產、URL、格式化與 HTML 顯示資料。
6. 常數分為「穩定 domain constants」、「年度可更新 constants」、「展示 labels」，避免混在計算模組或 builder 裡。
7. 重構時先搬動低風險 pure functions 與 constants，再拆 DB / sync pipeline，最後拆 frontend template 與 JS。

---

## 建議的新 Python 檔案架構

```text
site_builder/
  __init__.py
  config.py
  models.py

  constants/
    __init__.py
    levels.py
    stat_fields.py
    statcast.py
    run_environment.py

  utils/
    __init__.py
    dates.py
    json.py
    numbers.py
    units.py

  api/
    __init__.py
    client.py
    players.py
    stats.py
    games.py
    schedule.py

  db/
    __init__.py
    schema.py
    players.py
    season_stats.py
    game_logs.py

  mappings/
    __init__.py
    mlb_stats.py

  roster.py

  stats/
    __init__.py
    innings.py
    rates.py
    derived.py
    season.py
    pitching.py
    woba.py

  statcast/
    __init__.py
    extract.py
    classify.py
    aggregate.py
    batted_ball.py
    pitch_types.py
    plinko.py
    movement.py
    combine.py

  presentation/
    __init__.py
    filters.py
    urls.py
    pitchlog.py
    selectors.py

  build/
    __init__.py
    assets.py
    loaders.py
    context.py
    pages.py

  sync/
    __init__.py
    basic.py
    fetch.py
    write.py
    statcast_sync.py
    statcast_merge.py
```

### 架構邊界

| 新模組 | 職責 | 不應做的事 |
|---|---|---|
| `config.py` | runtime config，例如 season、worker 數、timeout 預設 | 放棒球公式常數 |
| `constants/*` | 可被多個模組共用的 domain constants | 執行 HTTP、DB query |
| `utils/*` | JSON、日期、數字、單位等通用工具 | 棒球統計公式 |
| `api/*` | MLB HTTP endpoint wrapper | 本機 roster 檔案解析、DB 寫入 |
| `db/*` | schema、migration、query、upsert | API 呼叫、statcast 計算 |
| `mappings/*` | MLB API 欄位名轉本地欄位名 | DB cursor 操作 |
| `stats/*` | season/career/advanced/FIP/wOBA 純計算 | Jinja 格式化 |
| `statcast/*` | pitch-level extraction、classification、aggregation、chart payload | HTML context 建立 |
| `presentation/*` | Jinja filters、URL helper、display projection | 修改資料庫 |
| `build/*` | 讀 DB、組 context、寫 static files | 統計公式、API fetch |
| `sync/*` | sync orchestration、平行化、錯誤隔離 | 低階 SQL schema 定義 |

---

## `site_builder/api.py` function 搬遷規劃

| 現有 function / constant | 目前職責 | 建議位置 | 說明 |
|---|---|---|---|
| `BASE_URL` | MLB Stats API base URL | `api/client.py` 或 `config.py` | 若未來支援 mock/base URL override，放 `config.py` 更好。 |
| `TIMEOUT` | API timeout | `config.py` | 與 `MAX_WORKERS` 同屬 runtime config。 |
| `_SPORT_ID_MAP` | sport id → level abbreviation | `constants/levels.py` | 與 `SPORT_LEVEL_ORDER`、`_SPORT_NAME_TO_ABBR` 合併。 |
| `_SPORT_NAME_TO_ABBR` | sport name → level abbreviation | `constants/levels.py` | 統一 sport level 單一來源。 |
| `get_player_profile()` | player profile / transaction / current team API | `api/players.py` | 保留 HTTP boundary；team level mapping 改呼叫 `level_from_sport_id()`。 |
| `get_player_stats()` | yearByYear stats API | `api/stats.py` | MLB/MiLB endpoint fallback 應在這裡修正。 |
| `get_player_advanced_stats()` | seasonAdvanced API | `api/stats.py` | 與其他 stats endpoints 放同檔。 |
| `get_game_logs()` | gameLog stats API | `api/stats.py` 或 `api/games.py` | 雖然是 game logs，但 endpoint 是 people stats；建議放 `api/stats.py`。 |
| `get_next_game()` | schedule API | `api/schedule.py` | UTC+8 formatting 可改交給 presentation，API 回 raw datetime。 |
| `get_game_play_by_play()` | live feed API | `api/games.py` | 只回 raw dict。 |
| `sport_obj_to_abbr()` | API sport object mapping | `constants/levels.py` | 這不是 HTTP 行為。 |
| `get_game_sport_level()` | lightweight live-feed sport lookup | `api/games.py` | 內部呼叫 `sport_obj_to_abbr()`。 |
| `get_player_sabermetrics()` | sabermetrics API | `api/stats.py` | MLB-only stats endpoint。 |
| `get_player_expected_stats()` | expectedStatistics API | `api/stats.py` | MLB-only expected stats endpoint。 |
| `parse_roster_from_file()` | 本機 roster JSON 解析 | `roster.py` | 不應放在 API client。 |

---

## `site_builder/helpers.py` function 搬遷規劃

| 現有 function / class / constant | 目前職責 | 建議位置 | 說明 |
|---|---|---|---|
| `SPORT_LEVEL_ORDER` | level sorting | `constants/levels.py` | 與 API sport id/name mapping 合併。 |
| `DEFAULT_SEASON_YEAR` | runtime default | `config.py` | 從 env 讀取屬於 config。 |
| `Obj` | dict attribute access | `models.py` | 若未來導入 dataclass / typed model，可從這裡替換。 |
| `_COUNTING_FIELDS` | career / season sum 欄位清單 | `constants/stat_fields.py` | 應和 API field mapping 放在同一 domain 區域。 |
| `safe_float()` | safe number conversion | `utils/numbers.py` | 通用工具。 |
| `safe_int()` | safe number conversion | `utils/numbers.py` | 通用工具。 |
| `loads_json()` | JSON parsing | `utils/json.py` | 通用工具。 |
| `loads_json_dict()` | JSON parsing to dict | `utils/json.py` | 通用工具。 |
| `loads_json_list()` | JSON parsing to list | `utils/json.py` | 通用工具。 |
| `dumps_json()` | compact JSON dump | `utils/json.py` | 通用工具。 |
| `parse_date()` | date parsing | `utils/dates.py` | 通用工具。 |
| `ip_to_outs()` | baseball IP → outs | `stats/innings.py` | 棒球 domain 公式。 |
| `outs_to_ip()` | outs → baseball IP | `stats/innings.py` | 棒球 domain 公式。 |
| `_HEIGHT_RE` | height parse regex | `utils/units.py` | 與 `height_to_cm()` 放一起。 |
| `height_to_cm()` | display unit conversion | `utils/units.py`，並註冊成 Jinja filter | builder 不需要塞 `height_cm` context。 |
| `lbs_to_kg()` | display unit conversion | `utils/units.py`，並註冊成 Jinja filter | 同上。 |
| `calc_obp()` | OBP formula | `stats/rates.py` | 純棒球 rate formula。 |
| `has_appearance()` | 判斷是否有出賽 | `stats/season.py` 或 `presentation/selectors.py` | 目前同時給 builder 用，仍屬 domain selector。 |
| `_sum_counting()` | aggregation helper | `stats/season.py` | 與 `_COUNTING_FIELDS` 一起。 |
| `_compute_rate_stats()` | aggregated rate stats | `stats/season.py` | season/career summary 專用。 |
| `_aggregate_stats()` | sum + rate aggregation | `stats/season.py` | `compute_career()` / `compute_season_combined()` 共用。 |
| `compute_career()` | career aggregation | `stats/season.py` | 純計算。 |
| `compute_season_combined()` | current-year combined row | `stats/season.py` | 應補 `_compute_advanced_stats()`。 |
| `_fmt_avg()` | baseball average display string | `presentation/filters.py` 或 `presentation/formatters.py` | 不應在計算層回傳字串。 |
| `_compute_advanced_stats()` | derived stat computation | `stats/derived.py` | 建議所有輸出維持 numeric，顯示交給 filter。 |
| `annotate_computed_stats()` | batch derived stat annotation | `stats/derived.py` | 純資料 enrichment。 |
| `compute_year_groups()` | by-year summary groups | `stats/season.py` | 介於 domain summary 與 presentation context，可先放 `stats/season.py`。 |

---

## `site_builder/jinja_env.py` function 搬遷規劃

| 現有 function / constant | 目前職責 | 建議位置 | 說明 |
|---|---|---|---|
| `_PROJECT_ROOT` | project path | `config.py` 或 `build/paths.py` | 多處需要路徑時統一。 |
| `_TEMPLATE_DIR` | template path | `build/paths.py` | 只跟 build/presentation 有關。 |
| `floatformat()` | numeric display filter | `presentation/filters.py` | Jinja filter。 |
| `default_if_none()` | fallback filter | `presentation/filters.py` | 可與 `num_dash()` 合併。 |
| `num_dash()` | fallback filter | `presentation/filters.py` | 重複度高。 |
| `slice_prefix()` | string filter | `presentation/filters.py` | Jinja filter。 |
| `tojson_safe()` | JSON-to-script filter | `presentation/filters.py` | 應改用 `htmlsafe_json_dumps()`。 |
| `pct_fmt()` | percentage display filter | `presentation/filters.py` | Jinja filter。 |
| `_make_url_helpers()` | URL factory | `presentation/urls.py` | `player_url()` / `static_url()` 可單測。 |
| `create_jinja_env()` | Jinja env assembly | `jinja_env.py` | 保留為 integration point，只負責註冊 filters/globals。 |

---

## `site_builder/statcast.py` function 搬遷規劃

| 現有 function / constant | 目前職責 | 建議位置 | 說明 |
|---|---|---|---|
| `SWING_CODES` | pitch result classification | `constants/statcast.py` | 與 whiff/called strike 同組。 |
| `WHIFF_CODES` | pitch result classification | `constants/statcast.py` | 同上。 |
| `CALLED_STRIKE_CODES` | pitch result classification | `constants/statcast.py` | 同上。 |
| `_W` | FanGraphs wOBA weights | `constants/run_environment.py` 或 `data/constants/woba_weights.json` | 年度可更新資料。 |
| `_WOBA_FALLBACK` | wOBA fallback | `stats/woba.py` | fallback policy 應靠 function 處理。 |
| `get_woba_weights()` | wOBA weights lookup | `stats/woba.py` | 回傳 value + fallback metadata 更好。 |
| `WOBA_EVENT_MAP` | MLB event → wOBA key | `constants/statcast.py` | classification constant。 |
| `FIP_CONSTANTS` | FIP C constants | `constants/run_environment.py` 或 `data/constants/fip_constants.json` | 年度可更新資料。 |
| `LEAGUE_RA9` | xWPCT league run environment | `constants/run_environment.py` | 年度/level 可更新。 |
| `_NON_PA_EVENTS` | non-PA events | `constants/statcast.py` | wOBA / AB denominator 共用。 |
| `_BAT_SIDE_SPLITS` | split specs + labels | `constants/statcast.py` 或 `presentation/labels.py` | key 與 label 應分離。 |
| `_COUNT_USAGE_BUCKETS` | count bucket definitions | `constants/statcast.py` | 與 builder 重複，必須單一來源。 |
| `_PLINKO_COUNTS` | Plinko nodes | `constants/statcast.py` | 與 builder 重複。 |
| `_PLINKO_EDGES` | Plinko edges | `constants/statcast.py` | 與 builder 重複。 |
| `_BATTER_PLINKO_SPLITS` | batter Plinko split specs | `constants/statcast.py` | key 與 label 可分離。 |
| `_PITCHER_PLINKO_SPLITS` | pitcher Plinko split specs | `constants/statcast.py` | 同上。 |
| `_BATTER_PLINKO_SKIP_TYPES` | Plinko pitch skip types | `constants/statcast.py` | 與 batter vs pitch type skip types 合併。 |
| trajectory constants | batted-ball classification | `constants/statcast.py` | `_GB_TRAJECTORIES` 等。 |
| Gameday constants | spray coordinate formula | `constants/statcast.py` | `_GAMEDAY_*`。 |
| `_HIT_LOCATION_ZONE` | hit location fallback map | `constants/statcast.py` | spray fallback map。 |
| `extract_pitch_logs()` | live-feed pitch extraction | `statcast/extract.py` | 僅處理 raw API → pitch dict。 |
| `_ensure_pre_strikes()` | legacy/backfill pre-count | `statcast/extract.py` | 與 extraction schema 同組。 |
| `_is_swing()` | classification helper | `statcast/classify.py` | 純 classification。 |
| `_is_whiff()` | classification helper | `statcast/classify.py` | 純 classification。 |
| `_is_called_strike()` | classification helper | `statcast/classify.py` | 純 classification。 |
| `_is_in_zone()` | zone classification | `statcast/classify.py` | 純 classification。 |
| `_is_out_of_zone()` | zone classification | `statcast/classify.py` | 純 classification。 |
| `_is_barrel()` | barrel definition | `statcast/batted_ball.py` | BBE formula。 |
| `_is_sweet_spot()` | launch-angle classification | `statcast/batted_ball.py` | BBE formula。 |
| `_ratio()` | safe ratio | `utils/numbers.py` 或 `stats/rates.py` | 與 builder 重複。 |
| `_mean()` | mean helper | `utils/numbers.py` | 通用。 |
| `_mean_round()` | mean helper | `utils/numbers.py` | 通用。 |
| `_float_or_none()` | safe float with finite check | `utils/numbers.py` | 與 `safe_float()` 可整合。 |
| `_is_unknown_pitch_type()` | pitch type validation | `statcast/pitch_types.py` | 與 builder 重複。 |
| `_filter_known_pitch_events()` | filter pitch list | `statcast/pitch_types.py` | pitch type helper。 |
| `_pre_count_tuple()` | pre-count helper | `statcast/classify.py` 或 `statcast/plinko.py` | 多個 statcast payload 共用。 |
| `_post_count_tuple()` | post-count helper | `statcast/classify.py` 或 `statcast/plinko.py` | Plinko edge 共用。 |
| `_count_label()` | count tuple label | `statcast/plinko.py` | Plinko/count display helper。 |
| `_empty_plinko_nodes()` | empty plinko payload | `statcast/plinko.py` | Plinko-specific。 |
| `_empty_plinko_edges()` | empty plinko payload | `statcast/plinko.py` | Plinko-specific。 |
| `_compute_pitch_plinko()` | Plinko data aggregation | `statcast/plinko.py` | Pure statcast chart payload。 |
| `compute_pitch_movement_chart()` | movement chart payload | `statcast/movement.py` | Pitch movement payload。 |
| `_spray_direction_from_location()` | spray fallback | `statcast/batted_ball.py` | 與 coordinate spray 放一起。 |
| `_spray_direction_from_coordinates()` | spray coordinates | `statcast/batted_ball.py` | 與 Gameday constants 放一起。 |
| `_compute_spray()` | spray counts | `statcast/batted_ball.py` | BBE aggregate helper。 |
| `_aggregate_pitches()` | base pitch aggregate | `statcast/aggregate.py` | pitcher/batter common aggregation。 |
| `_compute_woba()` | wOBA numerator/denominator | `stats/woba.py` | 可與 PA outcome helper 共用。 |
| `_discipline_metrics()` | plate discipline metrics | `statcast/aggregate.py` | Common statcast output。 |
| `_batted_ball_metrics()` | BBE metrics | `statcast/batted_ball.py` | BBE output。 |
| `compute_pitcher_statcast()` | pitcher season statcast | `statcast/aggregate.py` 或 `statcast/pitcher.py` | Public pure function。 |
| `_compute_pitch_arsenal_pitcher()` | pitcher arsenal table | `statcast/pitch_types.py` | Pitch-type table。 |
| `_compute_pitch_outcomes_pitcher()` | pitcher outcome table | `statcast/pitch_types.py` | Shares Put Away / AVG / wOBA logic。 |
| `_compute_pitch_usage_by_count_pitcher()` | count-bucket pitch usage | `statcast/pitch_types.py` | Uses centralized buckets。 |
| `_compute_pitcher_bat_side_splits()` | pitcher vs L/R splits | `statcast/pitch_types.py` | Table composition。 |
| `compute_batter_statcast()` | batter season statcast | `statcast/aggregate.py` 或 `statcast/batter.py` | Public pure function。 |
| `_compute_vs_pitch_types_batter()` | batter vs pitch type table | `statcast/pitch_types.py` | Shares PA outcome helper。 |
| `compute_fip()` | FIP formula | `stats/pitching.py` | Not Statcast-specific；需修正 IP 分母。 |
| `compute_xwpct()` | expected winning pct formula | `stats/pitching.py` | Uses run environment constants。 |
| `summarize_pitch_for_display()` | pitch log display projection | `presentation/pitchlog.py` | 這是前端 JSON projection，不是 statcast 計算。 |

---

## `site_builder/builder.py` function 搬遷規劃

| 現有 function / constant | 目前職責 | 建議位置 | 說明 |
|---|---|---|---|
| `_PROJECT_ROOT` | project path | `config.py` 或 `build/paths.py` | 和 Jinja path 統一。 |
| `_BAT_SIDE_SPLITS` | split specs | `constants/statcast.py` | 與 statcast 重複。 |
| `_COUNT_USAGE_BUCKETS` | count bucket labels | `constants/statcast.py` + `presentation/labels.py` | 與 statcast 不同步。 |
| `_PLINKO_COUNTS` | Plinko counts | `constants/statcast.py` | 與 statcast 重複。 |
| `_PLINKO_EDGES` | Plinko edges | `constants/statcast.py` | 與 statcast 重複。 |
| `_ratio()` | safe ratio | `utils/numbers.py` | 與 statcast 重複，digits 可參數化。 |
| `_is_unknown_pitch_type()` | pitch type validation | `statcast/pitch_types.py` | 與 statcast 重複。 |
| `_combine_pitch_type_data()` | per-level pitch-type weighted combine | `statcast/combine.py` | 統計合併，不是 build。 |
| `_combine_vs_pitch_types()` | combine batter vs pitch types | `statcast/combine.py` | 同上。 |
| `_combine_pitch_outcomes()` | combine pitcher outcomes | `statcast/combine.py` | 同上。 |
| `_combine_pitch_arsenal()` | combine pitch arsenal | `statcast/combine.py` | 同上。 |
| `_combine_pitch_usage_by_count()` | combine count usage | `statcast/combine.py` | 同上；應與 centralized buckets 對齊。 |
| `_combine_pitcher_bat_side_splits()` | combine pitcher splits | `statcast/combine.py` | 同上。 |
| `_combine_pitch_plinko()` | combine Plinko payloads | `statcast/combine.py` 或 `statcast/plinko.py` | nested `_new_split_bucket()` 可變 private helper。 |
| `_combine_pitch_movement()` | combine movement payloads | `statcast/combine.py` 或 `statcast/movement.py` | 和 `compute_pitch_movement_chart()` 放同 domain。 |
| `_combine_statcast_dicts()` | combine full statcast dict | `statcast/combine.py` | nested `_wsum()` / `_wpct()` 可變 private helpers。 |
| `_prefetch_headshots()` | download/copy image assets | `build/assets.py` | nested `_fetch_one()` 可變 `_fetch_headshot()`。 |
| `_pick_display_stat()` | choose current display stat | `presentation/selectors.py` 或 `build/context.py` | context selector。 |
| `_load_player_bundle()` | DB read model for player detail | `build/loaders.py` 或 `db/read_models.py` | 讀 SQLite + 轉 Obj，應離開 builder 主流程。 |
| `build_static_site()` | static build orchestration | `build/pages.py` 或保留 `builder.py` | 最後應只串接 assets、loaders、context、render。 |

---

## `site_builder/sync.py` function 搬遷規劃

| 現有 function / constant | 目前職責 | 建議位置 | 說明 |
|---|---|---|---|
| `MAX_WORKERS` | thread pool size | `config.py` | runtime config。 |
| `_init_db()` | schema + migrations | `db/schema.py` | SQL schema 不應在 sync orchestrator。 |
| `_load_season_row()` | season_stats read | `db/season_stats.py` | DB CRUD。 |
| `_save_season_row()` | season_stats upsert | `db/season_stats.py` | DB CRUD。 |
| `_apply_yearbyyear_fields()` | MLB API field mapping | `mappings/mlb_stats.py` | 把大 dict mapping 抽成 constants 會更好測。 |
| `_apply_advanced_fields()` | advanced API field mapping | `mappings/mlb_stats.py` | 同上。 |
| `_fetch_player_data()` | one-player API fetch bundle | `sync/fetch.py` | 不寫 DB，適合獨立測試。 |
| `_write_player_to_db()` | write fetched player bundle | `sync/write.py` + `db/*` | 目前同時做 profile、season、fielding、game log、next game。 |
| `_run_pipeline()` | sync/update common orchestration | `sync/basic.py` | public sync pipeline 的核心。 |
| `sync_database()` | full historical sync entry point | `sync/basic.py` | Public API。 |
| `update_database()` | daily update entry point | `sync/basic.py` | Public API。 |
| `_build_roster_map()` | roster config lookup | `roster.py` | 目前一行 function，可 inline 或擴充 validation。 |
| `_fetch_and_extract_game()` | live-feed fetch + extract per player | `sync/statcast_sync.py` 或 `statcast/extract.py` | 因含 API fetch 與 role fallback，放 statcast sync 較合理。 |
| `_pitches_need_hit_coord_backfill()` | cached pitch schema backfill check | `sync/statcast_sync.py` | 與 pitch cache migration 流程同組。 |
| `_load_all_pitches_for_player()` | load cached pitches grouped by year/level | `db/game_logs.py` | DB read helper。 |
| `_merge_statcast_into_season()` | merge statcast/saber/expected into season row | `sync/statcast_merge.py` | Orchestration + DB write，應拆小。 |
| `sync_statcast()` | statcast sync orchestration | `sync/statcast_sync.py` | Public API。 |

---

## 重複或高度相似功能

| 重複點 | 位置 | 建議 |
|---|---|---|
| `_ratio()` 重複 | `statcast.py:432`、`builder.py:71` | 合併為 `utils/numbers.safe_ratio(num, den, digits=3)`，呼叫端指定 digits。 |
| `_is_unknown_pitch_type()` 重複 | `statcast.py:463`、`builder.py:75` | 合併到 `statcast/pitch_types.py`。 |
| `_BAT_SIDE_SPLITS` 重複 | `statcast.py:98`、`builder.py:37` | 移至 `constants/statcast.py`，label 可由 `presentation/labels.py` 決定。 |
| `_COUNT_USAGE_BUCKETS` 重複且不同步 | `statcast.py:104`、`builder.py:43` | 單一來源。builder 目前多了 `all` bucket，但 statcast 不產生，造成 dead code。 |
| `_PLINKO_COUNTS` / `_PLINKO_EDGES` 重複 | `statcast.py:137, 142`、`builder.py:52, 57` | 單一來源。 |
| Put Away% 計算重複 | `statcast.py:990-996, 1061-1065, 1277-1282` | 抽成 `_compute_put_away_pct(pitches)`，回傳 `(pct, two_strike_count)`。 |
| PA final AVG / wOBA denominator 邏輯重複 | `statcast.py:860-876`、`1021-1085`、`1222-1301` | 抽 `iter_valid_pa_outcomes()` 或 `compute_pa_outcome_totals()`，統一排除 IBB/SH/non-PA events。 |
| `safe_float()` 與 `_float_or_none()` 相似 | `helpers.py:60`、`statcast.py:453` | 保留一個 `to_float(value, default=None, finite=False)`。 |
| `default_if_none()` 與 `num_dash()` 重疊 | `jinja_env.py:32-41` | 合併為 `dash(value, fallback="-", blank_is_missing=True)`。 |
| ISO 計算重複 | `builder.py:650-652`、`helpers.py:331-336` | 統一交給 `stats/derived.py`。 |
| Pitch movement 生成時機重複 | `statcast.py:962`、`builder.py:874-895` | 選一個 source of truth。建議 sync 時只存 raw-ish pitch logs，build 時產生 chart payload；或 sync 時存 payload，build 不再重算。 |
| sport level mapping 分散 | `api.py:17-26, 284-293`、`helpers.py:11-20` | 合併到 `constants/levels.py`。 |
| UTC+8 hardcode | `api.py:242`、`builder.py:714` | `utils/dates.TW_TZ`。 |
| field mapping 寫死在 function 裡 | `sync.py:183-320` | 抽成 mapping constants，例如 `YEAR_BY_YEAR_FIELD_MAP`、`ADVANCED_FIELD_MAP`。 |

---

## 常數治理方案

### 目前常數分類

| 類型 | 目前位置 | 問題 | 建議位置 |
|---|---|---|---|
| Runtime config | `helpers.DEFAULT_SEASON_YEAR`、`sync.MAX_WORKERS`、`api.TIMEOUT` | 分散且語意不同 | `config.py` |
| API endpoint config | `api.BASE_URL`、live-feed URL literal | URL literal 分散 | `api/client.py` |
| Sport level mapping | `api._SPORT_ID_MAP`、`api._SPORT_NAME_TO_ABBR`、`helpers.SPORT_LEVEL_ORDER` | 同一 domain 多處定義 | `constants/levels.py` |
| Stat field schema | `helpers._COUNTING_FIELDS`、`sync._apply_*_fields()` 內部 mapping | 欄位多且無單一來源 | `constants/stat_fields.py` + `mappings/mlb_stats.py` |
| Pitch classification | `SWING_CODES`、`WHIFF_CODES`、`CALLED_STRIKE_CODES`、`_NON_PA_EVENTS` | 放在大檔案頂部，難測 | `constants/statcast.py` |
| Yearly run environment | `_W`、`FIP_CONSTANTS`、`LEAGUE_RA9` | 年度資料更新不明確 | `data/constants/*.json` + loader |
| Chart definitions | `_COUNT_USAGE_BUCKETS`、`_PLINKO_COUNTS`、`_PLINKO_EDGES` | builder/statcast 重複 | `constants/statcast.py` |
| Spray / Gameday constants | `_GAMEDAY_*`、`_HIT_LOCATION_ZONE` | 和公式混在單檔 | `constants/statcast.py` |
| Presentation labels | split labels、bucket labels | 中文/英文 label 混在計算 constants | `presentation/labels.py` 或 frontend JSON |

### 建議檔案設計

```text
site_builder/constants/
  levels.py
  stat_fields.py
  statcast.py
  run_environment.py

src/data/constants/
  woba_weights.json
  fip_constants.json
  league_run_environment.json
  park_factors.json        # 未來 TJStats / TJBat+ 可用
```

### Python constants 範例

```python
# site_builder/constants/levels.py
from dataclasses import dataclass

@dataclass(frozen=True)
class SportLevel:
    key: str
    order: int
    sport_ids: tuple[int, ...]
    api_names: tuple[str, ...]
    display_zh: str

SPORT_LEVELS = {
    "MLB": SportLevel("MLB", 0, (1,), ("Major League Baseball",), "MLB"),
    "AAA": SportLevel("AAA", 1, (11,), ("Triple-A",), "AAA"),
    "AA": SportLevel("AA", 2, (12,), ("Double-A",), "AA"),
    "A+": SportLevel("A+", 3, (13,), ("High-A",), "A+"),
    "A": SportLevel("A", 4, (14, 15), ("Single-A", "Low-A"), "A"),
    "ROK": SportLevel("ROK", 6, (16, 17), ("Rookie", "Rookie Advanced"), "新人聯盟"),
}
```

```python
# site_builder/constants/statcast.py
from dataclasses import dataclass

@dataclass(frozen=True)
class CountBucket:
    key: str
    counts: frozenset[tuple[int, int]]

COUNT_USAGE_BUCKETS = (
    CountBucket("early", frozenset({(0, 0), (0, 1), (1, 0)})),
    CountBucket("pitcher_ahead", frozenset({(0, 1), (0, 2), (1, 2), (2, 2)})),
    CountBucket("pitcher_behind", frozenset({(1, 0), (2, 0), (3, 0), (2, 1), (3, 1)})),
    CountBucket("pre_two_strikes", frozenset({(0, 0), (0, 1), (1, 0), (1, 1), (2, 1), (3, 1)})),
    CountBucket("two_strikes", frozenset({(0, 2), (1, 2), (2, 2), (3, 2)})),
)
```

### 年度常數 loader 範例

```python
# site_builder/constants/run_environment.py
from dataclasses import dataclass

@dataclass(frozen=True)
class LookupResult:
    value: float
    exact: bool
    source_year: int | None

def get_fip_constant(level: str, year: int) -> LookupResult:
    exact = _FIP_BY_YEAR_LEVEL.get((year, level))
    if exact is not None:
        return LookupResult(exact, True, year)
    fallback = _latest_available_for_level(_FIP_BY_YEAR_LEVEL, level, year)
    return LookupResult(fallback.value, False, fallback.year)
```

### 維護規則

1. 年度可變資料（wOBA weights、FIP constants、league RA/9、park factors）放 `src/data/constants/*.json`，並用 loader 驗證 schema。
2. 計算 function 不直接讀 JSON，每次 build/sync 啟動時載入一次 constants，或以 module-level cached loader 提供 lookup。
3. lookup function 必須回傳是否 exact fallback，fallback 要 log warning 或在結果 metadata 標記。
4. label 不放在計算 constants 裡。`COUNT_USAGE_BUCKETS` 只放 key/counts，中文顯示由 `presentation/labels.py` 或前端 JS 決定。
5. 每新增年度資料，至少加一個 validation test：所有 active sport levels 是否有該年度值、fallback 是否符合預期。
6. 所有 magic number 必須有 source 註解，例如 barrel definition、Gameday spray correction、wOBA source、FIP source。

---

## 建議重構順序

| 階段 | 動作 | 風險 | 理由 |
|---|---|---|---|
| 1 | 建立 `constants/levels.py`、`utils/json.py`、`utils/numbers.py`，搬低風險工具 | 低 | 不改資料流程。 |
| 2 | 搬 `parse_roster_from_file()`、sport level mapping | 低 | 消除 API client 職責混雜。 |
| 3 | 搬 builder 內 Statcast combine functions 到 `statcast/combine.py` | 中 | 需更新 imports，但可用現有輸入輸出測試。 |
| 4 | 搬 `helpers.py` 的 stats aggregation 到 `stats/season.py`、`stats/derived.py` | 中 | 要注意 display string vs numeric 型別。 |
| 5 | 拆 `statcast.py` 成 extract/classify/batted_ball/pitch_types/plinko/movement/aggregate | 中 | function 多，但多數是 pure functions。 |
| 6 | 拆 DB schema/CRUD from `sync.py` | 中高 | SQLite migration 與 conflict key 要同步修。 |
| 7 | 拆 `build_static_site()` context builder | 中 | 輸出 HTML 可用 snapshot/diff 驗證。 |
| 8 | 拆 frontend templates / JS / CSS | 中 | 需要瀏覽器 smoke test。 |

---

## `src/` 檔案職責劃分與重構建議

### 目前檔案職責

| 檔案 | 目前職責 | 問題 |
|---|---|---|
| `src/templates/base.j2` | HTML shell、meta、global header、global CSS、favicon、table-align JS、avatar fallback JS、Cloudflare beacon | layout、SEO、global JS、analytics 混在同檔，且 inline JS 不可快取。 |
| `src/templates/index.j2` | 首頁 player cards、排序 controls、inline `sortCards()` | card markup 與排序行為混在模板；使用 inline `onclick`。 |
| `src/templates/player_detail.j2` | player hero、tabs、bio、stats、gamelogs、advanced/statcast、fielding、charts、pitch log、Pitch Plinko、所有互動 JS | 2053 行，職責過多，模板、資料 script、DOM 操作、圖表 rendering 全混在一起。 |
| `src/templates/404.j2` | 404 page | 有 inline style，樣式應移至 CSS。 |
| `src/static/css/style.css` | 全站 tokens、layout、header、index、player detail、tables、status、Pitch Plinko、pitch log、responsive | 1911 行全域 CSS，所有頁面都載入所有樣式。 |
| `src/static/logo.svg` | logo asset | 可保留；若 inline style 增長再獨立設計 token。 |
| `src/data/roster.json` | tracked player roster source data | 作為 source config 合理，但 `src/data` 名稱容易與 build output data 混淆。 |
| `src/.DS_Store` | macOS metadata | 不應出現在 source tree，應刪除並加入 ignore。 |

### 建議新的 `src/` 架構

```text
src/
  templates/
    base.j2
    index.j2
    404.j2
    macros/
      avatar.j2
      tables.j2
      stat_box.j2
      player_card.j2
    player/
      detail.j2
      hero.j2
      tabs.j2
      bio.j2
      stats.j2
      gamelogs.j2
      advanced.j2
      fielding.j2
      charts.j2
      pitch_arsenal.j2
      pitch_plinko.j2

  static/
    css/
      base.css
      layout.css
      components.css
      index.css
      player-detail.css
      tables.css
      pitch-log.css
      pitch-plinko.css
      charts.css
      responsive.css
    js/
      shared/
        avatar-fallback.js
        table-align.js
      index.js
      player-tabs.js
      gamelog-filters.js
      pitch-log.js
      arsenal-filters.js
      pitch-plinko.js
      performance-chart.js
    logo.svg

  data/
    roster.json
    constants/
      woba_weights.json
      fip_constants.json
      league_run_environment.json
```

### Template 拆分建議

| 現有區塊 | 建議檔案 | 說明 |
|---|---|---|
| base layout + header | `templates/base.j2` | 只保留 document shell、blocks、header include。 |
| avatar markup | `templates/macros/avatar.j2` | index/player detail 共用。 |
| stat boxes | `templates/macros/stat_box.j2` | index card 與 hero stats 共用。 |
| table shell / empty row | `templates/macros/tables.j2` | 多個 data table 共用。 |
| index card | `templates/macros/player_card.j2` | `index.j2` 只負責 loop + controls。 |
| player hero | `templates/player/hero.j2` | 從 detail 抽出個人資訊 header。 |
| tab nav | `templates/player/tabs.j2` | desktop/mobile nav 同一區塊。 |
| bio tab | `templates/player/bio.j2` | 個人資料、next game、transaction、career card。 |
| basic stats tab | `templates/player/stats.j2` | 歷年/合計基礎數據表。 |
| game logs tab | `templates/player/gamelogs.j2` | 逐場紀錄與 lazy pitch log trigger。 |
| advanced tab | `templates/player/advanced.j2` | Statcast/advanced tables。 |
| pitch arsenal table | `templates/player/pitch_arsenal.j2` | 球種數據、對戰結果、count usage。 |
| fielding tab | `templates/player/fielding.j2` | 守備數據。 |
| charts tab | `templates/player/charts.j2` | Chart.js canvas + data scripts。 |
| Pitch Plinko | `templates/player/pitch_plinko.j2` | HTML data containers only，rendering 交給 JS。 |

### JavaScript 拆分建議

| 現有位置 | 建議檔案 | 職責 |
|---|---|---|
| `base.j2:36-70` | `static/js/shared/table-align.js` | 對齊 numeric table header。 |
| `base.j2:72-88` | `static/js/shared/avatar-fallback.js` | headshot fallback。 |
| `index.j2:93-118` | `static/js/index.js` | player card sorting；移除 inline `onclick`。 |
| `player_detail.j2` tab restoration | `static/js/player-tabs.js` | tab switch、query param restore、tab-change event。 |
| game log filters | `static/js/gamelog-filters.js` | 年份/層級 selector。 |
| pitch log lazy rendering | `static/js/pitch-log.js` | fetch pitchlog JSON、escape DOM、render table。 |
| arsenal filters | `static/js/arsenal-filters.js` | year/level/bat-side filter。 |
| Pitch Plinko renderer | `static/js/pitch-plinko.js` | SVG render、tooltip、lazy init。 |
| Chart.js initialization | `static/js/performance-chart.js` | line chart init；Chart.js 版本 pin。 |

### CSS 拆分建議

| 現有區塊 | 建議檔案 | 說明 |
|---|---|---|
| `:root` tokens、base/body | `base.css` | 全站 tokens 與 reset。 |
| header/container/main | `layout.css` | 全站 layout。 |
| glass/card/button/avatar/status | `components.css` | 可跨頁元件。 |
| dashboard/player-card/sort bar | `index.css` | 只給首頁。 |
| hero/tabs/bio/next-game/transactions | `player-detail.css` | player detail common。 |
| `.data-table`, `.table-scroll` | `tables.css` | 表格元件。 |
| `.pitch-log-*` | `pitch-log.css` | pitch log 專用。 |
| `.pitch-plinko-*` | `pitch-plinko.css` | Pitch Plinko 專用。 |
| `.chart-*` | `charts.css` | Chart sections。 |
| media queries | `responsive.css` 或各檔 local media | 若拆分檔案，每個頁面 CSS 可保留 local responsive。 |

### `src/data` 建議

`roster.json` 是 source-of-truth config，不是 build artifact。可以保留在 `src/data/roster.json`，但若未來加入大量 constants，建議把 config 改到 `config/roster.json`，把 yearly constants 放 `src/data/constants/`。

---

## 最小可執行重構切片

1. 新增 `site_builder/constants/levels.py`，搬 `SPORT_LEVEL_ORDER`、sport id/name mapping、`sport_obj_to_abbr()`。
2. 新增 `site_builder/roster.py`，搬 `parse_roster_from_file()`，更新 `sync.py` import。
3. 新增 `site_builder/utils/json.py`、`site_builder/utils/numbers.py`，搬 JSON / safe number helpers。
4. 新增 `site_builder/statcast/combine.py`，先搬 builder 內 `_combine_*` functions，不改輸出格式。
5. 新增 `src/static/js/shared/table-align.js`、`avatar-fallback.js`、`index.js`，先移出最小 inline JS。
6. 新增 `templates/player/` partials，先只拆 `player_detail.j2` 的 hero / bio / gamelogs，不動 JS 行為。

---

## 驗證方式

| 重構區域 | 驗證 |
|---|---|
| constants / utils 搬遷 | `python build.py build --db data/tracker.sqlite3 --output dist-test`，比較是否 build 成功。 |
| statcast combine 搬遷 | 對 `_combine_statcast_dicts()` 加 fixture test，確認搬遷前後 dict 相同。 |
| stats/derived 搬遷 | 加 pytest：IP 轉換、ERA/WHIP、season combined、ISO、BABIP。 |
| sync/db 拆分 | 用單一 player `python build.py refresh --player <id>` smoke test。 |
| frontend JS 拆分 | 本機開 `python -m http.server 8000 --directory dist`，測首頁排序、tab 切換、pitch log、Pitch Plinko、Chart.js。 |
| CSS 拆分 | Desktop + mobile 截圖比對。 |

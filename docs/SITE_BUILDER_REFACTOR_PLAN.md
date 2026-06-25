# site_builder 重構計畫 v2

> 狀態：**規劃中（尚未執行）**
> 依據：`docs/CODE_REVIEW_REPORT.md`（2026-06-25 六檔 code review）
> 黃金標準：`site_builder/levels.py` —— 單一職責、領域知識集中於一處、純函式、無 I/O、檔頭講清楚「為什麼」。
> 目標：把目前肥大、職責混雜的 6 個檔案，重組成一組「每個檔案都像 `levels.py` 一樣乾淨」的模組／subpackage；
> 同時用「純搬移 + re-export shim + 逐階段驗證」把重構風險壓到最低。

---

## 目錄

1. [現況診斷](#1-現況診斷為什麼要重構)
2. [設計原則](#2-設計原則levelspy-標準)
3. [本次重構的範圍邊界](#3-本次重構的範圍邊界務必先讀)
4. [目標架構總覽](#4-目標架構總覽)
5. [分層與依賴方向](#5-分層與依賴方向無循環)
6. [公開契約凍結清單](#6-公開契約凍結清單)
7. [逐模組搬移細目](#7-逐模組搬移細目)
8. [待消除的重複](#8-待消除的重複)
9. [常數管理策略（三層）](#9-常數管理策略三層)
10. [re-export shim 設計](#10-re-export-shim-設計)
11. [風險控制與驗證方法](#11-風險控制與驗證方法)
12. [分階段執行順序](#12-分階段執行順序)
13. [code review 問題 → 重構後落點](#13-code-review-問題--重構後落點)
14. [命名慣例與檔頭模板](#14-命名慣例與檔頭模板)
15. [收尾](#15-收尾)
16. [附錄 A：完整符號搬移對照表](#附錄-a完整符號搬移對照表)

---

## 1. 現況診斷（為什麼要重構）

目前 `site_builder/` 共 7 個檔（不含 `__init__.py`），總計約 5,500 行，分工不均且職責混雜：

| 檔案 | 行數 | 問題 |
|------|------|------|
| `levels.py` | 149 | ✅ 乾淨範本（單一職責、領域集中） |
| `api.py` | 419 | 尚可，但常數散落（v1.1 URL、timeout、sportId） |
| `jinja_env.py` | 158 | 格式化邏輯與環境建構混在一起 |
| `helpers.py` | 687 | ❌ **雜物箱**：型別轉換 + JSON + 單位換算 + 棒球統計 + roster 狀態 + level 橋接，5 種互不相關的職責 |
| `builder.py` | 1,261 | ❌ **巨檔**：DB 載入 + 跨等級聚合 + headshot I/O + SEO/JSON-LD + sitemap/robots + 渲染主流程 |
| `statcast.py` | 1,415 | ❌ **巨檔**：萃取 + 分類 + 聚合 + 圖表 + 公式 + 顯示，全擠一檔 |
| `sync.py` | 1,425 | ❌ **巨檔**：schema/migration + 欄位對應 + 球員 pipeline + statcast pipeline |

三個 >1,200 行的巨檔，加上 `helpers.py` 雜物箱，是維護痛點的根源。code review 也直接點出由「分工差」衍生的問題：

- **重複定義**：`_ratio`、`_is_unknown_pitch_type`、`_PLINKO_*`、`_COUNT_USAGE_BUCKETS`、`_BAT_SIDE_SPLITS` 在 `statcast.py` 與 `builder.py` 各寫一份（格式還略有出入，是潛在的不一致來源）。
- **常數散落 6 檔**：賽伯計量常數（wOBA 權重、FIP 常數）、部署設定（URL、timeout、併發數）、結構常數（pitch code、軌跡集合）混雜，維護者不知「每季要改什麼、去哪改」。
- **領域知識外洩**：棒球統計公式（WHIP、BABIP）藏在 687 行的 `helpers.py` 中段，難以單獨測試與校正。
- **magic number 遍地**：FIP 係數、wOBA 門檻、單位換算係數、DB timeout、抽樣上限等硬編碼於函式內。

---

## 2. 設計原則（`levels.py` 標準）

每個重構後的模組都應符合以下五點（即 `levels.py` 的特質）：

1. **單一職責**：檔頭一句話講清楚「我負責什麼」，且只負責那件事。
2. **領域知識集中**：同一類知識（如某個常數表）只存在於一個檔，其他模組一律 import，**禁止各自再定義一份**。
3. **依賴單向**：只能 import 比自己「低層」的模組，不可形成循環。
4. **純度優先**：純運算／純資料的模組不做 I/O；I/O（網路、檔案、DB）集中在明確的邊界模組。
5. **檔頭說明「為什麼」**：像 `levels.py` 解釋 2020–21 MiLB 改制那樣，把領域背景寫在檔頭，讓後人看得懂。

> 「功能很大就開資料夾拆多檔」：`statcast`、`stats`、`sync` 三個大領域改為 subpackage，
> 用 `__init__.py` 當對外單一窗口（re-export），內部依「子職責」拆成數個 ~200–400 行的小檔。

---

## 3. 本次重構的範圍邊界（務必先讀）

為了把風險降到最低，**嚴格區分「結構重構」與「行為修正」**：

### ✅ 本次會做（純結構，零行為變更）
- 搬移函式／常數到新模組、改 import 路徑。
- 合併重複定義（用參數保留各呼叫端原行為）。
- 刪除確定的 deadcode（`highest_level`、`slice_prefix`、`statcast` 永不成立分支）。
- 把 magic number / 散落常數抽成具名常數（**值不變**）。
- 新增 re-export shim 維持相容。

### ❌ 本次**不**做（留待後續，由 `CODE_REVIEW_REPORT.md` 追蹤）
- 不改任何計算公式（WHIP、BABIP、ev90、sweet-spot%、barrel% 等**維持現狀**）。
- 不改 DB schema、不改 SQL 行為（含 `playbyplay_processed` 的去重邏輯）。
- 不改 template、不改任何 jinja filter 名稱或輸出格式。
- 不改 4 個公開入口的簽名與行為。

> **理由**：把「移動程式碼」和「修正邏輯」混在一起做，會讓「輸出變了到底是搬壞還是修對」無法判斷。
> 先純搬移（可用 golden diff 證明輸出 byte-for-byte 不變），完成後每個 bug 都有乾淨的落點（見 §13），再逐一修正並補測試。

---

## 4. 目標架構總覽

```
site_builder/
  __init__.py

  # ── L0 設定 / 常數層 ──
  config.py                 # [CONFIG] 部署/站台/執行參數（偶爾更新）
  season_constants.py       # [SEASONAL] 每季必更新的賽伯計量常數（單一維護入口）

  # ── L1 通用工具層（無領域知識、無 I/O）──
  util/
    __init__.py             # re-export 全部公開工具
    obj.py                  # Obj：屬性存取式 dict（模板用容器）
    coerce.py               # safe_float / safe_int / to_finite_float
    jsonio.py               # loads_json / loads_json_dict / loads_json_list / dumps_json
    numeric.py              # ratio / mean / mean_round / clamp
    units.py                # ip_to_outs / outs_to_ip / height_to_cm / lbs_to_kg / parse_date
    textfmt.py              # fmt_avg / floatformat / num_dash / default_if_none / pct_fmt /
                            #   json_html_safe / tojson_safe / jsonld / count_label

  # ── L2 領域：聯盟等級（既有，微調）──
  levels.py                 # (不大動) + 新增 level_case_sql() 集中 SQL CASE 產生

  # ── L3 領域：棒球統計 / 名單 ──
  stats/
    __init__.py             # re-export
    rates.py                # calc_obp / has_appearance / _compute_rate_stats /
                            #   _compute_advanced_stats（所有「率」公式）
    aggregate.py            # _COUNTING_FIELDS / _sum_counting / _aggregate_stats /
                            #   compute_career / compute_season_combined /
                            #   compute_year_groups / annotate_computed_stats /
                            #   highest_level_row
  roster.py                 # ROSTER_*_CODES / categorize_roster_status / is_active_player

  # ── L4 外部 API ──
  api.py                    # (不大動) MLB Stats API client；常數抽到 config

  # ── L5 領域：Statcast（subpackage）──
  statcast/
    __init__.py             # re-export 全部對外公開 API（sync/builder import 不用改）
    constants.py            # [STATIC] code 集合 / event map / plinko / trajectory /
                            #   gameday / zone / 門檻常數 / _is_unknown 用的判定資料
    classify.py             # 單球判定：_is_swing/_is_whiff/_is_called_strike/_is_in_zone/
                            #   _is_out_of_zone / _is_barrel / _is_sweet_spot /
                            #   _is_unknown_pitch_type / _filter_known_pitch_events /
                            #   _pre_count_tuple / _post_count_tuple / _count_label
    extract.py              # extract_pitch_logs / _ensure_pre_strikes（live-feed → pitch dict）
    formulas.py             # get_woba_weights / _compute_woba / compute_fip / compute_xwpct
    charts.py               # plinko / movement / spray 圖表資料
    aggregate.py            # _aggregate_pitches / discipline / batted-ball /
                            #   compute_pitcher_statcast(+subs) / compute_batter_statcast(+subs)
    combine.py              # 跨等級 _combine_*（從 builder.py 搬來）+ _combine_statcast_dicts
    display.py              # summarize_pitch_for_display

  # ── L6 持久化 / 同步（subpackage）──
  sync/
    __init__.py             # re-export: sync_database / update_database / sync_statcast
    db.py                   # _init_db(schema+migration) / 行 I/O / 查詢 /
                            #   表名常數 / EMPTY_PITCHES / DB_TIMEOUT
    mappers.py              # _apply_yearbyyear_fields / _apply_advanced_fields
    common.py               # _build_roster_map（兩個 pipeline 共用）
    pipeline.py             # _fetch_player_data / _write_player_to_db / _run_pipeline /
                            #   sync_database / update_database
    statcast_pipeline.py    # _fetch_and_extract_game / _load_all_pitches_for_player /
                            #   _merge_statcast_into_season / _compute_player_statcast_bundle /
                            #   sync_statcast

  # ── L7 渲染層 ──
  urls.py                   # URL helper factory（從 jinja_env 抽出）
  headshots.py              # _prefetch_headshots（頭像下載/快取 I/O）
  player_bundle.py          # _load_player_bundle / player_display_name（DB → 模板用 player 物件）
  seo.py                    # canonical path / description / JSON-LD / sitemap / robots
  jinja_env.py              # (瘦身) 只建 Environment + 註冊 filter/global

  # ── L8 主流程 ──
  builder.py                # build_static_site 主流程 + _pick_display_stat
```

> **檔案數變化**：7 檔（巨）→ 約 30 檔（小而專）。雖然檔案變多，但每檔職責單一、平均 ~200 行，
> 維護者依「層 + 職責」即可秒定位，符合使用者「像 `levels.py` 一樣乾淨」的目標。

---

## 5. 分層與依賴方向（無循環）

依賴只能由上往下（高層 import 低層），同層之間註明子順序避免循環：

```
L0  config, season_constants
      ↓
L1  util/*            (僅依賴 stdlib)
      ↓
L2  levels            (純，無依賴)
      ↓
L3  stats/* , roster  (依賴 util, levels)
      ↓
L4  api               (依賴 config, levels)
      ↓
L5  statcast/*        (依賴 util, season_constants；套件內順序見下)
      ↓
L6  sync/*            (依賴 api, levels, stats, roster, statcast, config, util)
      ↓
L7  urls, headshots, player_bundle, seo, jinja_env
      ↓
L8  builder
```

**statcast 套件內部順序**（避免循環）：
`constants → classify → extract → formulas → charts → aggregate → combine → display → __init__`
（`aggregate` 可依賴 `formulas`/`charts`/`classify`；`combine` 只依賴 `constants`+`util`。）

**sync 套件內部順序**：
`db → mappers → common → pipeline / statcast_pipeline → __init__`

**L7 內部順序**：`urls / headshots`（獨立）→ `player_bundle` → `seo`（可 import player_bundle 的 `player_display_name`）→ `jinja_env`（獨立，依賴 util/textfmt + urls + levels）。

> 驗證無循環的方法：Phase 完成後跑 `python -c "import site_builder.builder"`；若有循環會立即 ImportError。

---

## 6. 公開契約凍結清單

以下符號的 **import 路徑、簽名、行為** 在整個重構期間維持不變（靠 shim 保證）：

| 符號 | import 路徑（凍結） | 由誰使用 |
|------|---------------------|----------|
| `sync_database` | `site_builder.sync` | build.py |
| `update_database` | `site_builder.sync` | build.py |
| `sync_statcast` | `site_builder.sync` | build.py |
| `build_static_site` | `site_builder.builder` | build.py |
| `DEFAULT_SEASON_YEAR` | `site_builder.helpers` | build.py |
| 全部 jinja filter 名稱 | （template 內字串） | `src/templates/*` |

> `site_builder.sync` 變成 package 後，`sync/__init__.py` 必須 re-export 前三者；
> `DEFAULT_SEASON_YEAR` 雖搬到 `config.py`，`helpers.py` shim 仍 re-export，使 build.py **一行都不用改**。
> jinja filter 名稱由 `jinja_env.create_jinja_env` 以相同字串註冊（見 §7.10），template 完全不受影響。

---

## 7. 逐模組搬移細目

> 表格欄位：**新位置** ← **來源**（原符號）｜備註。標 `★` 者為去重合併點。

### 7.1 `config.py` — [CONFIG] 偶爾更新
| 常數（新名） | 來源 | 備註 |
|------|------|------|
| `BASE_URL` | api `BASE_URL` | v1 |
| `BASE_URL_V11` | api（行 299/333 硬編碼） | ★新增具名常數，消除重複硬編碼 |
| `TIMEOUT` | api `TIMEOUT` | 一般請求 15s |
| `LIVE_FEED_TIMEOUT` | api（行 301 `timeout=30`） | ★抽出 |
| `NEXT_GAME_WINDOW_DAYS` | api（行 238 `days=7`） | ★抽出 |
| `TW_TZ` | api（行 267 `timedelta(hours=8)`） | ★抽出台灣時區 |
| `MAX_WORKERS` | sync `MAX_WORKERS` | 併發數 |
| `DB_TIMEOUT` | sync（行 1120 `timeout=30` 等） | ★統一 DB connect timeout |
| `SITE_TITLE` / `SITE_DESCRIPTION` / `SITE_SAME_AS` | builder | 站台識別 |
| `SITE_ORIGIN` | jinja_env（行 120 預設值） | ★抽出 |
| `DEFAULT_SEASON_YEAR` | helpers | 讀環境變數，預設 2026 |
| `HEADSHOT_URL_TEMPLATE` / `HEADSHOT_TIMEOUT` | builder（行 577-581） | ★抽出頭像 URL/timeout |
| 輸出路徑常數（`OUTPUT_*`、`IMG_PLAYERS_DIR` 等） | builder 散落字串 | ★集中（見 §13） |

### 7.2 `season_constants.py` — [SEASONAL] 每季必更新
| 常數（新名） | 來源 |
|------|------|
| `WOBA_WEIGHTS` | statcast `_W` |
| `WOBA_FALLBACK` | statcast `_WOBA_FALLBACK` |
| `FIP_CONSTANTS` | statcast `FIP_CONSTANTS` |
| `LEAGUE_RA9` | statcast `LEAGUE_RA9` |

檔頭寫明每季更新步驟與資料來源（FanGraphs guts 連結等，沿用舊計畫 §7.1 範本）。

### 7.3 `util/` — 純工具
| 新位置 | 來源（原符號） | 備註 |
|--------|----------------|------|
| `util/obj.py` `Obj` | helpers `Obj` | |
| `util/coerce.py` `safe_float` / `safe_int` | helpers | |
| `util/coerce.py` `to_finite_float` | statcast `_float_or_none` | ★合併概念：以 `safe_float` 為基礎加 `math.isfinite`；statcast 改呼叫此 |
| `util/jsonio.py` `loads_json`/`loads_json_dict`/`loads_json_list`/`dumps_json` | helpers | |
| `util/numeric.py` `ratio` | statcast `_ratio` + builder `_ratio` | ★合併兩份；`digits` 由呼叫端帶入（statcast 多用 3、builder combine 多用 4），行為不變 |
| `util/numeric.py` `mean` / `mean_round` | statcast `_mean` / `_mean_round` | |
| `util/numeric.py` `clamp` | （新增小工具） | 供日後 `ip_to_outs` clamp 修正用，本次先不接 |
| `util/units.py` `ip_to_outs`/`outs_to_ip`/`height_to_cm`/`lbs_to_kg`/`parse_date` | helpers | `_HEIGHT_RE` 一併搬來，緊鄰 `height_to_cm` |
| `util/textfmt.py` `fmt_avg` | helpers `_fmt_avg` | |
| `util/textfmt.py` `floatformat`/`num_dash`/`default_if_none`/`pct_fmt` | jinja_env | 格式化邏輯移此；jinja_env 改 import 後註冊 |
| `util/textfmt.py` `json_html_safe`/`tojson_safe`/`jsonld` | jinja_env | 同上 |
| `util/textfmt.py` `count_label` | statcast `_count_label` | `(b,s)` → `"B-S"`；★與 statcast 共用 |

> `calc_obp`、`has_appearance` **不進 util**（含棒球語意）→ 進 `stats/`。

### 7.4 `levels.py` — 微調
- 新增純函式 `level_case_sql(column: str) -> str`：產生 sync 目前手拼的 `CASE ... END` 字串（含 `ELSE _UNKNOWN_RANK`），把 alias→rank 的對應與 `_UNKNOWN_RANK` 集中在 levels（唯一知道 level 的地方）。**輸出與現狀字串等價**（純搬移；安全修正留後續）。
- 刪 `helpers.py` 對 levels 的冗餘 re-export（見 §10）。

### 7.5 `stats/` — 棒球統計
| 新位置 | 來源（原符號） |
|--------|----------------|
| `stats/rates.py` `calc_obp` / `has_appearance` / `_compute_rate_stats` / `_compute_advanced_stats` | helpers 同名 |
| `stats/aggregate.py` `_COUNTING_FIELDS` / `_sum_counting` / `_aggregate_stats` / `compute_career` / `compute_season_combined` / `compute_year_groups` / `annotate_computed_stats` / `highest_level_row` | helpers 同名 |
| ~~`highest_level`~~ | helpers `highest_level` | ★**刪除 deadcode**（無呼叫者） |

`stats/aggregate.py` import `stats/rates.py`（aggregate 呼叫 rate 計算）。

### 7.6 `roster.py` — 名單狀態
| 符號 | 來源 |
|------|------|
| `ROSTER_INJURED_CODES`/`ROSTER_RESTRICTED_CODES`/`ROSTER_OTHER_CODES`/`ROSTER_INACTIVE_CODES` | helpers |
| `categorize_roster_status` | helpers |
| `is_active_player` / `_is_national_team_tx` / `_NATIONAL_TEAM_KEYWORD` | helpers |

### 7.7 `statcast/` — 見 §4 樹狀；逐函式對照見[附錄 A](#附錄-a完整符號搬移對照表)
重點：
- 結構常數全進 `statcast/constants.py`，**含 `_BATTER_PLINKO_SKIP_TYPES` 與原 `_compute_vs_pitch_types_batter` 內重複的 `{"EP","FA"}`** → ★合併為單一 `POSITION_PLAYER_PITCH_TYPES`。
- `_is_unknown_pitch_type` 收進 `statcast/classify.py`（builder 改 import）→ ★去重。
- 賽伯計量常數改 `from site_builder.season_constants import ...`。
- 各數學工具改 `from site_builder.util.numeric import ratio, mean, mean_round`、`from site_builder.util.coerce import to_finite_float`。

### 7.8 `sync/db.py` & `sync/mappers.py`
| 新位置 | 來源（原符號） | 備註 |
|--------|----------------|------|
| `sync/db.py` `_init_db` 等全部 DB I/O 與查詢 | sync `_init_db`/`_load_season_row`/`_save_season_row`/`_players_with_existing_stats`/`_warn_orphaned_players`/`_is_first_sync` | |
| `sync/db.py` 表名常數 / `EMPTY_PITCHES` | sync 散落字串 | ★`EMPTY_PITCHES = ("[]", "null", None)`（統一三處不一致的判定，§13） |
| `sync/db.py` 使用 `config.DB_TIMEOUT` | sync `timeout=30`/預設 | ★統一 |
| `sync/db.py` 使用 `levels.level_case_sql` | sync 行 653-661 手拼 CASE | ★改用 levels helper |
| `sync/mappers.py` `_apply_yearbyyear_fields`/`_apply_advanced_fields` | sync 同名 | |

### 7.9 `sync/common.py` / `sync/pipeline.py` / `sync/statcast_pipeline.py`
| 新位置 | 來源 |
|--------|------|
| `sync/common.py` `_build_roster_map` | sync 同名（兩 pipeline 共用，避免互相依賴） |
| `sync/pipeline.py` `_fetch_player_data`/`_write_player_to_db`/`_run_pipeline`/`sync_database`/`update_database` | sync 同名 |
| `sync/statcast_pipeline.py` `_fetch_and_extract_game`/`_pitches_need_hit_coord_backfill`/`_load_all_pitches_for_player`/`_merge_statcast_into_season`/`_compute_player_statcast_bundle`/`sync_statcast` | sync 同名 |

> `sync/statcast_pipeline.py` 內 `from site_builder.statcast import compute_fip, ...` 不會與檔名衝突（絕對路徑為 `site_builder.sync.statcast_pipeline`，與 `site_builder.statcast` 不同）。

### 7.10 渲染層
| 新位置 | 來源（原符號） | 備註 |
|--------|----------------|------|
| `urls.py` `make_url_helpers`/`make_absolute_url` | jinja_env `_make_url_helpers`/`_make_absolute_url` | jinja_env import 後註冊為 global |
| `headshots.py` `prefetch_headshots` + 頭像常數 | builder `_prefetch_headshots` | URL/timeout 用 config |
| `player_bundle.py` `load_player_bundle` / `player_display_name` | builder `_load_player_bundle` / `_player_display_name` | |
| `seo.py` `player_canonical_path`/`player_description`/`index_structured_data`/`player_structured_data`/`write_robots`/`write_sitemap` | builder 同名 | site metadata 改 import config |
| `jinja_env.py` `create_jinja_env` | jinja_env（瘦身） | 只建 env + 註冊；filter 名稱**完全不變** |
| ~~`slice_prefix`~~ / ~~`site_origin` global~~ | jinja_env | ★刪 deadcode（template 0 次使用） |
| `builder.py` `build_static_site` / `_pick_display_stat` | builder（剩餘主流程） | 從 ~1,261 行縮到 ~300 行 |
| `builder.py` `_combine_*` | → **`statcast/combine.py`** | ★整批搬移，順帶消除 builder/statcast 的 `_ratio`/`_is_unknown`/`_PLINKO_*` 重複 |

---

## 8. 待消除的重複

| 重複 | 出現位置 | 處理 |
|------|----------|------|
| `_ratio` | statcast、builder | → `util/numeric.ratio`（`digits` 參數化，行為不變） |
| `_is_unknown_pitch_type` | statcast、builder | → `statcast/classify`，builder（搬去 combine 後）改 import |
| `_float_or_none` vs `safe_float` | statcast vs helpers | → `util/coerce.to_finite_float` |
| `{"EP","FA"}` | statcast 模組常數 + `_compute_vs_pitch_types_batter` 區域變數 | → `statcast/constants.POSITION_PLAYER_PITCH_TYPES` |
| `_BAT_SIDE_SPLITS`/`_COUNT_USAGE_BUCKETS`/`_PLINKO_COUNTS`/`_PLINKO_EDGES` | statcast、builder 各一份（格式略不同） | builder 的 `_combine_*` 搬進 `statcast/combine.py` 後，與 statcast 其餘程式共用 `statcast/constants.py` 同一份；**若 combine 確實需要不同格式（字串 count vs tuple count），在 constants.py 以衍生變數產生並加註說明** |
| `_count_label` | statcast | builder combine 若用到，改 import `util/textfmt.count_label` |

> 合併原則：**先用參數／衍生變數保證每個呼叫端拿到與現狀一模一樣的值**，再以 golden diff 證明輸出不變。

---

## 9. 常數管理策略（三層）

依「**維護頻率**」分三層，讓 contributor 一眼知道「哪些要定期改、去哪改」。每個常數區塊上方加 cadence 標籤註解。

### Tier 1 — [SEASONAL] 每季/每年必更新 → `season_constants.py`
`WOBA_WEIGHTS`、`WOBA_FALLBACK`、`FIP_CONSTANTS`、`LEAGUE_RA9`。維護者休賽季只需打開這一個檔。

### Tier 2 — [CONFIG] 偶爾更新 → `config.py`
部署/站台/執行參數（見 §7.1 完整清單）。改站名、網址、併發數、timeout 只看這檔。
**例外**：`ROSTER_*_CODES`（roster 領域）、levels 的 `TIERS`（levels 領域）、api 的 sport 對照（api 領域）雖偶爾更新，但語意上屬各自領域，**留在領域檔**，避免 config 變雜物箱。

### Tier 3 — [STATIC] 綁定演算法、幾乎不動 → 隨領域、去重、集中於各自 `constants.py`
| 常數群 | 歸屬 |
|--------|------|
| `SWING_CODES`/`WHIFF_CODES`/`CALLED_STRIKE_CODES`/`WOBA_EVENT_MAP`/`_NON_PA_EVENTS` | `statcast/constants.py` |
| `_PLINKO_*`/`_COUNT_USAGE_BUCKETS`/`_BAT_SIDE_SPLITS`/`_*_PLINKO_SPLITS`/`POSITION_PLAYER_PITCH_TYPES` | `statcast/constants.py` |
| `_*_TRAJECTORIES`/`_GAMEDAY_*`/`_HIT_LOCATION_ZONE`/`_BATTED_BALL_RATE_DIGITS`/barrel·sweet-spot·hard-hit·zone 門檻 | `statcast/constants.py` |
| `_COUNTING_FIELDS` | `stats/aggregate.py` |
| `_HEIGHT_RE` | `util/units.py`（緊鄰 `height_to_cm`） |
| 表名 / `EMPTY_PITCHES` | `sync/db.py` |

### 共同慣例
- 區塊上方加 cadence 標籤：`# [SEASONAL]` / `# [CONFIG]` / `# [STATIC]`。
- 模組常數一律集中在檔頂（import 之後），不散落於函式之間。
- `CLAUDE.md` 的「Updating Stat Formulas」加一句：「每季更新賽伯計量常數 → 只改 `site_builder/season_constants.py`」。

---

## 10. re-export shim 設計

shim 的唯一目的：讓「舊 import 路徑」在重構期間照常運作，使每個 Phase 都能獨立 ship、獨立驗證。

### 10.1 套件 `__init__.py`（永久保留，當對外窗口）
```python
# site_builder/statcast/__init__.py
from .extract import extract_pitch_logs
from .aggregate import compute_pitcher_statcast, compute_batter_statcast
from .formulas import compute_fip, compute_xwpct, get_woba_weights
from .charts import compute_pitch_movement_chart
from .display import summarize_pitch_for_display
# ↑ 涵蓋 sync.py / builder.py 目前 import 的全部名稱
```
```python
# site_builder/sync/__init__.py
from .pipeline import sync_database, update_database
from .statcast_pipeline import sync_statcast
```

### 10.2 `helpers.py`（過渡 shim，最後一個 Phase 才移除）
重構期間 `helpers.py` 不刪，改成純 re-export，使任何遺漏的舊 import 仍可運作：
```python
# site_builder/helpers.py  （過渡期）
from .config import DEFAULT_SEASON_YEAR          # build.py 仍 from .helpers import
from .util.obj import Obj
from .util.coerce import safe_float, safe_int
from .util.jsonio import loads_json, loads_json_dict, loads_json_list, dumps_json
from .util.units import ip_to_outs, outs_to_ip, height_to_cm, lbs_to_kg, parse_date
from .stats.rates import calc_obp, has_appearance
from .stats.aggregate import (
    compute_career, compute_season_combined, compute_year_groups,
    annotate_computed_stats, highest_level_row,
)
from .roster import categorize_roster_status, is_active_player, ROSTER_INJURED_CODES  # …
from .levels import level_rank  # 僅保留實際被使用的（builder 用）
```
> 完成全部 Phase、把 builder/sync 的 import 改成新路徑後，`helpers.py` 僅剩 build.py 依賴的 `DEFAULT_SEASON_YEAR` 一項；屆時可決定保留極簡 shim 或改 build.py import 後刪檔（見 §15）。

### 10.3 `jinja_env.py` filter 名稱（硬約束）
`create_jinja_env` 內維持**字串名稱完全相同**的註冊：
```python
from .util import textfmt
env.filters["floatformat"]     = textfmt.floatformat
env.filters["num_dash"]        = textfmt.num_dash
env.filters["default_if_none"] = textfmt.default_if_none
env.filters["pct_fmt"]         = textfmt.pct_fmt
env.filters["tojson_safe"]     = textfmt.tojson_safe
env.filters["jsonld"]          = textfmt.jsonld
# slice_prefix：deadcode，不再註冊（template 0 次使用，已確認）
```

---

## 11. 風險控制與驗證方法

### 11.1 三道驗證關卡（每個 Phase 後都要過）
1. **import smoke test**：`python -c "import build; import site_builder.builder; import site_builder.sync; import site_builder.statcast"` —— 抓循環依賴與漏改 import。
2. **golden output diff**（核心關卡）：
   ```bash
   # Phase 0 先備份基準
   python build.py build --output dist_golden
   # 每個 Phase 後重建並比對
   python build.py build --output dist_check
   diff -r dist_golden dist_check          # 期望：完全無差異
   ```
   因為本次是「純結構重構」，**任何 dist 差異都代表搬壞了**，立即定位回滾。
3. **characterization tests**（Phase 0 建立）：對純函式（stats 公式、statcast 公式）以目前輸出建立 snapshot 測試，搬移後跑 `pytest` 必須全綠。

### 11.2 risk 來源與對策
| 風險 | 對策 |
|------|------|
| 漏改某處 import | helpers/statcast/sync 的 re-export shim 兜底；smoke test 抓 |
| 循環依賴 | 嚴守 §5 分層；smoke test 立即報 ImportError |
| 合併重複時行為改變（如 `_ratio` digits） | 呼叫端明確帶 `digits`，golden diff 證明逐字元不變 |
| `data/` DB 被動到 | 全程只跑 `build.py build`（唯讀 DB），不跑 sync/statcast/refresh；不碰 `data/tracker.sqlite3` |
| Statcast 浮點輸出細微變動 | golden diff 比 HTML；characterization test 比函式回傳值 |

### 11.3 回滾策略
- 每個 Phase = 一個獨立 git commit（甚至獨立 PR）。golden diff 不過就 `git revert` 該 commit，不影響其他 Phase。
- 因有 shim，**即使只完成前幾個 Phase 也能正常運作並上線**，可隨時暫停。

---

## 12. 分階段執行順序

風險由低到高；每個 Phase 都獨立可驗證、獨立可 ship、獨立可回滾。

| Phase | 內容 | 風險 | 驗證重點 |
|-------|------|------|----------|
| **0** | 建立安全網：golden `dist_golden`、import smoke script、純函式 characterization tests（先鎖住現狀行為） | — | 基準建立 |
| **1** | 建 `config.py` + `season_constants.py`，搬入散落常數（值不變）；api/sync/statcast/builder/jinja_env 改 import；helpers shim 保 `DEFAULT_SEASON_YEAR` | 低 | smoke + golden diff |
| **2** | 建 `util/`（obj/coerce/jsonio/numeric/units/textfmt）；搬入純工具；helpers 改 shim；jinja_env 改用 textfmt | 低 | golden diff（含 template filter 輸出） |
| **3** | 消除 §8 重複：`_ratio`→`util.numeric`、`_float_or_none`→`coerce`、`_count_label`→`textfmt`（呼叫端帶參數） | 低 | golden diff |
| **4** | `levels.py` 加 `level_case_sql()`（輸出等價）；sync 改用 | 低 | golden diff（build 不觸發，但驗證 import） |
| **5** | helpers 拆出 `stats/`（rates+aggregate）+ `roster.py`；刪 `highest_level` deadcode；helpers 改 shim | 中 | golden diff + characterization(stats) |
| **6** | `statcast.py` → `statcast/` 套件（constants/classify/extract/formulas/charts/aggregate/display）；`__init__` re-export；刪永不成立分支；合併 `{"EP","FA"}` | 中高 | golden diff + characterization(statcast) |
| **7** | builder 的 `_combine_*` → `statcast/combine.py`；消除 builder/statcast 常數與 `_ratio`/`_is_unknown` 重複 | 中高 | golden diff |
| **8** | `sync.py` → `sync/` 套件（db/mappers/common/pipeline/statcast_pipeline）；`__init__` re-export 三入口；抽 `EMPTY_PITCHES`/表名/`DB_TIMEOUT` | 中高 | smoke + （可選）對單一球員跑一次 statcast 於**複本 DB** 比對 |
| **9** | builder 拆出 `urls`/`headshots`/`player_bundle`/`seo`；jinja_env 瘦身；刪 `slice_prefix`/`site_origin` deadcode | 中 | golden diff（SEO/sitemap/robots/JSON-LD 逐字元比對） |
| **10** | 收尾：移除過渡 shim（或極簡化 helpers）、更新 `CLAUDE.md`、補測試、清 `dist_golden`/`dist_check` | 低 | 全套 smoke + golden + pytest |

> Phase 8 的 sync 因牽涉 DB 寫入，golden diff（只跑 build）無法覆蓋寫入路徑；
> 建議額外在**複製出的測試 DB** 上對單一球員跑 `statcast --player <id>`，比對 `season_stats` 該列 JSON 是否與重構前一致，再 ship。

---

## 13. code review 問題 → 重構後落點

重構**不修這些 bug**，但為每個 bug 建立乾淨、可測試的落點，讓後續修正單純：

| code review 問題（嚴重度） | 現位置 | 重構後落點 | 重構帶來的便利 |
|------|--------|-----------|----------------|
| WHIP 守護條件不對稱（高） | helpers | `stats/rates.py` | 公式獨立可單測 |
| 投手 BABIP 分母（中） | helpers | `stats/rates.py` | 同上 |
| `safe_int`/`safe_float` 不一致（中） | helpers | `util/coerce.py` | 兩者並列，一眼可對齊 |
| `ip_to_outs` 缺 clamp（中） | helpers | `util/units.py` | `util/numeric.clamp` 已備好 |
| ev90 用 nearest-rank（中高） | statcast | `statcast/aggregate.py` | 聚合邏輯獨立 |
| sweet-spot% 母體不一致（中） | statcast | `statcast/aggregate.py` | |
| barrel%/hard-hit% 分母不一致（中） | statcast | `statcast/aggregate.py` | |
| `compute_fip` 後備迴圈（中） | statcast | `statcast/formulas.py` | 公式集中 |
| 永不成立分支（低） | statcast | `statcast/aggregate.py` | **重構時直接刪** |
| `{"EP","FA"}` 重複（中） | statcast | `statcast/constants.py` | **重構時直接合併** |
| NaN 未當缺值（中） | jinja_env | `util/textfmt.py` | 一處修，所有 filter 受惠 |
| `_ratio`/`_is_unknown`/plinko 重複（中） | statcast+builder | `util/numeric`、`statcast/*` | **重構時直接去重** |
| `_combine_pitch_usage_by_count` 計數膨脹（中） | builder | `statcast/combine.py` | 聚合集中、可測 |
| `snapshot_valid` 用 today().year（中） | builder | `builder.py`（主流程） | |
| `playbyplay_processed` 只寫不讀（中） | sync | `sync/statcast_pipeline.py` + `sync/db.py` | 去重邏輯與 schema 同套件 |
| sabermetrics 寫入條件矛盾（中） | sync | `sync/statcast_pipeline.py` | merge 邏輯獨立 |
| `any([..0.0..])` 當無資料（中） | sync | `sync/statcast_pipeline.py` | |
| `EMPTY_PITCHES` 三處不一致（中） | sync | `sync/db.py` | **重構時直接統一常數** |
| level CASE 字串注入（中） | sync | `levels.level_case_sql` | **重構時直接收斂到 levels** |
| DB timeout 不一致（中） | sync | `config.DB_TIMEOUT` | **重構時直接統一** |
| `highest_level` deadcode（低） | helpers | — | **重構時直接刪** |
| `slice_prefix`/`site_origin` deadcode（低） | jinja_env | — | **重構時直接刪** |
| api v1.1 URL / timeout30 / sportId（低中） | api | `config.py` | **重構時直接抽常數** |

> 標「**重構時直接…**」者屬「值不變的純整理」，落在 §3 允許範圍內；其餘「改公式／改邏輯」者一律延後到結構穩定之後。

---

## 14. 命名慣例與檔頭模板

- **私有 helper**：保留 `_` 前綴；跨模組需被別檔 import 的，改為公開名（去 `_`）並在 `__init__`/shim re-export（如 `_prefetch_headshots` → `prefetch_headshots`）。
- **模組命名**：名詞、單一職責（`charts.py`、`formulas.py`、`mappers.py`）；避免 `utils.py`/`misc.py` 這種雜物箱名。
- **常數命名**：去除原本的 `_` 私有前綴改為語意化公開常數（`_W` → `WOBA_WEIGHTS`）。

每個新檔檔頭沿用 `levels.py` 風格：
```python
"""
<一句話職責>。

<為什麼這樣設計 / 領域背景 / 不變式>。

# 維護提示（若含常數）：[SEASONAL]/[CONFIG]/[STATIC] …
"""
```

---

## 15. 收尾

1. **移除過渡 shim**：把 builder/sync 內殘留的舊 import 全改為新路徑後，`helpers.py` 僅剩 `DEFAULT_SEASON_YEAR`。二擇一：
   - (a) 保留 4 行極簡 `helpers.py` shim（build.py 零改動）；或
   - (b) 改 build.py 為 `from site_builder.config import DEFAULT_SEASON_YEAR` 後刪除 `helpers.py`。
   建議 (a)，零風險。
2. **更新 `CLAUDE.md`**：File Organization 章節改為新結構；補「每季更新賽伯計量常數 → `season_constants.py`」「日期 filter 不存在」等與現況對齊的說明（code review 指出的文件落差）。
3. **補測試**：保留 Phase 0 的 characterization tests 作為長期回歸測試；在 §13 各 bug 修正時改為「正確值」斷言。
4. **清理**：刪 `dist_golden`/`dist_check` 暫存；確認 `.gitignore` 未誤納。

---

## 附錄 A：完整符號搬移對照表

### A.1 `statcast.py`（1,415 行）→ `statcast/` 套件
| 原符號 | 新位置 |
|--------|--------|
| `SWING_CODES`/`WHIFF_CODES`/`CALLED_STRIKE_CODES`/`WOBA_EVENT_MAP`/`_NON_PA_EVENTS` | `constants.py` |
| `_BAT_SIDE_SPLITS`/`_COUNT_USAGE_BUCKETS`/`_PLINKO_COUNTS`/`_PLINKO_EDGES`/`_BATTER_PLINKO_SPLITS`/`_PITCHER_PLINKO_SPLITS` | `constants.py` |
| `_BATTER_PLINKO_SKIP_TYPES`（+合併區域 `{"EP","FA"}`） | `constants.py`（`POSITION_PLAYER_PITCH_TYPES`） |
| `_*_TRAJECTORIES`/`_GAMEDAY_*`/`_HIT_LOCATION_ZONE`/`_BATTED_BALL_RATE_DIGITS` | `constants.py` |
| `_W`/`_WOBA_FALLBACK`/`FIP_CONSTANTS`/`LEAGUE_RA9` | `season_constants.py`（Tier 1） |
| `_is_swing`/`_is_whiff`/`_is_called_strike`/`_is_in_zone`/`_is_out_of_zone`/`_is_barrel`/`_is_sweet_spot`/`_is_unknown_pitch_type`/`_filter_known_pitch_events`/`_pre_count_tuple`/`_post_count_tuple` | `classify.py` |
| `_count_label` | `util/textfmt.py`（共用） |
| `_ratio`/`_mean`/`_mean_round` | `util/numeric.py` |
| `_float_or_none` | `util/coerce.py`（`to_finite_float`） |
| `extract_pitch_logs`/`_ensure_pre_strikes` | `extract.py` |
| `get_woba_weights`/`_compute_woba`/`compute_fip`/`compute_xwpct` | `formulas.py` |
| `_empty_plinko_nodes`/`_empty_plinko_edges`/`_compute_pitch_plinko`/`compute_pitch_movement_chart`/`_spray_direction_from_location`/`_spray_direction_from_coordinates`/`_compute_spray` | `charts.py` |
| `_aggregate_pitches`/`_discipline_metrics`/`_batted_ball_metrics`/`compute_pitcher_statcast`/`_compute_pitch_arsenal_pitcher`/`_compute_pitch_outcomes_pitcher`/`_compute_pitch_usage_by_count_pitcher`/`_compute_pitcher_bat_side_splits`/`compute_batter_statcast`/`_compute_vs_pitch_types_batter` | `aggregate.py` |
| `summarize_pitch_for_display` | `display.py` |

### A.2 `builder.py`（1,261 行）→ 多檔
| 原符號 | 新位置 |
|--------|--------|
| `_SITE_TITLE`/`_SITE_DESCRIPTION`/`_SITE_SAME_AS` | `config.py` |
| `_BAT_SIDE_SPLITS`/`_COUNT_USAGE_BUCKETS`/`_PLINKO_COUNTS`/`_PLINKO_EDGES` | 刪除（用 `statcast/constants.py`） |
| `_ratio` | 刪除（用 `util/numeric.ratio`） |
| `_is_unknown_pitch_type` | 刪除（用 `statcast/classify`） |
| `_combine_pitch_type_data`/`_combine_vs_pitch_types`/`_combine_pitch_outcomes`/`_combine_pitch_arsenal`/`_combine_pitch_usage_by_count`/`_combine_pitcher_bat_side_splits`/`_combine_pitch_plinko`/`_combine_pitch_movement`/`_combine_statcast_dicts` | `statcast/combine.py` |
| `_prefetch_headshots` | `headshots.py` |
| `_load_player_bundle`/`_player_display_name` | `player_bundle.py` |
| `_player_canonical_path`/`_player_description`/`_index_structured_data`/`_player_structured_data`/`_write_robots`/`_write_sitemap` | `seo.py` |
| `_pick_display_stat`/`build_static_site` | `builder.py`（保留） |
| `_PROJECT_ROOT` | 各檔依需要各自定義（或 config） |

### A.3 `helpers.py`（687 行）→ util / stats / roster
| 原符號 | 新位置 |
|--------|--------|
| `Obj` | `util/obj.py` |
| `safe_float`/`safe_int` | `util/coerce.py` |
| `loads_json`/`loads_json_dict`/`loads_json_list`/`dumps_json` | `util/jsonio.py` |
| `parse_date`/`ip_to_outs`/`outs_to_ip`/`height_to_cm`/`lbs_to_kg`/`_HEIGHT_RE` | `util/units.py` |
| `_fmt_avg` | `util/textfmt.py`（`fmt_avg`） |
| `DEFAULT_SEASON_YEAR` | `config.py`（helpers shim re-export） |
| `calc_obp`/`has_appearance`/`_compute_rate_stats`/`_compute_advanced_stats` | `stats/rates.py` |
| `_COUNTING_FIELDS`/`_sum_counting`/`_aggregate_stats`/`compute_career`/`compute_season_combined`/`compute_year_groups`/`annotate_computed_stats`/`highest_level_row` | `stats/aggregate.py` |
| `highest_level` | 刪除（deadcode） |
| `ROSTER_*_CODES`/`categorize_roster_status`/`is_active_player`/`_is_national_team_tx`/`_NATIONAL_TEAM_KEYWORD` | `roster.py` |
| levels re-export（`is_mlb`/`level_display`/`resolve_tier`/`sport_id_to_code`/`tier_keys_ordered`） | 刪除冗餘；僅 `level_rank` 經 shim 保留 |

### A.4 `sync.py`（1,425 行）→ `sync/` 套件
| 原符號 | 新位置 |
|--------|--------|
| `MAX_WORKERS` | `config.py` |
| `_init_db`/`_load_season_row`/`_save_season_row`/`_players_with_existing_stats`/`_warn_orphaned_players`/`_is_first_sync` | `sync/db.py` |
| `_apply_yearbyyear_fields`/`_apply_advanced_fields` | `sync/mappers.py` |
| `_build_roster_map` | `sync/common.py` |
| `_fetch_player_data`/`_write_player_to_db`/`_run_pipeline`/`sync_database`/`update_database` | `sync/pipeline.py` |
| `_fetch_and_extract_game`/`_pitches_need_hit_coord_backfill`/`_load_all_pitches_for_player`/`_merge_statcast_into_season`/`_compute_player_statcast_bundle`/`sync_statcast` | `sync/statcast_pipeline.py` |

### A.5 `jinja_env.py`（158 行）→ util/textfmt + urls + jinja_env
| 原符號 | 新位置 |
|--------|--------|
| `floatformat`/`default_if_none`/`num_dash`/`pct_fmt`/`_json_html_safe`/`tojson_safe`/`jsonld` | `util/textfmt.py` |
| `slice_prefix` | 刪除（deadcode） |
| `_make_url_helpers`/`_make_absolute_url` | `urls.py` |
| `site_origin` global | 刪除（template 未用）；`SITE_ORIGIN` 常數進 `config.py` |
| `create_jinja_env` | `jinja_env.py`（保留，瘦身為建 env + 註冊） |

### A.6 `api.py`（419 行）→ 微調
保留全部 function；僅把 `BASE_URL`/`TIMEOUT`/v1.1 URL/`timeout=30`/`days=7`/UTC+8/sportId 等抽到 `config.py`（值不變），其餘不動。

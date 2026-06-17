# site_builder 重構計畫

> 狀態：**規劃中（尚未執行）**
> 目標：依「程式分工 / 邏輯重複性」重新分類函式，讓未來維護者更容易看懂；
> 同時以 re-export shim 降低重構後程式無法運作的風險。

---

## 1. 核心目標

1. **把功能相似的函式完美分類** —— 重點是目前散落在 `helpers.py` / `jinja_env.py` /
   `statcast.py` / `builder.py` 的大量「數據轉換、單位轉換、數值運算、顯示格式化」函式。
2. **消除重複** —— 同一個函式在多檔各寫一份（見 §3）。
3. **降低風險** —— 公開 API 入口不變，舊 import 路徑用 re-export 維持相容，
   CLI (`build.py`) 完全不受影響。

---

## 2. 工具函式的分類法（本計畫重點）

把所有「不含領域知識的通用工具」收斂到 `site_builder/util/` subpackage，
依「做什麼事」分成五個明確家族。每個檔案職責單一、易讀：

```
site_builder/util/
  __init__.py     # re-export 全部公開工具，集中對外窗口
  coerce.py       # 型別安全轉換：把髒值轉成 Python 型別
  jsonio.py       # JSON 序列化 / 反序列化
  numeric.py      # 純數值運算（已是數字 → 算出數字）
  units.py        # 單位轉換（局數、身高、體重、日期等格式互轉）
  textfmt.py      # 顯示格式化（值 → 給 UI/模板看的字串）
```

### 2.1 `util/coerce.py` — 型別安全轉換
| 函式 | 來源 | 備註 |
|------|------|------|
| `safe_float` | helpers | 不變 |
| `safe_int` | helpers | 不變 |
| `to_finite_float` | statcast `_float_or_none` | 與 `safe_float` 合併概念：在 `safe_float` 基礎上加 `math.isfinite` 檢查；statcast 改呼叫此函式 |

### 2.2 `util/jsonio.py` — JSON 序列化
| 函式 | 來源 |
|------|------|
| `loads_json` / `loads_json_dict` / `loads_json_list` | helpers |
| `dumps_json` | helpers |

### 2.3 `util/numeric.py` — 純數值運算
| 函式 | 來源 | 備註 |
|------|------|------|
| `ratio(num, den, digits=3)` | statcast `_ratio` + builder `_ratio` | **合併兩份**；位數一律用參數帶入（statcast 多為 3、builder combine 多為 4），呼叫端明確指定，行為不變 |
| `mean` | statcast `_mean` | 不變 |
| `mean_round` | statcast `_mean_round` | 不變 |

### 2.4 `util/units.py` — 單位 / 格式互轉
| 函式 | 來源 | 備註 |
|------|------|------|
| `ip_to_outs` / `outs_to_ip` | helpers | 棒球局數 ↔ outs |
| `height_to_cm` | helpers | 身高字串 → 公分 |
| `lbs_to_kg` | helpers | 磅 → 公斤 |
| `parse_date` | helpers | ISO 字串 → `date` |

### 2.5 `util/textfmt.py` — 顯示格式化
| 函式 | 來源 | 備註 |
|------|------|------|
| `fmt_avg` | helpers `_fmt_avg` | 打擊率字串（去前導 0） |
| `floatformat` / `default_if_none` / `num_dash` / `slice_prefix` / `pct_fmt` | jinja_env | 格式化邏輯移此；`jinja_env.py` 改 import 後註冊為 filter |
| `count_label` | statcast `_count_label` | `(b,s)` → `"B-S"` |
| `json_html_safe` / `tojson_safe` / `jsonld` | jinja_env | HTML-safe JSON 內嵌；同樣由 jinja_env import 後註冊 |

> 注意：`calc_obp`、`has_appearance` **不歸工具層**——它們含棒球統計語意，
> 留在統計領域（見 §4 `stats.py`）。`_is_unknown_pitch_type` 屬 statcast 領域判斷，
> 歸 statcast（見 §3）。

---

## 3. 待消除的重複（風險最低、收益最高，建議第一步先做）

| 重複函式 | 出現位置 | 處理 |
|----------|----------|------|
| `_ratio` | `statcast.py`、`builder.py` | 統一到 `util/numeric.ratio`，兩處改 import；保留 digits 參數確保行為一致 |
| `_is_unknown_pitch_type` | `statcast.py`、`builder.py` | 內容完全相同 → 收斂到 statcast（如 `statcast/constants.py` 或 `extract.py`），builder 改 import |
| `_float_or_none` vs `safe_float` | statcast vs helpers | 合併為 `util/coerce.to_finite_float` |
| `_BAT_SIDE_SPLITS` / `_COUNT_USAGE_BUCKETS` / `_PLINKO_COUNTS` / `_PLINKO_EDGES` | `statcast.py`、`builder.py` 各定義一份（格式略不同：statcast 用 tuple count、builder 用字串 count） | 評估能否共用同一份來源；若格式必須不同，至少集中到 `statcast/constants.py` 並加註說明 |

---

## 4. 整體目錄結構（含領域層）

工具層之外，其餘依「層」拆分；最大的 statcast 領域開一個 subpackage。

```
site_builder/
  __init__.py

  # ── 設定 / 常數層（§7）──
  config.py               # 部署/站台/執行設定（偶爾更新）：BASE_URL、TIMEOUT、MAX_WORKERS、
                          # SITE_TITLE/DESCRIPTION/SAME_AS、SITE_ORIGIN、DEFAULT_SEASON_YEAR
  season_constants.py     # ⚠️ 每季必更新的賽伯計量常數：WOBA_WEIGHTS、WOBA_FALLBACK、
                          # FIP_CONSTANTS、LEAGUE_RA9（休賽季維護單一入口）

  # ── 外部 API 層 ──
  api.py                  # (不動) MLB Stats API client；sport 對照表留此

  # ── 通用工具層（§2）──
  util/
    __init__.py
    coerce.py
    jsonio.py
    numeric.py
    units.py
    textfmt.py

  # ── 統計 / 領域轉換層 ──
  stats.py                # calc_obp、has_appearance、_sum_counting、_compute_rate_stats、
                          # compute_career、compute_season_combined、_compute_advanced_stats、
                          # annotate_computed_stats、compute_year_groups、SPORT_LEVEL_ORDER、_COUNTING_FIELDS
  roster.py               # ROSTER_*_CODES 常數 + categorize_roster_status
                          #（亦可併入 stats.py，避免過多小檔——二擇一）

  # ── Statcast 領域 (subpackage) ──
  statcast/
    __init__.py           # re-export 既有公開 API → sync/builder 的 import 不用改
    constants.py          # code 集合、wOBA 權重、FIP 常數、plinko/trajectory/gameday 定義、_is_unknown_pitch_type
    extract.py            # extract_pitch_logs、_ensure_pre_strikes、分類函式(_is_swing…)
    charts.py             # plinko / movement / spray 圖表資料
    aggregate.py          # _aggregate_pitches、discipline/batted-ball、投手/打者季 statcast
    formulas.py           # get_woba_weights、compute_fip、compute_xwpct、summarize_pitch_for_display
    combine.py            # 跨等級 _combine_*（從 builder.py 搬來）

  # ── 持久化 / 同步層 ──
  db.py                   # _init_db/migration、_load_season_row、_save_season_row、
                          # _players_with_existing_stats、_is_first_sync
  mappers.py              # _apply_yearbyyear_fields、_apply_advanced_fields
  sync.py                 # 球員抓取寫入 pipeline（sync_database / update_database）
  statcast_sync.py        # statcast 同步 pipeline（sync_statcast）

  # ── 渲染層 ──
  jinja_env.py            # (邏輯移至 util/textfmt 後) 只負責建 env + 註冊 filter/global
  seo.py                  # 結構化資料、sitemap、robots、站台 metadata 常數
  builder.py              # build_static_site 主流程 + _load_player_bundle + _prefetch_headshots
```

依賴方向（單向往下，無循環）：
`config/season_constants → api → util → stats/roster → statcast → db/mappers → sync/statcast_sync → seo/jinja_env → builder`

---

## 5. 風險控制策略

1. **公開入口不動**：`sync_database` / `update_database` / `sync_statcast` /
   `build_static_site` 簽名與行為不變。`build.py` 不需修改。
2. **re-export shim**：
   - `statcast/__init__.py` re-export 所有原 `statcast.py` 對外函式，
     使 `from site_builder.statcast import compute_pitcher_statcast` 等照常運作。
   - 若擔心外部引用 `helpers.py`，可在 `helpers.py` 暫時 `from .util.xxx import *`
     做過渡相容，之後再逐步移除。
3. **純搬移、不改邏輯**：本次重構只「移動 + 改 import + 合併重複」，
   不改任何計算公式；合併重複時用參數保留原行為。
4. **每步可驗證**：每完成一層搬移就跑 `python build.py build`，
   比對輸出 HTML 與重構前一致（可先備份一份 `dist/` 做 diff）。

---

## 6. 建議執行順序（風險由低到高）

1. 建 `util/` 並搬入無爭議的純工具（coerce/jsonio/numeric/units/textfmt），各原檔改 import。
2. 消除 §3 的重複函式（`_ratio`、`_is_unknown_pitch_type`、`_float_or_none`）。
3. `helpers.py` 拆出 `stats.py`（+ `roster.py`）。
4. 拆 `statcast/` subpackage（constants/extract/charts/aggregate/formulas），`__init__` re-export。
5. 把 `builder.py` 的 `_combine_*` 搬到 `statcast/combine.py`。
6. `sync.py` 拆出 `db.py` / `mappers.py` / `statcast_sync.py`。
7. `builder.py` 拆出 `seo.py`；`jinja_env.py` 改用 `util/textfmt`。
8. 每步後跑 `python build.py build` 驗證輸出不變。

> 常數的搬移（§7）建議併入對應步驟：`config.py` / `season_constants.py` 可在
> 第 1 步一起建立（風險最低）；statcast 結構性常數隨第 4 步進 `statcast/constants.py`。

---

## 7. 常數管理策略（重點）

目前常數散落 6 個檔、且有重複（如 plinko/split 常數在 statcast 與 builder 各一份）。
依「**維護頻率**」分三層管理，讓 contributor 一眼知道「哪些要定期改、去哪改」。

### 7.1 Tier 1 — 每季/每年必更新 → 集中到 `season_constants.py`

把所有「年份相關、休賽季要維護」的賽伯計量常數收進**單一檔**，檔頭寫清楚更新步驟與來源。
這是本策略最關鍵的一步：維護者只需打開這一個檔。

| 常數 | 原位置 | 新名稱（建議） |
|------|--------|----------------|
| `_W` | statcast | `WOBA_WEIGHTS` |
| `_WOBA_FALLBACK` | statcast | `WOBA_FALLBACK` |
| `FIP_CONSTANTS` | statcast | `FIP_CONSTANTS` |
| `LEAGUE_RA9` | statcast | `LEAGUE_RA9` |

`statcast/formulas.py`、`statcast/aggregate.py` 改 `from site_builder.season_constants import ...`。

建議檔頭範例：

```python
"""
賽伯計量常數 —— 每年球季結束後需更新。

更新清單（每季）：
  1. WOBA_WEIGHTS：到 FanGraphs guts (https://www.fangraphs.com/guts.aspx?type=cn)
     複製新年份的 wBB/wHBP/w1B/w2B/w3B/wHR，新增一列。
  2. FIP_CONSTANTS：計算或查詢各 level 新年份的 FIP constant，新增 (level, year) 項。
  3. LEAGUE_RA9：校正各 level 的聯盟 RA/9 基準（變動小，可隔年檢查一次）。
"""
```

> `DEFAULT_SEASON_YEAR` 放 `config.py`（與部署/環境變數相關），但在
> `season_constants.py` 檔頭備註「新年份記得同步更新 config 的 DEFAULT_SEASON_YEAR」。

### 7.2 Tier 2 — 偶爾更新 → 集中到 `config.py`

部署、站台與執行參數放 `config.py`，contributor 改站名/網址/併發數時只看這檔：

| 常數 | 原位置 |
|------|--------|
| `BASE_URL`、`TIMEOUT` | api |
| `MAX_WORKERS` | sync |
| `SITE_TITLE`、`SITE_DESCRIPTION`、`SITE_SAME_AS`、`SITE_ORIGIN` | builder / jinja_env |
| `DEFAULT_SEASON_YEAR` | helpers |

例外：`ROSTER_*_CODES`、`_SPORT_ID_MAP/_SPORT_NAME_TO_ABBR` 雖偶爾更新，但語意上
分別屬 roster 與 api 領域，**留在各自領域檔**（`roster.py` / `api.py`），不進 `config.py`，
避免 config 變成雜物箱。

### 7.3 Tier 3 — 結構性、幾乎不動 → 隨領域、去重、加標籤

這些綁定演算法邏輯，改它們等於改演算法，因此**留在領域旁**，但要求：
1. **每個來源只留一份**（消除 statcast/builder 的重複定義，見 §3）。
2. 統一收在各領域的 `constants.py`，集中而非散在函式之間。

| 常數群 | 歸屬 |
|--------|------|
| `SWING_CODES`、`WHIFF_CODES`、`CALLED_STRIKE_CODES`、`WOBA_EVENT_MAP`、`_NON_PA_EVENTS` | `statcast/constants.py` |
| `_PLINKO_*`、`_COUNT_USAGE_BUCKETS`、`_BAT_SIDE_SPLITS`、`_*_PLINKO_SPLITS`、`_BATTER_PLINKO_SKIP_TYPES` | `statcast/constants.py` |
| `_*_TRAJECTORIES`、`_GAMEDAY_*`、`_HIT_LOCATION_ZONE`、`_BATTED_BALL_RATE_DIGITS` | `statcast/constants.py` |
| `SPORT_LEVEL_ORDER`、`_COUNTING_FIELDS` | `stats.py` |
| `_HEIGHT_RE` | `util/units.py`（緊鄰 `height_to_cm`）|

### 7.4 共同慣例（讓常數「易找易維護」）

- 每個常數區塊上方加一行 cadence 標籤註解，例如：
  `# [SEASONAL] 每年更新` / `# [CONFIG] 偶爾更新` / `# [STATIC] 綁定邏輯，勿隨意改`。
- 模組內常數一律集中在檔案頂部（import 之後），不散落於函式之間。
- 在 `CLAUDE.md` 的「Updating Stat Formulas / Common Workflows」加一句指引：
  「每季更新賽伯計量常數 → 只改 `site_builder/season_constants.py`」。
</content>

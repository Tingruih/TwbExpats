# TODO — 代碼改進清單

> 根據完整 code review 整理，依優先度排列。

---

## 🔴 Bug 修正（直接影響資料正確性）

- [ ] **`api.py:121`** — MiLB 端點未包 `try/except`
  - `get_player_stats()` 的 MiLB 請求若發生網路錯誤，會直接拋出例外導致球員歷史 MiLB 資料靜默丟失
  - 修正：與上方 MLB 端點相同，包入 `try/except Exception as e: logger.warning(...)`

- [ ] **`helpers.py:269`** — `compute_season_combined` 缺少 `_compute_advanced_stats`
  - 跨層級（MLB + MiLB）球員的合計賽季列中，ISO、BABIP、K%、BB% 等進階統計全為 `None`
  - `compute_year_groups`（第 559 行）有正確呼叫，但 `compute_season_combined` 在 `_aggregate_stats` 後直接回傳，漏掉這步
  - 修正：在 `compute_season_combined` 回傳前加入 `_compute_advanced_stats(combined)`

- [ ] **`statcast.py:541`** — 開關打者被錯誤計為左打
  - 擊球方向判斷使用 `bat != "R"`，開關打者（`"S"`）被歸類為左打
  - 修正：改為 `bat == "L"`

- [ ] **`statcast.py:554`** — EV90 計算索引 off-by-one
  - 樣本數 < 10 時，`int(len * 0.1) - 1` 產生 `-1`，`max(0, -1)` 掩蓋問題並回傳最大值
  - 修正：`idx = int(len(ev_values) * 0.1)`（移除 `- 1`）

---

## 🔴 錯置的 Functions（概念歸屬錯誤）

- [ ] **`api.py` → `helpers.py`**：`parse_roster_from_file()`
  - 讀取本機 JSON 檔案，與 MLB API 無關，不應在 `api.py` 中
  - 移至 `helpers.py`，並更新所有 import

- [ ] **`builder.py` → `statcast.py`**：`_combine_pitch_type_data()` / `_combine_vs_pitch_types()` / `_combine_pitch_arsenal()` / `_combine_statcast_dicts()`
  - 四個 function 都是 Statcast 數據的加權平均合併運算，屬於計算層邏輯
  - 目前放在 `builder.py` 只因在建置時使用，但計算邏輯應與 HTML 建置分離
  - 移至 `statcast.py`，並更新 `builder.py` 的 import

- [ ] **`statcast.py` → `builder.py`**：`summarize_pitch_for_display()`
  - 函式名稱就帶 "for_display"，只在 `builder.py` 中被 import 和使用
  - 屬於展示層邏輯，不應依賴 `statcast.py`
  - 移至 `builder.py`，切斷不必要的跨模組依賴

- [ ] **`helpers.py` → `jinja_env.py`**：`height_to_cm()` / `lbs_to_kg()`
  - 這兩個是單位換算 function，只在 `builder.py` 組建 template context 時使用
  - 應移至 `jinja_env.py` 作為 Jinja2 filter，讓 template 直接使用

- [ ] **`helpers.py` → `jinja_env.py`**：`_fmt_avg()`
  - 格式化 float 為 ".333" 格式字串，屬於展示層關切
  - 目前混入 `_compute_advanced_stats` 計算邏輯中，職責混雜
  - 移至 `jinja_env.py` 並作為 `avg_fmt` filter 注入

---

## 🟡 重複邏輯（可合併或刪除）

- [ ] **`builder.py:308`** — ISO 計算與 `helpers.py` 重複
  - `_load_player_bundle` 中手動計算 `data.iso = slg - avg`
  - `helpers.py:_compute_advanced_stats:332` 後來也會計算（有 None 守衛）
  - 修正：刪除 `builder.py` 那行，讓 `annotate_computed_stats` 統一處理

- [ ] **`statcast.py`** — Put Away% 計算在投手/打者路徑各寫一次
  - `_compute_pitch_arsenal_pitcher`（第 482-488 行）和 `_compute_vs_pitch_types_batter`（第 630-634 行）的 Put Away% 邏輯完全相同
  - 修正：抽出共用私有 function `_compute_put_away_pct(pitches_for_type)`

- [ ] **`jinja_env.py`** — `default_if_none` 和 `num_dash` 功能高度重疊
  - `default_if_none(v, fallback)`: None → fallback
  - `num_dash(v)`: None 或空字串 → "-"
  - 修正：合併為 `num_dash(value, fallback="-")` 一個 function

- [ ] **Sport level 對照表分散在三處**
  - `api.py:_SPORT_ID_MAP`（id → 縮寫）
  - `api.py:_SPORT_NAME_TO_ABBR`（名稱 → 縮寫）
  - `helpers.py:SPORT_LEVEL_ORDER`（縮寫 → 排序值）
  - 修正：集中定義於 `helpers.py`，`api.py` 改為 import

---

## 🟡 可維護性改善

- [ ] **`sync.py`（1218 行）職責過多，應拆分為三個模組**
  - `db.py`：`_init_db`, `_load_season_row`, `_save_season_row`（DB schema 與 CRUD）
  - `sync.py`：`_apply_yearbyyear_fields`, `_apply_advanced_fields`, `_fetch_player_data`, `_write_player_to_db`, `_run_pipeline`, `sync_database`, `update_database`（一般資料同步）
  - `statcast_sync.py`：`_build_roster_map`, `_fetch_and_extract_game`, `_load_all_pitches_for_player`, `_merge_statcast_into_season`, `sync_statcast`（Statcast 專屬同步）

- [ ] **`build_static_site`（`builder.py`，227 行）應拆分**
  - 球員詳細頁的 context 組建邏輯（第 426-561 行）應抽出為 `_build_player_context(player, all_stats, all_logs, year) -> dict`
  - 讓主流程只剩資源複製、template render、檔案寫入

- [ ] **`helpers.py:Obj.__getattr__` 靜默吞掉欄位名稱 typo**
  - 任何拼錯的欄位（如 `stat.eras`）回傳 `None` 而不拋出 `AttributeError`，造成 template 空白難以 debug
  - 可考慮在 debug 模式下加入 warning log，或在開發環境中改為嚴格模式

- [ ] **`builder.py:465`** — `next_game` 有效性判斷邏輯有誤
  - `(player.next_game_for_season or 0) >= datetime.date.today().year` 對未來任何賽季都為 True，可能顯示舊的未來賽季資料
  - 修正：改為 `== datetime.date.today().year`

- [ ] **UTC+8 硬編碼重複出現兩處**
  - `api.py:242` 和 `builder.py:364` 各有一個 `datetime.timezone(datetime.timedelta(hours=8))`
  - 修正：在 `helpers.py` 定義 `TW_TZ = datetime.timezone(datetime.timedelta(hours=8))` 並 import 使用

- [ ] **`sync.py:_build_roster_map` 只有一行實質內容，應 inline 或刪除**
  - `return {p["mlb_id"]: p for p in parse_roster_from_file(roster_file)}` 只在 `sync_statcast` 中呼叫一次，可直接 inline

---

## 🟡 網頁效能

- [ ] **`player_detail.j2` 中約 225 行 JS 應抽出為獨立檔案**
  - 目前內嵌在 template 中，無法被瀏覽器快取
  - 抽出為 `src/static/js/player_detail.js`，讓第二個球員頁面命中快取
  - 涉及：`toggleYearGroup()`、gamelog 年度切換、`_buildPitchTable()` / `togglePitchLog()`、arsenal 切換、Chart.js 初始化、tab system

- [ ] **`index.j2` 中的 `sortCards()` 應抽出為獨立檔案**
  - 移至 `src/static/js/index.js`

---

## 🟢 Dead Code / 設定缺陷（低優先度）

- [ ] **刪除 `ztest.py`（135 行）**
  - 全部是早期探索 pybaseball 的腳本，與正式 pipeline 無關，可安全刪除

- [ ] **`sync.py:87`** — UNIQUE 約束對同年同球隊不同層級可能碰撞
  - `UNIQUE(player_mlb_id, year, team_name)` 在同球員同年同球隊名稱但不同層級（如 optioned + recalled）時會碰撞
  - 修正：改為 `UNIQUE(player_mlb_id, year, team_name, sport_level)`

- [ ] **`statcast.py:62`** — `FIP_CONSTANTS` 只有 2024 年資料，歷史年份靜默使用錯誤常數
  - 2022–2023 年球員資料會靜默使用 2024 年常數
  - 修正：在 `compute_fip` 的 fallback 路徑加入 `logger.warning()`，提示使用非對應年份的常數



我現在要你優化vs球種分析 把層級改為下拉式選單 預設為all levels 接著增加對戰的左右手數據差別 如果是投手的話就是左打右打 打者變是左投雨右投 預設為 All 


計算$[T]_\beta$時，為何可以透過標準矩陣 $A$ 去做 $B^{-1}AB$ 的組合運算

9個人分





已擷取 3 個資源



已擷取 https://tjstats.ca/glossary/

以下是完整整理：

---

## 一、Park Factors 表（每支球隊，每年）

表格共 9 欄：

| 欄位 | 說明 |
|------|------|
| Team | 球隊名 |
| League | 所屬聯盟 |
| Home G | 主場場次 |
| Road G | 客場場次 |
| `pf_raw_1y` | 今年原始 Park Factor |
| `pf_raw_3y` | 3 年原始均值 |
| `pf_wgt_3y` | 3 年加權（近年 3:2:1 权重） |
| `pf_reg_3y` | 3 年加權後往 1.00 回歸 50% |
| **`pf_reg_wgt_3y`** | **最終使用值**，用於 wOBA+ 和 TJBat+ |

---

## 二、League Constants 表（每個聯盟，每年）

每筆按 **level + 聯盟** 分開（例如 AAA 拆成 International League / Pacific Coast League）：

| 欄位 | 2026 MLB AL 值 | 2026 MLB NL 值 | 說明 |
|------|--------------|--------------|------|
| PA | 8,089 | 7,804 | 樣本打席數 |
| `lg_wOBA` | 0.313 | 0.309 | 聯盟平均 wOBA |
| `lg_OBP` | 0.324 | 0.318 | 聯盟平均 OBP |
| `lg_R/PA` | 0.118 | 0.118 | 每打席得分率 |
| `woba_scale` | **1.240**（固定） | **1.240**（固定） | wOBA → 得分的換算係數 |

---

## 三、TJStats 固定 wOBA 線性權重（全層級、全年通用）

| 事件 | 權重 |
|------|------|
| BB（四壞） | 0.689 |
| HBP（觸身） | 0.720 |
| 1B（一壘安） | 0.881 |
| 2B | 1.254 |
| 3B | 1.589 |
| HR | 2.048 |
| IBB, 犧牲觸擊, Out | 0（不計） |

> ⚠️ **與我們現有代碼的差異**：目前 statcast.py 使用的是 FanGraphs **每年不同**的權重（`_W` dict），TJStats 用的是**全年份固定**權重。兩者計算出的 wOBA 會有微小差異。

---

## 四、可計算的數據

### wOBA+（球場與聯盟中性的打擊率）

$$\text{wOBA+} = 100 \times \frac{\text{wOBA} / \text{PF}}{\text{lg\_wOBA}}$$

- 需要：球員 wOBA、球隊 `pf_reg_wgt_3y`、所在聯盟 `lg_wOBA`
- 100 = 聯盟平均，120 = 比平均好 20%

---

### TJBat+（等同 wRC+，全調整後得分貢獻）

$$\text{PF}_m = 1 + (\text{PF} - 1) \times 0.5$$

$$\text{wRC/PA} = \frac{\text{wOBA} - \text{lg\_wOBA}}{\text{woba\_scale}} + \text{lg\_R/PA}$$

$$\text{TJBat+} = 100 \times \frac{\text{wRC/PA} \div \text{PF}_m}{\text{lg\_R/PA}}$$

- 需要：wOBA、PF、`lg_wOBA`、`lg_R/PA`、`woba_scale`（固定 1.24）
- 比 wOBA+ 更精確，因為還原到「得分」尺度（非線性放大效果）

---

## 五、對現有代碼的影響

| 現有代碼 | 需要補充的資料 |
|---------|-------------|
| statcast.py 計算 wOBA，但用 FanGraphs 年份權重 | 若要與 TJStats 對齊，需改為固定權重 |
| `FIP_CONSTANTS` 只有 level，無 park factor | Park Factor 需加入 `(team, year)` 的對應表 |
| `LEAGUE_RA9` 用 level 分 | TJStats 更細：同 level 不同聯盟值不同（PCL vs IL 差距很大） |
| statcast.py 無 wOBA+ / TJBat+ | 需引入 park factors + league constants 才能算 |

實作時，最直接的方式是：把 TJStats 這張表存成 tjstats_league_constants.csv（你的 repo 已有這個檔案！）以及新增一個 `data/tjstats_park_factors.csv`，然後在 statcast.py 或 helpers.py 讀入做 lookup。
# 聯盟層級邏輯統一化 — 設計文件

- **日期**：2026-06-20
- **狀態**：設計完成，待實作
- **核心目標**：把**所有** MLB/MiLB 層級邏輯收進**單一模組**統一處理，廢除目前散落的多張常數表；全站所有 level-badge / 層級標籤 / 篩選器都走**同一套顯示邏輯**。
- **不影響**：SQLite 資料（零遷移）、統計計算、JS 邏輯（JS 不需改）。

---

## 1. 問題陳述

同一個聯盟層級在系統裡有**多套互不正規化的字串來源與常數表**，散落在 `api.py`、`helpers.py`、`sync.py`、模板、JS 各處，導致卡片 badge 與資料表內顯示「完全不相同」。以真實資料庫驗證：

| # | 來源 | 取值方式 | DB 內實際值 | 問題 |
|---|------|----------|-------------|------|
| 1 | `players.level`（卡片/hero badge） | 最近一季的**原始** `sport_level`（`sync.py:645`） | 多為正規碼，退役球員殘留 `A(Short)`、`A(Adv)`、`A(Full)`、`Minors` | 跟著最近一季原始拼法走 |
| 2 | `season_stats.sport_level`（賽季/進階/守備表） | API 原始 `sport.abbreviation` | `A(Adv)`、`A(Full)`、`A(Short)`、含空格的 `A (Adv)`/`A (Short)`/`A (Full)`、`ROA` | 歷史拼法裸露、空格變體並存 |
| 3 | `game_logs.sport_level`（逐場表） | `sport_obj_to_abbr()`／sportId 推導 | 正規化後的 `A-`、`A+`、`A`、`ROK` | **與 #2 同一球季拼法不同**：2019 短期 A 在賽季表是 `A(Short)`，逐場表是 `A-` |

**散落的常數表 / 函式（這次要整併消滅）：**
- `api.py`：`_SPORT_ID_MAP`（sportId → 代碼），且 `sportId 17` 誤標為 `ROK`（官方 API 現為 Winter Leagues）。
- `helpers.py`：`SPORT_LEVEL_ORDER`、`LEVEL_ALIASES`、`canonical_level`、`level_rank`、`highest_level`。
- `sync.py`：`line 642` 又用 `SPORT_LEVEL_ORDER` 自組一段 SQL `CASE` 排序。
- 模板：30+ 處各自用 `{{ x.sport_level }}` / `{{ player.level }}` 直出原始值。

**根因**：沒有單一真相來源；「排序用的正規化」與「顯示用的字串」被混為一談；多張表分開維護而漂移。

---

## 2. 參考統整：改革前後所有層級、代碼、稱呼、層級高低

2020–21 年 MLB 接管小聯盟（160→120 隊，每母隊 4 個農場）。**層級高低從未改變，只有名稱改動與短期層級裁撤**。已用官方 `/api/v1/sports` 端點核對。

| 階層 | sportId | 官方名（現） | 官方名（改革前） | 現代代碼 | DB 內歷史拼法 | tier key | rank |
|------|---------|--------------|------------------|----------|----------------|----------|------|
| 大聯盟 | 1 | Major League | （不變） | `MLB` | `MLB` | `MLB` | 0 |
| 三A | 11 | Triple-A | （不變） | `AAA` | `AAA` | `AAA` | 1 |
| 二A | 12 | Double-A | （不變） | `AA` | `AA` | `AA` | 2 |
| 高階一A | 13 | High-A | Class A-Advanced | `A+` | `A(Adv)` / `A (Adv)` | `A+` | 3 |
| 一A | 14 | Single-A (Low-A) | Class A (full-season) | `A` | `A(Full)` / `A (Full)` | `A` | 4 |
| 短期一A | ~~15~~（已裁撤） | — | Class A Short Season | （pre-2021 限定） | `A(Short)` / `A (Short)` / `A-` | `A-` | 5 |
| 新人聯盟 | 16 | Rookie / Complex | Rookie + Rookie-Adv | `ROK` | `ROK` / `ROA` / `Rk` | `ROK` | 6 |
| Winter Leagues | 17 | Winter Leagues | — | `WIN` | （未追蹤） | `WIN` | 7 |
| （彙總層） | 21 | Minor League | — | `Minors` | `Minors` | `Minors` | 99 |

改革三個關鍵動作：① High-A／Low-A **改名**（層級不變）；② 短期一A（A-）**整層裁撤**（只存在於 2020 含以前）；③ Rookie-Advanced **併入** Rookie/Complex。年代分界＝**2021 賽季**（2020 因疫情無小聯盟賽季，DB 中 `A+` 起於 2021、`A(Adv)` 止於 2019，分界乾淨）。

---

## 3. 設計決策（已與使用者確認）

| 決策 | 選擇 |
|------|------|
| 邏輯位置 | **全部收進單一新模組 `site_builder/levels.py`**，其餘常數表全部刪除並改 import |
| 全站 badge | 所有 level 顯示點（含兩種 badge 樣式與篩選器）**一律走同一函式** |
| 顯示用語 | 純英文代碼（無中文、無雙語） |
| 改革前舊賽季 | **保留當年原名**（2019 顯示 `A(Adv)`，不改寫成 `A+`）→ 推論出顯示函式必須吃 `year` |
| 短期一A 顯示字串 | `A(Short)` |
| 資料遷移 | 不做（DB 維持原始值，可逆、零風險） |

---

## 4. 單一真相來源：`site_builder/levels.py`

新增**一個模組**，成為全專案唯一的層級知識來源。內含一張 registry 與一組純函式；其他檔案一律 import，不得再自帶常數表。

### 4.1 Registry（唯一一張表）

以「tier」為單位，每個 tier 一筆，集中描述其 sportId、rank、現代代碼、改革前名稱、以及所有原始拼法別名：

```python
@dataclass(frozen=True)
class Tier:
    key: str            # 正規 tier key，例 "A+"
    rank: int           # 層級高低，數字小=層級高
    sport_ids: tuple    # 對應的 MLB sportId
    modern: str | None  # 2021+ 顯示字串（None=該 tier 已裁撤）
    legacy: str         # 2020- 顯示字串
    aliases: tuple      # 所有會在 DB/API 出現的原始拼法

TIERS = [
    Tier("MLB",    0,  (1,),     "MLB",    "MLB",      ("MLB",)),
    Tier("AAA",    1,  (11,),    "AAA",    "AAA",      ("AAA",)),
    Tier("AA",     2,  (12,),    "AA",     "AA",       ("AA",)),
    Tier("A+",     3,  (13,),    "A+",     "A(Adv)",   ("A+", "A(Adv)", "A (Adv)")),
    Tier("A",      4,  (14,),    "A",      "A(Full)",  ("A", "A(Full)", "A (Full)")),
    Tier("A-",     5,  (15,),    None,     "A(Short)", ("A-", "A(Short)", "A (Short)")),
    Tier("ROK",    6,  (16,),    "ROK",    "ROK",      ("ROK", "ROA", "Rk", "Rookie")),
    Tier("WIN",    7,  (17,),    "WIN",    "WIN",      ("WIN",)),
    Tier("Minors", 99, (21,),    "Minors", "Minors",   ("Minors",)),
]
```

由 `TIERS` 在模組載入時建出兩張查找索引：`_BY_ALIAS`（raw → Tier）、`_BY_SPORT_ID`（sportId → Tier）。**這修正了 `sportId 17` 的 bug**（不再誤判為 ROK）。

### 4.2 公開 API（全站唯一入口）

| 函式 | 用途 | 行為 |
|------|------|------|
| `resolve_tier(raw) -> Tier \| None` | 內部：把任何原始拼法解析為 tier | 查 `_BY_ALIAS`；未知回 `None` |
| `level_rank(raw) -> int` | **排序／比較／最高層級**的鍵 | tier.rank；未知回 50；跨年代收斂（`A(Adv)` 與 `A+` 同為 3） |
| `level_display(raw, year) -> str` | **所有畫面顯示**的字串 | 見 §4.3，吃 year 決定年代名稱；sentinel/未知原樣回傳 |
| `is_mlb(raw) -> bool` | hero badge 的 MLB 特別樣式判斷 | `resolve_tier(raw).key == "MLB"` |
| `sport_id_to_code(sport_id) -> str` | api.py 取 currentTeam / 逐場層級存入 DB | `tier.modern or tier.legacy`（對已裁撤的 15 回 `A(Short)` 而非空字串；顯示端仍會再正規化，故存入的原始值不影響一致性） |
| `tier_keys_ordered() -> list[str]` | sync.py SQL `CASE` 排序 | 依 rank 排好的 tier key 清單，取代 `SPORT_LEVEL_ORDER.items()` |

`highest_level` 由 helpers 移入本模組（或改為呼叫本模組）：回傳「最高層級那一筆 stat row」，讓呼叫端能同時拿到 `(sport_level, year)` 供 `level_display`（見 §6 退役 badge）。

### 4.3 `level_display(raw, year)` 規則

1. **Sentinel 直通**：`raw` ∈ {`""`, `None`, `_combined`, `_all`} → 原樣回傳（篩選器哨兵值不可動）。
2. `tier = resolve_tier(raw)`；解析不到 → 原樣回傳 `raw`（防呆）。
3. `era = "modern" if (year and year >= 2021) else "legacy"`。
4. 回傳 `tier.modern`（era=modern 且非 None）否則 `tier.legacy`。短期一A `modern=None`，永遠回 `A(Short)`。

對照範例（**全站任一顯示點都套這條**）：

| raw | year | 輸出 | 場景 |
|-----|------|------|------|
| `A(Adv)` | 2019 | `A(Adv)` | 賽季表，原名統一拼法 |
| `A (Adv)` | 2003 | `A(Adv)` | 去空格變體 |
| `A+` | 2019 | `A(Adv)` | 逐場表現代代碼 → 當年原名 |
| `A+` | 2023 | `A+` | 現代季維持代碼 |
| `A-` | 2019 | `A(Short)` | 逐場 `A-` ↔ 賽季 `A(Short)` 統一 |
| `A(Short)` | 2018 | `A(Short)` | 賽季表原名 |
| `ROA` | 2019 | `ROK` | Rookie-Adv 併入 Rookie |
| `_combined` | — | `_combined` | 哨兵直通 |
| `MLB` | 任意 | `MLB` | 不變 |

**為什麼吃 year**：game_logs 存現代代碼、season_stats 存當年原名；兩者各自呼叫 `level_display(raw, year)` 後都會落到「同 tier + 同 year」→ 輸出相同字串。這是讓賽季表、逐場表、卡片 badge 對同一球季顯示一致的關鍵。

---

## 5. 整併：刪除與改接

| 檔案 | 動作 |
|------|------|
| `site_builder/levels.py` | **新增**，§4 全部內容 |
| `helpers.py` | 刪 `SPORT_LEVEL_ORDER`、`LEVEL_ALIASES`、`canonical_level`、`level_rank`；改 `from .levels import level_rank, level_display, highest_level, ...`（或直接 re-export 維持既有 import 路徑） |
| `api.py` | 刪 `_SPORT_ID_MAP`；`current_team_level` 與 `sport_obj_to_abbr` 改用 `levels.sport_id_to_code` |
| `sync.py` | `line 642` 的 `SPORT_LEVEL_ORDER.items()` 改用 `levels.tier_keys_ordered()`；其餘 import 改指向 levels |
| `builder.py` | `SPORT_LEVEL_ORDER` / `level_rank` / `highest_level` import 改指向 levels |
| `jinja_env.py` | 註冊 filter `level_display`（包 `levels.level_display`）；可選註冊 `is_mlb` |

---

## 6. 全站 level 顯示點清單（全部改走 `level_display`）

掃描結果，共 **3 類顯示**散落在 17 個模板。**每一處都改為 `{{ raw | level_display(year) }}`**，並確保該處 `year` 在 scope 內（builder 需隨資料帶出對應年份）。

### A. `.level-tag` 小標籤（賽季/進階/守備表）
桌機：`tab_stats.j2:34,76`、`tab_advanced.j2:38,84,164,226,279`、`tab_fielding.j2:22`
行動：`m_stats.j2:19,75`、`m_advanced.j2:72,88,120,176,215`、`m_fielding.j2:16`、`m_gamelogs.j2:37`
- 文字：`{{ row.sport_level | level_display(row.year) }}`
- class 後綴 `level-{{ ...|lower }}` 目前無對應 CSS（會產生 `level-a(adv)` 這種非法字串）→ **移除後綴，只留 `.level-tag`**（顏色分級屬範圍外）。

### B. Hero / 卡片大 badge（兩種樣式統一）
- `index.j2:36`（卡片 `.level-tag`）：`{{ player.level | level_display(player.level_year) }}`
- `retired.j2:34`（卡片 `.level-tag`）：`{{ item.badge_level | level_display(item.badge_year) }}`
- `player_detail.j2:32`、`m_hero.j2:20`（hero `.badge`）：
  - 文字：`{{ player.level | level_display(player.level_year) }}`
  - 樣式判斷：`{{ 'badge-mlb' if is_mlb(player.level) else 'badge-level' }}`（改用 `is_mlb`，不再字串硬比 `== 'MLB'`）

### C. `data-level` / `data-level-label`（JS 篩選器；JS 不改）
逐場：`tab_gamelogs.j2:37,77`、`m_gamelogs.j2:25`
圖表：`tab_advanced.j2:333-334`、`tab_plot.j2:31-32`、`m_advanced.j2:271-272`、`m_plot.j2:31`
- `data-level` 與 `data-level-label` 皆輸出 `{{ raw | level_display(year) }}`（key 與 label 一致，JS 比對與顯示同步正規化）。
- `_combined` / `_all` 由 §4.3 哨兵規則直通，現有 `{% if _level == '_combined' %}All Levels{% endif %}` 模板邏輯保留。
- `index.j2:20` 的 `data-level`（排序用）同樣輸出 `level_display`；排序本身已由 builder 用 `level_rank` 算好 `data-level-order`，不受影響。

### builder/sync 端配合
- `players.level` 仍存原始值，但 builder 組卡片資料時**一併帶出 `level_year`**（active＝最近一季年份）。優先在記憶體計算，非不得已不加 DB 欄位。
- 退役頁：`badge_level` 改由 `highest_level` 回傳的「最高層級 stat row」取得 `(sport_level, year)`，模板用 `level_display` 顯示為當年原名（例 2018 達到的高階一A → `A(Adv)`）。

---

## 7. 邊界情況

- **未知 / 空字串**：`level_display` 原樣回傳，不報錯（與 `level_rank` 回退 50 一致）。
- **Sentinel**：`_combined`、`_all`、`""` 一律直通，不可被當作 level 解析。
- **`A-` 僅出現於 game_logs 且必為 pre-2021**（短期 A 2021 後裁撤）→ 一律解析為短期 tier → `A(Short)`。
- **`Minors`（rank 99）/ `WIN`**：彙總層與冬季聯盟，原樣顯示其代碼。
- **`is_mlb` 對未知值**：`resolve_tier` 回 None → `is_mlb` 回 False（套用一般 `badge-level` 樣式）。
- **跨年代同 tier 的篩選器**：同一球員若 2019(`A(Adv)`) 與 2023(`A+`) 都打過高階一A，篩選器會出現兩個選項（不同年代名稱）——此為符合「保留當年原名」的預期行為。

---

## 8. 測試策略

- `level_display` 單元測試：覆蓋 §4.3 對照表每一列（空格變體、現代代碼+舊年份換算、`ROA`/`Rk` 併入、sentinel 直通、未知值回退）。
- `level_rank` 單元測試：整併後排序不變（`A(Adv)`＝`A+`＝3；`A(Short)`＝`A-`＝5；未知＝50）。
- `resolve_tier` / `sport_id_to_code`：`sportId 17` → `WIN`（回歸驗證 bug 已修），16 → `ROK`。
- 端對端：對一名橫跨改革、且有逐場資料的球員建頁，確認賽季表、進階表、守備表、逐場表、篩選器下拉、卡片/hero badge 對同一球季顯示**完全一致**。

---

## 9. 範圍外（YAGNI）

- 中文 / 雙語層級名稱。
- level badge 顏色分級（per-level CSS class）；本次只移除無效的 `level-{x}` 後綴。
- 追蹤 Winter Leagues 資料；本次僅修正其代碼定義不再誤標 ROK。
- 任何 DB schema 變更或資料回填（`level_year` 優先在 builder 記憶體計算）。
- 修改 JS 篩選邏輯（模板輸出正規化後 JS 自動正確）。

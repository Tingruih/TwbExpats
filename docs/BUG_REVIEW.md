# Taiwan MLB Tracker — Bug 審查與修復學習文檔

本文整併三輪程式碼審查（含兩組 sub-agent 深掘）後**已驗證為真**的所有問題。
每一條都採「從最底層原理講起 → 為什麼是 bug（附驗證）→ 解法與修改後程式碼 → 為什麼這樣能修正」的結構，
讓你能一邊學習一邊覆核 bug 的真實性。

> **先講清楚：以下這些「曾被懷疑、但實測確認為正確」者不在修復清單，請勿亂改。**
> - 投手 BABIP 用 `BF − SO − HR − BB` 當分母 → 業界常見的簡化分母，正確。
> - wOBA 分母 = `PA − SH − IBB`（含 SF/HBP）→ 與 FanGraphs 一致。
> - Barrel 公式（98→[26,30]、100→[24,33]、116→[8,50]）、Sweet Spot 區間 8–32°、IP 棒球小數換算（7.2 → 23 outs）→ 全部實跑驗證正確。
> - `.data-table` 在多檔出現 → 是「單一基準 + 帶修飾類的情境覆寫」，架構正確，非重複定義。
> - `tojson_safe` 的 `</` → `<\/` 跳脫、autoescape → 無 XSS。
> - SQLite 並行模型（worker 各自開連線讀、主執行緒序列寫）→ 安全。

嚴重度定義：**P0** 當機/資料毀損；**P1** 使用者可見的錯誤或重大維護/可及性缺陷；**P2** 局部錯誤或明顯效能/維護問題；**P3** 邊角、低影響、潔癖。

---

## 目錄
- A. 會顯示錯誤數字的 bug（最優先）
  - A1. WAR / FIP / xWPCT 的 `0.0` 被當成「無資料」
- B. 多層級「合計」聚合 bug
  - B1. 合計列的「All Counts」配球桶恆為空
  - B2. 合計列用 BBE 數加權 `ev90` / `hr_fb_pct`（百分位/比率不可加權平均）
- C. 健壯性 / 例外處理
  - C1. `get_player_stats` 的 MiLB 段沒有 try，失敗會丟掉整批
  - C2. 空字串 `""` 讓 rate-stat 的衍生重算被跳過
  - C3. `ci`（捕手妨礙）寫入卻不在 `_COUNTING_FIELDS`，生涯漏算
- E. 重複與耦合（改一處要改多處）
- F. 前端效能
- G. 前端正確性 / 可及性
- H. CSS 維護性與其他

---

# A. 會顯示錯誤數字的 bug

## A1. WAR / FIP / xWPCT 的 `0.0` 被當成「無資料」顯示成「—」
**位置**：`src/templates/tabs/tab_advanced.j2:166,167,182`、`src/templates/mobile/sections/m_advanced.j2:125,128,144`
**嚴重度**：P2　**信心**：已確認

### 從最底層講起：什麼是「truthiness（真值性）」
Python 在 `if x:` 這種「需要布林判斷」的情境，不會只接受 `True/False`，而是把任何物件透過 `bool(x)` 轉成真假。對數字而言，**只有 `0`、`0.0` 會被視為「假」**，其餘非零數字都是「真」。其他常見的「假值」還有 `None`、`""`（空字串）、`[]`、`{}`。

Jinja2 模板的 `{% if x %}` 沿用同一套規則。所以：

```jinja
{% if ss_row.war %} ... {% else %}—{% endif %}
```

當 `ss_row.war` 是 `0.0` 時，`{% if 0.0 %}` → 假 → 走 `{% else %}` → 印出「—」。

### 為什麼這是 bug（而不是刻意）
- **WAR = 0.0 是完全合法的數值**：它代表「替補水準球員（replacement level）」，是棒球統計裡有意義的一個點，不是「沒有資料」。
- 同一張表的 wRC+ 卻寫對了，用的是 `is not none`：

```jinja
{% if ss_row and ss_row.wrc_plus is not none %}{{ ss_row.wrc_plus }}{% else %}—{% endif %}
```

`is not none` 只問「是不是 `None`」，`0` 不是 `None`，所以 0 會正常顯示。WAR/FIP/xWPCT 用 truthy、wRC+ 用 `is not none`，**同頁不一致**本身就是強烈的 bug 訊號。

- 資料端確實可能是 0.0：`site_builder/sync.py:1094` 是 `stat_doc["war"] = safe_float(sabermetrics.get("war"))`，沒有過濾 0。

### 驗證
- `grep` 確認這三欄（`ss_row.war` / `ss_row.fip` / `ss_row.xwpct`）在模板中**零處**使用 `is not none`，全用 truthy。
- 桌機（`tab_advanced.j2`）與手機（`m_advanced.j2`）**一致地錯**，所以不是雙模板分歧、是同一個觀念性錯誤。

### 解法與修改後程式碼
把 truthy 判斷改成 `is not none`，與 wRC+ 對齊。

`tab_advanced.j2`（投手列）：
```jinja
{# 修改前 #}
<td class="num">{% if ss_row and ss_row.fip %}{{ ss_row.fip|floatformat(2) }}{% else %}—{% endif %}</td>
<td class="num">{% if ss_row and ss_row.xwpct %}{{ ss_row.xwpct|floatformat(3) }}{% else %}—{% endif %}</td>

{# 修改後 #}
<td class="num">{% if ss_row and ss_row.fip is not none %}{{ ss_row.fip|floatformat(2) }}{% else %}—{% endif %}</td>
<td class="num">{% if ss_row and ss_row.xwpct is not none %}{{ ss_row.xwpct|floatformat(3) }}{% else %}—{% endif %}</td>
```

`tab_advanced.j2`（打者列 WAR）：
```jinja
{# 修改前 #}
<td class="num">{% if ss_row and ss_row.war %}{{ ss_row.war|floatformat(1) }}{% else %}—{% endif %}</td>
{# 修改後 #}
<td class="num">{% if ss_row and ss_row.war is not none %}{{ ss_row.war|floatformat(1) }}{% else %}—{% endif %}</td>
```

`m_advanced.j2` 同樣三處（`:125` FIP、`:128` xWPCT、`:144` WAR）比照改成 `is not none`。

### 為什麼這樣能修正
`is not none` 把判斷的語意從「值是不是真的（非零非空）」改回正確的「**有沒有資料**」。如此一來 `0.0` 因為「不是 None」而被視為有資料、正常顯示；只有真正缺值（`None`）才顯示「—」。

---



---

# B. 多層級「合計」聚合 bug

> 背景：同一年球員若在多個層級出賽（MLB↔AAA 升降），`builder.py` 會在該年的明細列前面再插一列「合計（_combined）」，把各層級數據做加權平均後顯示。以下三個 bug 都只影響這個「合計」摘要列，**各單一層級的值是精確的**。

## B1. 合計列的「All Counts」配球桶恆為空
**位置**：`site_builder/builder.py:54-61`（`_COUNT_USAGE_BUCKETS`）對照 `site_builder/statcast.py:104-135`；合併邏輯 `builder.py:225-240`
**嚴重度**：P3（模板目前有過濾掉，使用者看不到，但屬死碼＋資料漏算）　**信心**：已確認

### 從最底層講起：用「key 對照」合併時，兩端 key 的定義必須一致
合併程式用 `row["key"]` 去把各層級的資料丟進對應的桶。如果產生端（statcast）根本不產出某個 key，消費端（builder）卻替它開了一個桶，那個桶就永遠累加不到東西。

### 程式現況
- `statcast.py` 的 `_COUNT_USAGE_BUCKETS` 只有 5 個球數分桶：`early / pitcher_ahead / pitcher_behind / pre_two_strikes / two_strikes`，**沒有** `all`。
- `builder.py` 的 `_COUNT_USAGE_BUCKETS` 多了一個 `("all", "All Counts", ...)`。
- 合併時 `_combine_pitch_usage_by_count` 以 row 的 key 配桶，但 statcast 產出的 `rows` 裡從來沒有 `key == "all"` 的列 → `bucket_data["all"]` 的 `pitches` 永遠是 0。
- 連帶 `builder.py:239` 那段 `if row.get("key") == "all": ...` 補 totals 的分支也永不執行（死碼）。

### 驗證
- 列印兩邊 keys：`set(builder_keys) − set(statcast_keys) == {"all"}`。
- 跑一次多層級 combine：`all` 桶 `pitches = 0`，其餘桶正常。
- 模板 `tabs/tab_advanced.j2` 用 `{% if row.key != 'all' %}` 把這列跳過，所以**目前使用者看不到**這個空列。

### 解法與修改後程式碼
兩端對齊：移除 builder 端多出來的 `all` 桶與其死分支。

```python
# builder.py  修改前
_COUNT_USAGE_BUCKETS = (
    ("all", "All Counts", "All ball-strike counts"),
    ("early", "Early Count", "0-0, 0-1, 1-0"),
    ("pitcher_ahead", "Pitcher Ahead", "0-1, 0-2, 1-2, 2-2"),
    ("pitcher_behind", "Pitcher Behind", "1-0, 2-0, 3-0, 2-1, 3-1"),
    ("pre_two_strikes", "Pre Two Strikes", "0-0, 0-1, 1-0, 1-1, 2-1, 3-1"),
    ("two_strikes", "Two Strikes", "0-2, 1-2, 2-2, 3-2"),
)

# builder.py  修改後（拿掉 all，與 statcast 對齊）
_COUNT_USAGE_BUCKETS = (
    ("early", "Early Count", "0-0, 0-1, 1-0"),
    ("pitcher_ahead", "Pitcher Ahead", "0-1, 0-2, 1-2, 2-2"),
    ("pitcher_behind", "Pitcher Behind", "1-0, 2-0, 3-0, 2-1, 3-1"),
    ("pre_two_strikes", "Pre Two Strikes", "0-0, 0-1, 1-0, 1-1, 2-1, 3-1"),
    ("two_strikes", "Two Strikes", "0-2, 1-2, 2-2, 3-2"),
)
```

並刪除 `builder.py:239-240` 這段永不觸發的補桶分支：
```python
# 刪除
if row.get("key") == "all" and ptype not in totals_by_type:
    totals_by_type[ptype] = totals_by_type.get(ptype, 0) + (pt.get("count") or 0)
```
（`totals_by_type` 已由上方 `usage.get("pitch_types")` 迴圈正確累加，這段本就無作用。）

> 註：這個 bug 與 E1（常數重複）同根——同一份「球數分桶」定義散在兩個檔，才會漂移出 `all` 這種不一致。根治見 E1。

### 為什麼這樣能修正
消費端不再替一個產生端不存在的 key 開桶，就不會出現恆空的 `all` 列，也消掉一段誤導後人的死分支。

---

## B2. 合計列用 BBE 數加權 `ev90` / `hr_fb_pct` / `avg_la`
**位置**：`site_builder/builder.py:524-528`（`_combine_statcast_dicts` 的 `bbe_fields`）
**嚴重度**：P3（僅合計列）　**信心**：高（ev90 為確定錯誤）

### 從最底層講起：哪些統計量可以「加權平均合併」、哪些不行
把兩個子群的統計量合成整體，能不能用「各自的值 × 各自的樣本數，再除以總樣本數」這種加權平均，取決於該統計量的數學性質：
- **可加權平均**：分子分母都是「可相加的計數」的比率（如 barrel% = barrels/BBE）。把分子計數加總、分母計數加總再相除即可；用樣本數加權平均是它的等價近似。
- **不可加權平均**：
  - **百分位數**（如 `ev90` = 第 90 百分位的擊球初速）。百分位是「排序後某位置的值」，無法只憑兩個子群各自的百分位＋樣本數還原整體百分位——你必須有**原始 EV 清單**重新排序取百分位。
  - **權重對象搞錯的比率**：`hr_fb_pct` = HR / 飛球數，正確權重是「飛球數」不是「BBE 數」；`avg_la` 正確權重是「有 launch angle 的 BBE 數」。

### 程式現況
```python
bbe_fields = [
    "barrel_pct", "hard_hit_pct", "avg_ev", "avg_la", "swsp_pct",
    "gb_pct", "ld_pct", "fb_pct", "pu_pct", "air_pct", "pull_pct",
    "straight_pct", "oppo_pct", "pull_air_pct", "hr_fb_pct", "ev90",
]
...
for f in bbe_fields:
    combined[f] = _wpct(f, "bbe")   # 一律用 BBE 數加權
```

`ev90`、`hr_fb_pct`、`avg_la` 都被丟進「用 BBE 數加權」這條路。

### 為什麼是 bug
- `ev90`：百分位**根本不能**用兩層級的百分位加權平均得到，結果是個沒有統計意義的數。
- `hr_fb_pct`、`avg_la`：權重對象錯了（該用 FB 數 / 有 la 的 BBE 數），是近似誤差。

### 驗證
閱讀 `_combine_statcast_dicts` 的權重映射；對照 `max_ev` 是正確地用 `max()`（極值合併不能加權平均），證明作者知道某些量要特別處理，只是漏了 ev90。

### 解法與修改後程式碼
最務實、最誠實的做法：**合計列無法精確重算的量就標 `None`**（模板會顯示「—」），不要給使用者一個假的數。

```python
# builder.py 修改前
bbe_fields = [
    "barrel_pct", "hard_hit_pct", "avg_ev", "avg_la", "swsp_pct",
    "gb_pct", "ld_pct", "fb_pct", "pu_pct", "air_pct", "pull_pct",
    "straight_pct", "oppo_pct", "pull_air_pct", "hr_fb_pct", "ev90",
]
...
for f in bbe_fields:
    combined[f] = _wpct(f, "bbe")

# builder.py 修改後
bbe_fields = [
    "barrel_pct", "hard_hit_pct", "avg_ev", "avg_la", "swsp_pct",
    "gb_pct", "ld_pct", "fb_pct", "pu_pct", "air_pct", "pull_pct",
    "straight_pct", "oppo_pct", "pull_air_pct", "hr_fb_pct",
]
...
for f in bbe_fields:
    combined[f] = _wpct(f, "bbe")

# ev90 是百分位，無法由各層級百分位加權還原；合計列不提供（顯示「—」）
combined["ev90"] = None
```

> 進階（若要連 `hr_fb_pct` 都精確）：需在 `compute_*_statcast` 多存一個 `fb`（飛球數）計數，合併時 `combined["hr_fb_pct"] = Σhr / Σfb`。此屬增強，非必修。

### 為什麼這樣能修正
把「數學上無法正確合併的量」誠實地留白，比顯示一個誤導的加權平均更正確。各單一層級的 `ev90` 仍精確顯示，使用者要看分層數字即可。

---


---

# C. 健壯性 / 例外處理

## C1. `get_player_stats` 的 MiLB 段沒有 try，失敗會丟掉整批
**位置**：`site_builder/api.py:124-152`
**嚴重度**：P3　**信心**：已確認

### 從最底層講起：例外會「往上炸穿」整個函式，連已完成的工作一起作廢
Python 的例外一旦在某行拋出且當層沒有 `try` 接住，會直接結束**整個函式**並往呼叫端傳遞。函式內部已經算好、但還在區域變數裡、還沒 `return` 的東西，全部隨之消失。

### 程式現況
```python
def get_player_stats(mlb_id):
    all_stats = []
    # MLB endpoint —— 有 try 包著
    try:
        resp = requests.get(mlb_url, timeout=TIMEOUT)
        resp.raise_for_status()
        all_stats.extend(resp.json().get("stats", []))
    except Exception as e:
        logger.warning(...)

    # MiLB endpoint —— 沒有 try，直接 raise_for_status()
    resp = requests.get(milb_url, timeout=TIMEOUT)
    resp.raise_for_status()          # ← 若 MiLB 端 500/逾時，這裡拋例外
    all_stats.extend(resp.json().get("stats", []))
    return all_stats                 # ← 上面一炸，這行到不了，連 MLB 段也回不來
```

### 為什麼是 bug
兩個端點刻意分開抓（同一球員可能 MLB+MiLB 都有資料），MLB 段體貼地包了 try，MiLB 段卻沒有。當 MiLB 端暫時故障，整個 `get_player_stats` 拋例外 → 即使 MLB 段已成功放進 `all_stats`，也因為例外炸穿而**連 MLB 資料一起丟失**。雖然上層 `sync.py:445-448` 有 try 兜底不至於整個 sync 崩潰，但該球員這次同步會「兩種層級都沒拿到」，而非「至少拿到 MLB」。風格也與 MLB 段不一致。

### 解法與修改後程式碼
```python
# 修改前
    resp = requests.get(url, timeout=TIMEOUT)
    resp.raise_for_status()
    all_stats.extend(resp.json().get("stats", []))
    return all_stats

# 修改後
    try:
        resp = requests.get(url, timeout=TIMEOUT)
        resp.raise_for_status()
        all_stats.extend(resp.json().get("stats", []))
    except Exception as e:
        logger.warning("MiLB yearByYear failed for %s: %s", mlb_id, e)
    return all_stats
```

### 為什麼這樣能修正
MiLB 段自己接住例外後，函式不會炸穿，`all_stats` 裡已成功的 MLB 資料能正常 `return`。達成「部分成功也能保留」（graceful degradation），且與 MLB 段對稱。

---

## C2. 空字串 `""` 讓 rate-stat 的衍生重算被跳過
**位置**：寫入端 `site_builder/sync.py:278-279,307-311,349-350`；重算守門 `site_builder/helpers.py`（`_compute_advanced_stats` 內各 `if s.get("xxx") is None`）
**嚴重度**：P3　**信心**：已確認

### 從最底層講起：`None`（無值）與 `""`（空字串）是兩種不同的「沒有」
- `None`：明確表示「沒有這個值」。
- `""`：是一個**長度為 0 的字串**，它**不等於** `None`（`"" is None` 為 `False`）。
- 但兩者在 truthy 判斷下都是「假」（`bool("")` 與 `bool(None)` 都是 `False`）。

混用這兩者、又在判斷時用了「錯的那一種比較」，就會出錯。

### 程式現況
寫入端把缺值存成空字串：
```python
"win_pct": str(stat.get("winPercentage", "")),   # API 沒給 → 存成 ""
"strike_pct": str(stat.get("strikePercentage", "")),
"p_avg": str(stat.get("avg", "")),
...
```
重算端用 `is None` 當「要不要自己補算」的守門：
```python
# Win% = W / (W + L)
if s.get("win_pct") is None:        # ← 守門：只有 None 才補算
    w = s.get("wins"); l = s.get("losses")
    if w is not None and l is not None and (w + l) > 0:
        s["win_pct"] = _fmt_avg(w / total)
```

### 為什麼是 bug
當 API 沒給 `winPercentage` 但**有給 W 和 L**（例如某些 MiLB 賽季），`win_pct` 被存成 `""`。重算守門是 `is None`，而 `"" is None` 為 `False` → **不補算** → 該欄永遠是空字串、表格顯示空白，即使我們明明能從 W/L 算出來。受影響的同型欄位還有 `strike_pct / p_avg / p_obp / p_slg / p_ops / sb_pct / cs_pct`。

### 驗證
構造 `wins=5, losses=3, win_pct=""`，跑 `annotate_computed_stats` → `win_pct` 仍是 `""`（沒有變成 `.625`）。

### 解法與修改後程式碼
有兩種修法，擇一（建議兩者都做，最穩）：

**修法一（治本）：寫入端不要用 `""`，缺值就存 `None`。** 改一個小工具：
```python
def _str_or_none(value):
    """API 字串型 rate-stat：缺值回 None（而非 ''），讓下游 is None 守門正確生效。"""
    if value is None or value == "":
        return None
    return str(value)
```
然後 `sync.py` 把 `str(stat.get("winPercentage", ""))` 改為 `_str_or_none(stat.get("winPercentage"))`，其餘同型欄位比照。

**修法二（治標但簡單）：重算守門改用 falsy 判斷。**
```python
# 修改前
if s.get("win_pct") is None:
# 修改後（None 或 "" 都視為「缺，需補算」）
if not s.get("win_pct"):
```
同樣套用到 `strike_pct / p_avg / p_obp / p_slg / p_ops / sb_pct / cs_pct` 的守門。

> ⚠️ 注意：`not x` 對 `0`/`0.0` 也成立。對「合法值可能為 0」的數值欄位（如 WAR、各種計數）**不可**用 `not x` 當守門（會犯 A1 同款錯）。這裡用 falsy 安全的原因是：這些 rate-stat 即使值為 `0`，原本就以字串 `"0.000"` 之類存放（非數字 0），且重算只會得到相同結果，無副作用。若不確定，採修法一最保險。

### 為什麼這樣能修正
- 修法一從源頭消除 `""` 這個「假的空」，讓 `is None` 守門恢復正確語意。
- 修法二把守門從「只認 None」放寬到「None 與空字串都算缺」，使有 W/L 時能正確補算 win%。

---

## C3. `ci`（捕手妨礙）寫入卻不在 `_COUNTING_FIELDS`，生涯/賽季合計漏算
**位置**：寫入 `site_builder/sync.py:346`；聚合清單 `site_builder/helpers.py:92-109`（`_COUNTING_FIELDS`）
**嚴重度**：P2（靜默漏算）　**信心**：已確認

### 從最底層講起：聚合是「照著一張白名單欄位逐欄加總」
生涯／賽季合計不是「把整個 dict 全加起來」，而是 `_sum_counting` **只迭代 `_COUNTING_FIELDS` 這張白名單**裡的欄位去加總：
```python
def _sum_counting(stats, result):
    for field in _COUNTING_FIELDS:       # ← 只有名單上的欄位會被加總
        values = [getattr(s, field) for s in stats]
        ...
        result[field] = sum(v or 0 for v in values)
```
所以任何「有存進 DB、但沒列進白名單」的計數欄，在生涯列就會**默默消失**。

### 程式現況
`sync.py:346` 把捕手妨礙存進每季 stat：
```python
"ci": safe_int(stat.get("catchersInterference")),
```
但 `helpers.py` 的 `_COUNTING_FIELDS` 清單裡**沒有** `"ci"`。

### 為什麼是 bug
單一賽季列能顯示 `ci`（因為直接讀該季 stat_json），但生涯列、跨隊合計列因為 `ci` 不在白名單而**不會被加總** → 生涯 CI 永遠缺失或為 0。這是「資料有存、但聚合層漏接」的靜默不一致。CI 很罕見，影響小，但屬正確性缺口。

### 驗證
讀 `_COUNTING_FIELDS` 全清單，確認無 `ci`；讀 `_sum_counting` 確認它只跑該清單。

### 解法與修改後程式碼
若要在生涯列顯示 CI，把 `"ci"` 加進白名單（放在 hitting 區塊）：
```python
# helpers.py  _COUNTING_FIELDS 的 Hitting 區塊
    "pa", "ab", "runs", "hits", "doubles", "triples", "hr", "rbi", "tb",
    "hit_bb", "h_so", "hbp", "ibb", "sb", "cs", "gdp", "lob",
    "sac_bunts", "sac_flies", "h_ground_outs", "h_air_outs", "pitches_seen",
    "gidpo", "roe", "wo", "xbh", "ci",   # ← 新增 ci
```

若決定不顯示 CI，則反向移除 `sync.py:346` 的寫入，避免存了不用的欄位。**二擇一**，使「有存就有用、有用才存」一致。

### 為什麼這樣能修正
把 `ci` 納入白名單後，`_sum_counting` 會在生涯/賽季合計時一併加總它，補上漏接。

---


---

# E. 重複與耦合（改一處要改多處）

## E1. 配球/球數常數與小工具在 `builder.py` 與 `statcast.py` 各定義一份
**位置**：兩檔皆有 `_PLINKO_COUNTS`、`_PLINKO_EDGES`、`_BAT_SIDE_SPLITS`、`_COUNT_USAGE_BUCKETS`、`_is_unknown_pitch_type`、`_ratio`　**P2/已確認**

### 底層原因
同一份「真相」（Plinko 圖的節點與邊、球數分桶、未知球種判定、安全除法）被複製成兩份。複製品一旦只改一邊就會「漂移」——B1 的 `all` 桶恆空、就是 `_COUNT_USAGE_BUCKETS` 兩份漂移的直接後果。另外兩個 `_ratio` 的**預設小數位數不同**（`builder._ratio` 預設 4 位、`statcast._ratio` 預設 3 位），跨檔閱讀時極易誤判精度。

### 修法
建立單一共用模組（例如 `site_builder/pitch_constants.py`，或放進現有的 `levels.py` 旁），把這些常數與純函式集中：
```python
# site_builder/pitch_constants.py（新檔，示意）
PLINKO_COUNTS = ("0-0", "0-1", "1-0", "0-2", "1-1", "2-0",
                 "1-2", "2-1", "3-0", "2-2", "3-1", "3-2")
PLINKO_EDGES = ( ("0-0","0-1"), ("0-0","1-0"), ... )   # 唯一一份
BAT_SIDE_SPLITS = (("all","全部"), ("L","左打"), ("R","右打"))
COUNT_USAGE_BUCKETS = ( ("early","Early Count","0-0, 0-1, 1-0"), ... )  # 不含 all

def is_unknown_pitch_type(pitch_type, pitch_name=None) -> bool: ...
def ratio(num, den, digits=3): ...   # 明確、單一的預設位數
```
`builder.py` 與 `statcast.py` 改成 `from .pitch_constants import ...`，刪除各自的副本。

> 注意 statcast 的 `_COUNT_USAGE_BUCKETS` 是 dict 帶 `counts` set、builder 是 tuple——整併時要設計一個能同時供兩邊使用的結構（例如每個 bucket 帶 `key/label/counts_label/counts`，builder 端忽略 `counts` 即可）。

### 為什麼這樣能修正
唯一真相（single source of truth）後，改 Plinko 結構或球數分桶只需動一處，兩端永遠同步，漂移類 bug（如 B1）從根上消失。`_ratio` 也只剩一個明確的預設位數，杜絕精度誤用。`levels.py` 正是這個專案已經實踐過、效果很好的範本。

## E2. 桌機 / 手機兩套模板渲染同一份數據（改欄位要改兩處）
**位置**：6 組平行模板 `src/templates/tabs/tab_*.j2` ↔ `src/templates/mobile/sections/m_*.j2`　**P1/已確認**

### 底層原因
球員頁同時輸出桌機版與手機版兩套 markup，靠 CSS `display:none`（768px）藏一份（見 F1）。同一個 stat 欄位在桌機 tab 與手機 section **各寫一遍**。依 `CLAUDE.md` 的「新增數據欄」流程，新增一欄要同時改桌機與手機兩個模板，且兩邊 markup 結構不同、容易漏改造成 RWD 不一致。

### 修法（屬較大重構，建議先設計再動）
- **短期**：把重複的渲染抽成共用 Jinja `macro`（例如 `macros/stat_blocks.j2` 內 `key_stats_strip(stat, is_pitcher)`、`advanced_row(sc, ss_row, is_pitcher)`），桌機與手機都 `import` 同一個 macro，差異只留在外層容器/CSS。
- **長期**：收斂成單一響應式 markup（一套 HTML + 純 CSS RWD），移除整個 `mobile/sections/` 平行樹。

### 為什麼這樣能修正
共用 macro 或單一 markup 後，「一個欄位只有一處定義」，改一次到處生效，消除雙改漏改。

## E3. 首頁「層級」排序的 `data-level-order` 用 `loop.index`（脆弱耦合）
**位置**：`src/templates/index.j2:21` + `src/static/js/index-sort.js:19-20`　**P3/已確認（目前正確、屬脆弱）**

### 底層原因
`index-sort.js` 的註解宣稱「依 data-level-order 升冪（AAA→AA→A）」，但模板實際輸出的是 `loop.index`——也就是卡片在 `player_data` 陣列裡的**位置序號**，不是層級。目前之所以剛好對，是因為 `builder.py:919` 在渲染前已先 `player_data.sort(key=lambda x: level_rank(x["player"].level))` 把資料按層級排好，於是「位置序號」恰好等於「層級序」。

### 為什麼是隱患
這是**靠上游排序剛好對齊**的巧合。哪天有人把 `builder.py` 的排序改成別的（例如按姓名），首頁「依層級」按鈕會**無聲地壞掉**、且沒有任何錯誤訊息。`data-level-order` 應該輸出真正的層級序（`level_rank`），與資料語意對齊，而非依賴渲染順序。

### 修法
讓模板輸出真正的層級序。`builder.py` 的 `player.level` 可經 `level_rank` 得到序：
```jinja
{# index.j2 修改前 #}
data-level-order="{{ loop.index }}"
{# 修改後（輸出真正的層級序；需在 builder 端把 level_rank 暴露給模板，或預先算好放進 item） #}
data-level-order="{{ item.level_order }}"
```
搭配 `builder.py` 在組 `player_data` 時加上 `"level_order": level_rank(player.level)`：
```python
player_data.append({
    "player": player,
    "stat": _pick_display_stat(stats_current, player),
    "level_year": level_year,
    "last_game_date": last_game_date,
    "level_order": level_rank(player.level),   # ← 新增
})
```

### 為什麼這樣能修正
排序鍵直接來自層級語意（`level_rank`），與 builder 的渲染順序解耦。即使日後改變卡片渲染順序，「依層級」排序仍然正確。

---

# F. 前端效能

## F1. 桌機＋手機雙重渲染：DOM 量約翻倍、內嵌 JSON 出現兩次
**位置**：`src/templates/player_detail.j2:5-74`；切換 `src/static/css/mobile/mobile.css:12-13,71-72`　**P1/已確認**

### 底層原因
`display:none` 只是**不繪製**，被藏起來的那一份 DOM 節點**仍然存在於 HTML、仍會被瀏覽器解析**。球員頁同時 `include` 桌機 `tabs/*.j2` 與手機 `mobile/sections/m_*.j2`，於是：
- 每張 `<table>`、每個數據格在 HTML 裡都有兩份；
- 更糟的是，`tab_plot.j2` 與 `m_plot.j2` **各自內嵌一份** plinko/movement 的 `tojson_safe` 資料 → 同一包 JSON 在頁面出現兩次，傳輸與解析都加倍。

手機使用者下載＋解析了整套桌機 table，桌機使用者反之。

### 修法
與 E2 同源。最低成本先做「去重內嵌 JSON」：把資料只輸出一份 `<script type="application/json" id="...">`，桌機與手機 JS 都讀同一個 id。根治則是收斂為單一 markup。

### 為什麼這樣能修正
去除重複 DOM 與重複 JSON 後，HTML 體積與解析成本下降（進階頁尤其明顯），首屏與互動都更快。

## F4. 巢狀 `@import` 瀑布 + 每頁載入全站 CSS
**位置**：`src/static/css/style.css:18-30`、`src/static/css/mobile/mobile.css:1-10`　**P2/已確認**

### 底層原因
CSS 的 `@import` 與 HTML 的多個 `<link>` 不同：瀏覽器要先**下載並解析** `style.css`，**之後才發現**裡面的 `@import` 清單，再去抓子檔；而 `mobile.css` 自己又 `@import` 了 10 個 `m-*.css`，要等到第二層解析完才開始抓——形成最深 3 跳的**序列瀑布**（style → mobile → m-*.css）。多個 `<link>` 則能一開始就並行抓取。此外 `index.j2`/`retired.j2` 也透過 `style.css` 載入了整套 `player-hero/tabs/bio/stats/gamelogs/advanced/charts/fielding/mobile/*`，但首頁只用得到其中 4 個檔。

### 修法
- **去瀑布**：在建置期（或用簡單的串接腳本）把所有子 CSS **串接成單一檔**，消除 `@import`；或把子檔改成 `base.j2` 裡的多個 `<link>`（並行下載）。
- **去多載**：拆成 `common.css`（base/layout/components）+ 各頁專屬 CSS，首頁不載入球員頁樣式。

### 為什麼這樣能修正
單檔串接消除「解析後才發現要再抓下一層」的往返；分頁載入讓首頁只下載它需要的樣式，減少傳輸與解析量。

## F5. 首頁頭像未用原生 `loading="lazy"`，且 `<img>` 無尺寸（CLS）
**位置**：`src/templates/index.j2:27`（與退役頁同型）　**P3/已確認**

### 底層原因
- 首頁頭像用自製 JS 分批 lazy（`avatar-fallback.js`），可運作，但比瀏覽器原生 `loading="lazy"` 多一層 JS 排程成本。
- `<img>` 沒有 `width`/`height` 屬性時，瀏覽器在圖片載入前不知道要保留多少空間，圖片一進來會把下面內容往下推 → 造成 **CLS（版面位移）**。

### 修法
```html
<!-- 修改前 -->
<img data-src="{{ cdn_primary }}" data-cdn-src="{{ cdn_secondary }}" alt="{{ player_name }}" class="avatar-img">
<!-- 修改後：給定尺寸 + 原生 lazy（視 avatar-fallback 的 fallback 機制決定是否保留 data-src 流程） -->
<img data-src="{{ cdn_primary }}" data-cdn-src="{{ cdn_secondary }}" alt="{{ player_name }}"
     class="avatar-img" width="56" height="56" loading="lazy" decoding="async">
```
（`width/height` 用實際 CSS 顯示尺寸；確切數值依 `.avatar-img` 樣式而定。）

### 為什麼這樣能修正
明確 `width/height` 讓瀏覽器在載入前就保留正確空間，消除 CLS；原生 `loading="lazy"`/`decoding="async"` 把延後載入交給瀏覽器最佳化。

---

# G. 前端正確性 / 可及性

## G1. 桌機 Tab 用 `<label>` 模擬分頁，無法鍵盤操作、無 ARIA
**位置**：`src/templates/player_detail.j2:54-61` + `src/static/js/tabs.js`　**P1/已確認**

### 底層原因
分頁是用一排 `<label>` 加 `data-tab` 做的，`tabs.js` 只綁了 `click`：
```html
<label data-tab="bio" class="tab-label tab-label--active">球員資料</label>
```
- `<label>`（沒有關聯 `for` 的）**不是可聚焦的互動元素**：它不能被 Tab 鍵聚焦、不能用 Enter/Space 觸發、不能用方向鍵切換 → **完全無法用鍵盤操作分頁**。
- 沒有 `role="tablist"`/`role="tab"`/`aria-selected`/`aria-controls` → 螢幕報讀器不知道這是分頁、也不會宣告目前選了哪個。（手機版 `m-tabs.js` 反而有處理 `aria-current`，桌機版較差。）

### 驗證
`grep "role=\|aria-\|tabindex"` 在 tab 區段零命中；`tabs.js` 只有 `addEventListener('click')`，無 `keydown`。

### 修法（依 WAI-ARIA Tabs pattern）
把 `<label>` 換成 `<button>`（原生可聚焦、可 Enter/Space 觸發），加上 ARIA，並在 `tabs.js` 補方向鍵：
```html
<div class="tab-nav glass-panel" role="tablist" aria-label="球員數據分頁">
  <button type="button" role="tab" id="tab-bio" aria-controls="panel-bio"
          aria-selected="true"  data-tab="bio"      class="tab-label tab-label--active">球員資料</button>
  <button type="button" role="tab" id="tab-stats" aria-controls="panel-stats"
          aria-selected="false" data-tab="stats"    class="tab-label">基礎數據</button>
  ... 其餘分頁同理 ...
</div>
```
`tabs.js` 切換時同步更新 `aria-selected`，並加方向鍵：
```js
tablist.addEventListener('keydown', function (e) {
  if (e.key !== 'ArrowRight' && e.key !== 'ArrowLeft') return;
  var tabs = Array.from(tablist.querySelectorAll('[role="tab"]'));
  var i = tabs.indexOf(document.activeElement);
  var next = e.key === 'ArrowRight' ? (i + 1) % tabs.length : (i - 1 + tabs.length) % tabs.length;
  tabs[next].focus();
  tabs[next].click();
});
```

### 為什麼這樣能修正
`<button>` 本身可被鍵盤聚焦與觸發；`role/aria-selected/aria-controls` 讓輔助技術正確理解這是分頁與目前狀態；方向鍵處理符合使用者對分頁的鍵盤預期。

## G2. `m-pitch-log.js` 預載「作用中年份」用 inline-style 字串完全比對
**位置**：`src/static/js/mobile/m-pitch-log.js:54-55`　**P3/已確認（目前可運作、屬脆弱）**

### 底層原因
```js
var activeYear = document.querySelector('.m-gamelog-year[style="display: flex;"], .m-gamelog-year:not([style*="display:none"]):not([style*="display: none"])');
```
靠 `[style="display: flex;"]` 這種**對 inline style 序列化字串的完全比對**來找可見年份。`m-gamelogs.js:53` 目前正好是 `container.style.display = 'flex'`（序列化成 `"display: flex;"`），所以現在能對上。但只要顯示邏輯改用 class toggle、或 inline style 多加任何屬性（序列化字串就變了），這個 selector 會**靜默失效**。失敗後果僅是「展開時要等 fetch」，不影響正確性。

### 修法
改用語意判斷，別比字串：
```js
var years = Array.from(document.querySelectorAll('.m-gamelog-year'));
var activeYear = years.find(function (el) { return el.style.display !== 'none'; });
```
或讓 `m-gamelogs.js` 在顯示的年份加 `.is-active` class，這裡改 `querySelector('.m-gamelog-year.is-active')`。

### 為什麼這樣能修正
用「display 不是 none」或 class 標記來判斷可見，與「inline style 字串長怎樣」解耦，顯示實作改動也不會讓預載失效。

---

# H. CSS 維護性與其他

## H1. 10 處 `!important` 用來壓 hover 的 specificity
**位置**：`stats.css`（5）、`charts.css`（3）、`gamelogs.css`（2）　**P2/高**

### 底層原因
CSS 衝突時的勝出規則是「specificity（選擇器明確度）higher 者勝；相同則後者勝」。`!important` 是繞過這套排序的**強制覆蓋**，常被當成「壓不過就加 important」的捷徑。本專案的 `.year-detail-row td { background: ... !important }` 是為了壓過 `.data-table tbody tr:hover` 的 hover 背景（兩者 specificity 相近，靠 important 強壓）。問題是一旦未來新增列狀態，又得再堆一個 `!important`，愈滾愈難維護。

### 修法
用**更明確的選擇器**取代 important，讓它靠 specificity 自然勝出：
```css
/* 修改前 */
.year-detail-row td { background: rgba(0,0,0,.2) !important; }
.year-detail-row:hover td { background: var(--secondary) !important; }

/* 修改後：把 .data-table 也納入選擇器，specificity 高於 .data-table tbody tr:hover */
.data-table tbody tr.year-detail-row td { background: rgba(0,0,0,.2); }
.data-table tbody tr.year-detail-row:hover td { background: var(--secondary); }
```

### 為什麼這樣能修正
提高選擇器明確度後，這條規則本來就會贏過 `.data-table tbody tr:hover`，不再需要 `!important`，未來新增狀態也能用同樣手法疊加而不會陷入 important 戰爭。

## H2. teal 半透明色寫死 `rgba(20,184,166,…)` 共 9 處
**位置**：`gamelogs.css`/`stats.css`/`charts.css`/`base.css` 等　**P3/已確認**

### 底層原因
`--teal: #14b8a6` 已是 `:root` 變數，但它的半透明變體全部寫成 `rgba(20,184,166, x)` 字面量（同一顏色、9 種透明度）。日後改主題色 `--teal` 時，這 9 處不會跟著變——又一個「改一處要改多處」。

### 修法
定義 RGB 分量變數，半透明全部走它：
```css
:root {
  --teal: #14b8a6;
  --teal-rgb: 20, 184, 166;   /* 新增 */
}
/* 用法 */
background: rgba(var(--teal-rgb), .15);
box-shadow: 0 0 0 2px rgba(var(--teal-rgb), .2);
```

### 為什麼這樣能修正
所有 teal 半透明都引用同一組 `--teal-rgb`，改主題色只需改變數一處，全站連半透明一起更新。

## H3. `LEAGUE_RA9` 未涵蓋 A-/ROK/WIN（xWPCT fallback 4.5）
**位置**：`site_builder/statcast.py:71-78`、`:1384`　**P3/高**

`compute_xwpct` 用 `LEAGUE_RA9.get(sport_level, 4.5)`，但表只有 MLB/AAA/AA/A+/A，A-/ROK/WIN 會落到固定 4.5（與這些層級偏高的得分環境不符）。這些層級幾乎沒有逐球資料，影響極小。
**修法**：補齊 `LEAGUE_RA9`（A- ≈ 4.7、ROK ≈ 5.0 等，依實際聯盟數據）；或在 docstring 標明 4.5 為近似。

## H4. `compute_xwpct` docstring 誤稱「Pythagenpat」
**位置**：`site_builder/statcast.py:1380-1389`　**P3/已確認（僅命名）**

公式 `1 / (1 + (fip/lg_ra) ** 1.83)` 是**固定指數 1.83 的 Pythagorean**，不是 Pythagenpat（後者指數會隨得分環境變動）。**數值正確**（FIP==lgRA 時恰得 .500），只是命名誤導。
**修法**：把註解改為「fixed-exponent Pythagorean (exp=1.83)」。**為什麼**：不改行為，只讓文件與實作一致，避免後人誤解。

## H5. `build.py` 每個 subparser 重複宣告 `--roster`
**位置**：`build.py`　**P3/可維護性**

`build`/`refresh` 等子命令各自重複 `add_argument("--roster", ...)`。
**修法**：把共用參數放進一個 `parent` parser（`argparse.ArgumentParser(add_help=False)`），各 subparser 用 `parents=[common]` 繼承。**為什麼**：DRY，改一次預設值/說明所有子命令同步。

---

# 建議修復順序（風險由低到高）

1. **純清理（零行為風險）**：H4 docstring。
2. **明確小修正**：A1 WAR/FIP/xWPCT `is not none`、C1 MiLB try、C3 `ci` 白名單、B1 `all` 桶。
3. **聚合與耦合**：B2 ev90 留白、C2 空字串守門、E1 常數抽共用、E3 排序鍵。
4. **可及性**：G1 Tab ARIA + 鍵盤。
5. **較大重構（先設計）**：E2/F1 桌機手機雙模板收斂、F4 `@import` 改 bundle、H1 `!important`、H2 色變數、F5 CLS、G2 selector。

> 第 1、2 類都可獨立提交、立即驗證，建議先行。

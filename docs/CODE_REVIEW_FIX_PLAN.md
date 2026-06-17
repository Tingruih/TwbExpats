# 全專案 Code Review 修正實作計劃

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 修正 2026-06-11 全專案 code review 發現的安全性、網頁效能、數據正確性、重複碼與常數管理問題。

**Architecture:** 分六個 Phase,每個 Phase 完成後網站皆可獨立建置部署。Python 純函式以 pytest TDD;模板/JS/CSS 修改以 `python build.py build` + 對 `dist/` 產出的腳本斷言驗證。

**Tech Stack:** Python 3.13 / Jinja2 / SQLite / vanilla JS / GitHub Pages

---

## 全域規範(每個 Task 都適用)

1. **Commit 慣例**:一個檔案一個 commit,訊息聚焦該檔案的變更;**禁止加 Co-Authored-By**。多檔變更時依「測試 → 實作 → 模板」順序分次 commit。
2. **驗證基準**:任何改動後 `python build.py build` 必須成功輸出 `Built 22 player pages + index to .../dist`。
3. **測試指令**:`python3 -m pytest tests/ -v`(Phase 0 建立後)。
4. **行號註記**:本計劃行號以 2026-06-11 的 codebase 為準,若有偏移以「搜尋錨點字串」為主。

---

## Phase 0 — 測試基礎建設

### Task 1: 建立 pytest 環境與冒煙測試

本專案目前沒有任何測試。先建立最小 pytest 環境,並以既有純函式 `ip_to_outs` 寫一個冒煙測試驗證環境可用。

**Files:**
- Create: `requirements-dev.txt`
- Create: `tests/__init__.py`(空檔)
- Create: `tests/test_helpers.py`

- [ ] **Step 1: 建立 dev 依賴檔並安裝**

`requirements-dev.txt`:

```
pytest==8.3.5
```

Run: `pip install -r requirements-dev.txt`

- [ ] **Step 2: 寫冒煙測試**

`tests/test_helpers.py`:

```python
"""helpers.py 純函式測試。"""

from site_builder.helpers import ip_to_outs, outs_to_ip


def test_ip_to_outs_baseball_notation():
    # 棒球記法:7.2 = 7 又 2/3 局 = 23 個出局數
    assert ip_to_outs(7.2) == 23
    assert ip_to_outs(0.1) == 1
    assert ip_to_outs(9.0) == 27
    assert ip_to_outs(None) == 0


def test_outs_to_ip_roundtrip():
    assert outs_to_ip(23) == 7.2
    assert outs_to_ip(0) is None
```

- [ ] **Step 3: 執行測試確認通過**

Run: `python3 -m pytest tests/ -v`
Expected: 2 passed

- [ ] **Step 4: Commit(每檔一個 commit)**

```bash
git add requirements-dev.txt && git commit -m "chore: add pytest dev dependency"
git add tests/__init__.py && git commit -m "chore: create tests package"
git add tests/test_helpers.py && git commit -m "test: add smoke tests for ip_to_outs/outs_to_ip"
```

---

## Phase 1 — 數據正確性

### Task 2: `compute_fip` 修正 IP 棒球記法換算

**問題**:`sync.py:917` 把棒球記法的 IP(如 10.1 = 10⅓ 局)直接當十進位數丟進 FIP 公式,分母最大誤差約 1.7%。`_compute_rate_stats` 已有正確的 `ip_to_outs/3` 換算,FIP 應比照。

**Files:**
- Modify: `site_builder/statcast.py:1353`(`compute_fip`)
- Test: `tests/test_statcast.py`(新檔)

- [ ] **Step 1: 寫失敗測試**

`tests/test_statcast.py`:

```python
"""statcast.py 數據計算測試。"""

import pytest

from site_builder.statcast import compute_fip


def test_compute_fip_converts_baseball_ip_notation():
    # 10.1 IP(棒球記法)= 31 outs = 31/3 真實局數
    fip = compute_fip(hr=1, bb=3, hbp=0, k=10, ip=10.1,
                      sport_level="AAA", year=2024)
    expected = round((13 * 1 + 3 * 3 - 2 * 10) / (31 / 3) + 3.896, 2)
    assert fip == expected


def test_compute_fip_none_and_zero_ip():
    assert compute_fip(1, 1, 0, 5, None, "AAA", 2024) is None
    assert compute_fip(1, 1, 0, 5, 0, "AAA", 2024) is None
```

- [ ] **Step 2: 執行確認失敗**

Run: `python3 -m pytest tests/test_statcast.py -v`
Expected: `test_compute_fip_converts_baseball_ip_notation` FAIL(現行實作把 10.1 當 10.1 局)

- [ ] **Step 3: 修改 `compute_fip`**

`site_builder/statcast.py` 檔頭 import 區(`from typing import Optional` 之後)加:

```python
from site_builder.helpers import ip_to_outs
```

(`helpers.py` 不依賴 `statcast.py`,無循環 import 問題。)

`compute_fip` 開頭改為:

```python
def compute_fip(hr, bb, hbp, k, ip, sport_level: str, year: int,
                c_fip: Optional[float] = None) -> Optional[float]:
    """MiLB FIP using known or supplied constant.

    ``ip`` 為棒球記法(7.2 = 7⅔ 局),內部以 ip_to_outs 換算為真實局數。
    """
    if ip is None:
        return None
    ip_actual = ip_to_outs(ip) / 3.0
    if ip_actual <= 0:
        return None
```

並把公式行的 `/ ip` 改為 `/ ip_actual`:

```python
        fip = (13 * hr + 3 * (bb + hbp) - 2 * k) / ip_actual + c_fip
```

- [ ] **Step 4: 執行測試確認通過**

Run: `python3 -m pytest tests/test_statcast.py tests/test_helpers.py -v`
Expected: all passed

- [ ] **Step 5: 確認唯一呼叫端不需改**

Run: `grep -rn "compute_fip(" site_builder/ build.py`
Expected: 只有 `statcast.py` 定義處與 `sync.py:917` 呼叫處(傳入值本來就是棒球記法,語意修正後直接正確)。

- [ ] **Step 6: Commit**

```bash
git add tests/test_statcast.py && git commit -m "test: cover FIP baseball-notation IP conversion"
git add site_builder/statcast.py && git commit -m "fix: convert baseball IP notation to real innings in compute_fip"
```

### Task 3: 統一 Barrel% 與擊球型態的分母

**問題**(`statcast.py:936` `_batted_ball_metrics`):
- `barrel_pct` 分母用「全部 in-play」,但 `hard_hit_pct` 用「有測得 EV 的 BBE」。MiLB 大量擊球無 EV 數據,Barrel% 被系統性低估。Savant 兩者皆以有測得 EV 的 BBE 為分母。
- `gb_pct`/`ld_pct`/`fb_pct`/`pu_pct`/`air_pct` 分母含「軌跡未知」的擊球,稀釋比例。改用已分類軌跡總數。
- `pull_pct`/`straight_pct`/`oppo_pct`/`pull_air_pct` 同理,改用 `spray_total`(方向可判定的擊球數)。

**Files:**
- Modify: `site_builder/statcast.py:936-965`(`_batted_ball_metrics`)
- Test: `tests/test_statcast.py`

- [ ] **Step 1: 寫失敗測試**

附加到 `tests/test_statcast.py`:

```python
from site_builder.statcast import _aggregate_pitches, _batted_ball_metrics


def _bbe(ev=None, la=None, traj="fly_ball", x=None, y=None):
    """合成一顆 in-play 擊球。"""
    return {
        "result_code": "X", "is_in_play": True,
        "ev": ev, "la": la, "trajectory": traj,
        "hit_coord_x": x, "hit_coord_y": y,
    }


def test_barrel_pct_uses_measured_ev_denominator():
    # 3 顆 in-play:1 顆 barrel(100mph/28°)、1 顆弱擊球、1 顆無 EV 數據
    pitches = [_bbe(ev=100, la=28), _bbe(ev=50, la=10), _bbe()]
    metrics = _batted_ball_metrics(_aggregate_pitches(pitches))
    assert metrics["bbe"] == 3
    assert metrics["barrel_pct"] == 0.5      # 1/2(僅計有 EV 的)
    assert metrics["hard_hit_pct"] == 0.5    # 1/2(維持原行為)


def test_trajectory_pcts_use_classified_denominator():
    # 1 滾地 + 1 飛球 + 1 軌跡未知 → GB% 應為 1/2 而非 1/3
    pitches = [_bbe(traj="ground_ball"), _bbe(traj="fly_ball"), _bbe(traj="")]
    metrics = _batted_ball_metrics(_aggregate_pitches(pitches))
    assert metrics["gb_pct"] == 0.5
    assert metrics["fb_pct"] == 0.5
    assert metrics["air_pct"] == 0.5


def test_spray_pcts_use_spray_total_denominator():
    # 2 顆可判定方向(座標)+ 1 顆無方向資訊
    # x=30,y=100 在本壘左側 → 右打者拉打;x=125.42 → 中間方向
    pitches = [
        _bbe(traj="fly_ball", x=30.0, y=100.0) | {"bat_side": "R"},
        _bbe(traj="fly_ball", x=125.42, y=100.0) | {"bat_side": "R"},
        _bbe(traj="fly_ball"),
    ]
    metrics = _batted_ball_metrics(_aggregate_pitches(pitches))
    assert metrics["pull_pct"] == 0.5
    assert metrics["straight_pct"] == 0.5
```

- [ ] **Step 2: 執行確認失敗**

Run: `python3 -m pytest tests/test_statcast.py -v`
Expected: 新增 3 個測試 FAIL(現行分母為 n_ip)

- [ ] **Step 3: 修改 `_batted_ball_metrics`**

整個函式改為:

```python
def _batted_ball_metrics(agg: dict, sport_level: str = "") -> dict:
    """Build batted-ball metrics dict from _aggregate_pitches output.

    分母原則(對齊 Baseball Savant):
      - barrel_pct / hard_hit_pct / avg_ev → 有測得 EV 的 BBE(n_ev)
      - gb/ld/fb/pu/air → 軌跡已分類的擊球數(classified)
      - pull/straight/oppo/pull_air → 方向可判定的擊球數(spray_total)
    MiLB 缺測資料多,用全部 in-play 當分母會系統性低估比例。
    """
    n_ip = len(agg["in_play"])
    n_ev = len(agg["bbe_ev"])
    classified = agg["gb"] + agg["ld"] + agg["fb"] + agg["pu"]
    spray_total = agg.get("spray_total") or 0
    metrics = {
        "bbe": n_ip,
        "gb_pct": _ratio(agg["gb"], classified, digits=_BATTED_BALL_RATE_DIGITS),
        "ld_pct": _ratio(agg["ld"], classified, digits=_BATTED_BALL_RATE_DIGITS),
        "fb_pct": _ratio(agg["fb"], classified, digits=_BATTED_BALL_RATE_DIGITS),
        "pu_pct": _ratio(agg["pu"], classified, digits=_BATTED_BALL_RATE_DIGITS),
        "air_pct": _ratio(
            agg["ld"] + agg["fb"], classified, digits=_BATTED_BALL_RATE_DIGITS
        ),
        "pull_pct": None,
        "straight_pct": None,
        "oppo_pct": None,
        "pull_air_pct": None,
        "barrel_pct": _ratio(agg["barrels"], n_ev),
        "hard_hit_pct": _ratio(agg["hard_hits"], n_ev),
        "avg_ev": _mean_round([p["ev"] for p in agg["bbe_ev"]], 1),
    }
    if spray_total:
        metrics.update({
            "pull_pct": _ratio(agg["pull"], spray_total, digits=_BATTED_BALL_RATE_DIGITS),
            "straight_pct": _ratio(agg["straight"], spray_total, digits=_BATTED_BALL_RATE_DIGITS),
            "oppo_pct": _ratio(agg["oppo"], spray_total, digits=_BATTED_BALL_RATE_DIGITS),
            "pull_air_pct": _ratio(agg["pull_air"], spray_total, digits=_BATTED_BALL_RATE_DIGITS),
        })
    return metrics
```

同時把 `_compute_pitch_outcomes_pitcher`(statcast.py:1125-1126)與 `_compute_vs_pitch_types_batter`(statcast.py:1341-1342)中的:

```python
            "barrel_pct": _ratio(agg["barrels"], len(agg["in_play"])),
```

改為:

```python
            "barrel_pct": _ratio(agg["barrels"], len(agg["bbe_ev"])),
```

(兩處,`hard_hit_pct` 原本就用 `bbe_ev` 不動。)

- [ ] **Step 4: 執行測試確認通過**

Run: `python3 -m pytest tests/ -v`
Expected: all passed

- [ ] **Step 5: 重算資料庫聚合並重建**

Run: `python build.py statcast && python build.py build`
Expected: 兩者正常完成。注意:此修正會改變顯示數字(MiLB 球員 Barrel% 普遍上升),屬預期行為。

- [ ] **Step 6: Commit**

```bash
git add tests/test_statcast.py && git commit -m "test: cover batted-ball metric denominators"
git add site_builder/statcast.py && git commit -m "fix: align barrel/trajectory/spray denominators with measured BBE"
```

### Task 4: 同年同層級多隊的 Statcast 重複計權

**問題**:`_merge_statcast_into_season`(sync.py:891)把整層級的全年聚合寫進「每一個」`sport_level` 相符的隊伍列。若球員同年在同層級換隊(年中交易),`builder.py:1025-1041` 建立 `statcast_by_year` 時會出現兩筆相同聚合 → Statcast 概覽顯示兩列相同數字,且 `_combine_statcast_dicts` 將其雙倍計權。

**Fix**:builder 端以 `(year, sport_level)` 去重(同時涵蓋既有資料庫中已寫入的重複副本)。

**Files:**
- Modify: `site_builder/builder.py:1025-1041`
- Create: `tests/test_builder.py`

- [ ] **Step 1: 將該段邏輯抽成可測函式並寫失敗測試**

`tests/test_builder.py`:

```python
"""builder.py 資料組裝測試。"""

from site_builder.builder import _build_statcast_entries
from site_builder.helpers import Obj


def _stat_row(year, level, team, sc):
    s = Obj()
    s.year = year
    s.sport_level = level
    s.team_name = team
    s["statcast"] = sc
    return s


def test_statcast_entries_dedupe_same_year_level():
    # 同年同層級兩隊:整層級聚合相同,只應取一筆
    sc = {"total_pitches": 100, "woba": 0.300}
    rows = [
        _stat_row(2025, "AAA", "Team A", sc),
        _stat_row(2025, "AAA", "Team B", sc),
        _stat_row(2025, "AA", "Team C", {"total_pitches": 50}),
    ]
    by_year = _build_statcast_entries(rows, is_pitcher=False,
                                      movement_by_year_level={})
    levels = [e["sport_level"] for e in by_year[2025]]
    assert levels == ["AAA", "AA"]
```

- [ ] **Step 2: 執行確認失敗**

Run: `python3 -m pytest tests/test_builder.py -v`
Expected: FAIL — `ImportError: cannot import name '_build_statcast_entries'`

- [ ] **Step 3: 抽出函式並加去重**

在 `builder.py` 的 `_load_player_bundle` 之前新增:

```python
def _build_statcast_entries(
    all_stats,
    is_pitcher: bool,
    movement_by_year_level: dict,
) -> dict[int, list]:
    """Season-level Statcast data keyed by year → list of entries.

    同年同層級多隊時,_merge_statcast_into_season 會把相同的整層級
    聚合寫進每個隊伍列;這裡以 (year, sport_level) 去重,
    避免 Statcast 表格出現重複列、合計被雙倍計權。
    """
    statcast_by_year: dict[int, list] = {}
    seen_year_levels: set[tuple[int, str]] = set()
    for s in all_stats:
        raw_sc = s.get("statcast")
        if not raw_sc:
            continue
        key = (s.year, s.sport_level)
        if key in seen_year_levels:
            continue
        seen_year_levels.add(key)
        sc = dict(raw_sc)
        if is_pitcher:
            movement = movement_by_year_level.get((s.year, s.sport_level))
            if movement and movement.get("total_pitches"):
                sc["pitch_movement"] = movement
            else:
                sc.setdefault("pitch_movement", raw_sc.get("pitch_movement") or {})
        statcast_by_year.setdefault(s.year, []).append({
            "sport_level": s.sport_level,
            "team_name": s.team_name,
            "sc": sc,
            "stat": s,
        })
    return statcast_by_year
```

把 `build_static_site` 中原本的迴圈(搜尋錨點 `# Season-level Statcast data keyed by year` 至 `"stat": s,` 後的 `})` 區塊)整段替換為:

```python
        statcast_by_year = _build_statcast_entries(
            all_stats, player.is_pitcher, movement_by_year_level
        )
```

(其後 `for yr_key, yr_entries in statcast_by_year.items():` 的 `_combined` 插入邏輯不變。)

- [ ] **Step 4: 執行測試確認通過**

Run: `python3 -m pytest tests/ -v`
Expected: all passed

- [ ] **Step 5: 建置後驗證 dist 無重複列**

Run: `python build.py build` 後執行:

```bash
python3 - <<'EOF'
import glob, re, sys
bad = []
for path in glob.glob('dist/player/*/index.html'):
    html = open(path).read()
    m = re.search(r'id="stats-table-sc".*?</table>', html, re.S)
    if not m:
        continue
    rows = re.findall(
        r'<td><strong>(\d{4})</strong></td>\s*<td><span class="level-tag level-(\w+)',
        m.group(0))
    if len(rows) != len(set(rows)):
        bad.append((path, rows))
print("duplicate (year, level) rows:", bad or "none")
sys.exit(1 if bad else 0)
EOF
```

Expected: `duplicate (year, level) rows: none`,exit 0

- [ ] **Step 6: Commit**

```bash
git add tests/test_builder.py && git commit -m "test: cover statcast entry dedupe for same-year-level multi-team"
git add site_builder/builder.py && git commit -m "fix: dedupe statcast entries by (year, level) to stop double-weighting"
```

### Task 5: 投手/打者 K%、BB% 鍵值衝突

**問題**:`helpers.py:432-444` 投手 K%(SO/BF)與打者 K%(SO/PA)共用 `k_pct`/`bb_pct` 鍵。投打雙修球員(投手該季有打席)時,打者公式先填值、投手公式被 None-guard 擋住,投手進階表會顯示打擊 K%。

**Fix**:投手改用 `p_k_pct`/`p_bb_pct`(與既有 `p_avg`/`p_babip` 命名一致),模板跟進。

**Files:**
- Modify: `site_builder/helpers.py:432-444`
- Modify: `src/templates/tabs/tab_advanced.j2:47-48,93-94`
- Modify: `src/templates/mobile/sections/m_advanced.j2:18-19`
- Test: `tests/test_helpers.py`

- [ ] **Step 1: 寫失敗測試**

附加到 `tests/test_helpers.py`:

```python
from site_builder.helpers import Obj, _compute_advanced_stats


def test_pitcher_kpct_not_clobbered_by_batting_stats():
    # 投打雙修:投手 K% 用 SO/BF,打者 K% 用 SO/PA,兩者必須分開
    s = Obj({"so": 50, "bf": 200, "bb": 20, "h_so": 20, "pa": 60, "hit_bb": 6})
    _compute_advanced_stats(s)
    assert s["p_k_pct"] == 0.25            # 50/200
    assert s["p_bb_pct"] == 0.1            # 20/200
    assert s["k_pct"] == round(20 / 60, 3) # 打者欄位不受影響
    assert s["bb_pct"] == 0.1              # 6/60


def test_pure_pitcher_has_no_batter_kpct():
    s = Obj({"so": 30, "bf": 100, "bb": 10})
    _compute_advanced_stats(s)
    assert s["p_k_pct"] == 0.3
    assert s.get("k_pct") is None
```

- [ ] **Step 2: 執行確認失敗**

Run: `python3 -m pytest tests/test_helpers.py -v`
Expected: FAIL — `p_k_pct` 為 None

- [ ] **Step 3: 修改 `_compute_advanced_stats` 投手區塊**

`helpers.py` 中(搜尋錨點 `# Pitcher K% = SO / BF`)把:

```python
    # Pitcher K% = SO / BF
    if s.get("k_pct") is None:
        so = s.get("so")
        bf = s.get("bf")
        if so is not None and bf and bf > 0:
            s["k_pct"] = round(so / bf, 3)

    # Pitcher BB% = BB / BF
    if s.get("bb_pct") is None:
        bb = s.get("bb")
        bf = s.get("bf")
        if bb is not None and bf and bf > 0:
            s["bb_pct"] = round(bb / bf, 3)
```

改為:

```python
    # Pitcher K% = SO / BF(用 p_ 前綴與打者 k_pct 區隔,
    # 避免投打雙修時打擊數據覆蓋投球數據)
    if s.get("p_k_pct") is None:
        so = s.get("so")
        bf = s.get("bf")
        if so is not None and bf and bf > 0:
            s["p_k_pct"] = round(so / bf, 3)

    # Pitcher BB% = BB / BF
    if s.get("p_bb_pct") is None:
        bb = s.get("bb")
        bf = s.get("bf")
        if bb is not None and bf and bf > 0:
            s["p_bb_pct"] = round(bb / bf, 3)
```

- [ ] **Step 4: 更新模板(投手分支才改,打者分支不動)**

`src/templates/tabs/tab_advanced.j2` — `{% if is_pitcher %}` 分支內兩處(summary 列與 detail 列):

```jinja
                            <td class="num">{{ sm.p_k_pct|pct_fmt }}</td>
                            <td class="num">{{ sm.p_bb_pct|pct_fmt }}</td>
```

```jinja
                            <td class="num">{{ stat.p_k_pct|pct_fmt }}</td>
                            <td class="num">{{ stat.p_bb_pct|pct_fmt }}</td>
```

`src/templates/mobile/sections/m_advanced.j2` — `adv_body` macro 的 `{% if is_pitcher %}` 分支:

```jinja
        {{ mcell('K%', s.p_k_pct|pct_fmt) }}
        {{ mcell('BB%', s.p_bb_pct|pct_fmt) }}
```

- [ ] **Step 5: 確認沒有遺漏的投手用 k_pct**

Run: `grep -rn "k_pct\|bb_pct" src/templates/ | grep -v "p_k_pct\|p_bb_pct"`
Expected: 僅剩打者分支(tab_advanced.j2 batter 區、m_advanced.j2 batter hero/grid)。

- [ ] **Step 6: 測試 + 建置驗證**

Run: `python3 -m pytest tests/ -v && python build.py build`
然後抽查一位投手頁(678906)進階表 K% 數字不為空:

```bash
grep -A2 '<th data-tooltip="三振率：SO ÷ 面對打者數">K%</th>' dist/player/678906/index.html | head -3
```

- [ ] **Step 7: Commit**

```bash
git add tests/test_helpers.py && git commit -m "test: cover pitcher/batter K%/BB% key separation"
git add site_builder/helpers.py && git commit -m "fix: namespace pitcher K%/BB% as p_k_pct/p_bb_pct"
git add src/templates/tabs/tab_advanced.j2 && git commit -m "fix: read p_k_pct/p_bb_pct in desktop pitcher advanced table"
git add src/templates/mobile/sections/m_advanced.j2 && git commit -m "fix: read p_k_pct/p_bb_pct in mobile pitcher advanced cards"
```

---

## Phase 2 — 常數收斂與重複碼消除

### Task 6: statcast.py 公開共用常數與輔助函式

builder.py 與 statcast.py 各養一份 `_COUNT_USAGE_BUCKETS`/`_PLINKO_*`/`_BAT_SIDE_SPLITS`/`_ratio`/`_is_unknown_pitch_type`,且 label 已分岔(builder 英文、statcast 中文)→ 合計列顯示 "Pitcher Ahead"、單層級顯示「球數領先」。本 Task 先在 statcast.py 提供公開名稱,Task 7 讓 builder 改用。

**Files:**
- Modify: `site_builder/statcast.py`(檔尾新增公開別名)
- Test: `tests/test_statcast.py`

- [ ] **Step 1: 寫失敗測試**

附加到 `tests/test_statcast.py`:

```python
def test_public_shared_constants_exported():
    from site_builder import statcast as sc
    assert sc.ratio(1, 4) == 0.25
    assert sc.is_unknown_pitch_type("UN") is True
    assert sc.is_unknown_pitch_type("FF") is False
    # 配球 bucket 必須是中文標籤的單一來源
    assert [b["key"] for b in sc.COUNT_USAGE_BUCKETS] == [
        "early", "pitcher_ahead", "pitcher_behind",
        "pre_two_strikes", "two_strikes",
    ]
    assert sc.COUNT_USAGE_BUCKETS[1]["label"] == "球數領先"
    assert sc.PLINKO_COUNT_LABELS[0] == "0-0"
    assert ("0-0", "0-1") in sc.PLINKO_EDGES
    assert sc.BAT_SIDE_SPLITS[0] == ("all", "全部")
```

- [ ] **Step 2: 執行確認失敗**

Run: `python3 -m pytest tests/test_statcast.py::test_public_shared_constants_exported -v`
Expected: FAIL — AttributeError

- [ ] **Step 3: 在 statcast.py 檔尾新增公開別名**

```python
# ══════════════════════════════════════════════════════════════════════════
# 公開共用常數 / 輔助(builder、statcast_combine 共用的單一來源)
# ══════════════════════════════════════════════════════════════════════════

ratio = _ratio
is_unknown_pitch_type = _is_unknown_pitch_type
COUNT_USAGE_BUCKETS = _COUNT_USAGE_BUCKETS
PLINKO_COUNT_LABELS = tuple(_count_label(c) for c in _PLINKO_COUNTS)
PLINKO_EDGES = _PLINKO_EDGES
BAT_SIDE_SPLITS = _BAT_SIDE_SPLITS
```

- [ ] **Step 4: 測試通過後 Commit**

Run: `python3 -m pytest tests/ -v`

```bash
git add tests/test_statcast.py && git commit -m "test: lock public shared statcast constants"
git add site_builder/statcast.py && git commit -m "refactor: export shared pitch constants/helpers from statcast"
```

### Task 7: 建立 `statcast_combine.py`,builder 移除重複定義

把 builder.py L48–557 的跨層級合併邏輯搬到新模組,改吃 Task 6 的共用常數,順帶修掉中英文標籤分岔。

**Files:**
- Create: `site_builder/statcast_combine.py`
- Modify: `site_builder/builder.py`
- Test: `tests/test_combine.py`(新檔)

- [ ] **Step 1: 寫失敗測試(鎖定標籤一致性)**

`tests/test_combine.py`:

```python
"""statcast_combine.py 跨層級合併測試。"""

from site_builder.statcast import (
    COUNT_USAGE_BUCKETS,
    _compute_pitch_usage_by_count_pitcher,
)
from site_builder.statcast_combine import (
    _combine_pitch_usage_by_count,
    _combine_statcast_dicts,
)


def _pitch(ptype, pre=(0, 0)):
    return {
        "pitch_type": ptype, "pitch_name": ptype,
        "pre_balls": pre[0], "pre_strikes": pre[1],
        "balls": pre[0], "strikes": pre[1],
    }


def test_combined_usage_labels_match_per_level_chinese():
    usage = _compute_pitch_usage_by_count_pitcher(
        [_pitch("FF"), _pitch("SL", pre=(0, 2))]
    )
    entries = [{"sport_level": "AAA", "sc": {"pitch_usage_by_count": usage}}]
    combined = _combine_pitch_usage_by_count(entries)
    # 合計列標籤必須與單層級(中文)完全一致 — 修正英文/中文分岔 bug
    assert [r["label"] for r in combined["rows"]] == \
        [b["label"] for b in COUNT_USAGE_BUCKETS]
    assert "Pitcher Ahead" not in [r["label"] for r in combined["rows"]]


def test_combine_statcast_dicts_weighted_average():
    entries = [
        {"sport_level": "AAA", "sc": {"total_pitches": 100, "whiff_pct": 0.30,
                                      "bbe": 10, "pa_count": 25}},
        {"sport_level": "AA",  "sc": {"total_pitches": 300, "whiff_pct": 0.10,
                                      "bbe": 30, "pa_count": 75}},
    ]
    combined = _combine_statcast_dicts(entries)
    assert combined["total_pitches"] == 400
    assert combined["whiff_pct"] == 0.15  # (0.3*100 + 0.1*300) / 400
```

- [ ] **Step 2: 執行確認失敗**

Run: `python3 -m pytest tests/test_combine.py -v`
Expected: FAIL — `ModuleNotFoundError: site_builder.statcast_combine`

- [ ] **Step 3: 建立 `site_builder/statcast_combine.py`**

檔頭:

```python
"""跨層級(MLB/AAA/AA…)Statcast 聚合的加權合併。

由 builder.py 在「同年多層級」時呼叫,產生 _combined 合計列。
所有 bucket / plinko / 打席邊常數一律 import 自 statcast.py,
不得在此重新定義(歷史教訓:builder 曾自帶一份英文標籤導致 UI 中英混用)。
"""

from site_builder.statcast import (
    BAT_SIDE_SPLITS,
    COUNT_USAGE_BUCKETS,
    PLINKO_COUNT_LABELS,
    PLINKO_EDGES,
    is_unknown_pitch_type,
    ratio,
)
```

然後把 builder.py 中下列函式**原樣搬移**(連同其 docstring 與內部邏輯;行號為搜尋起點):

| 函式 | builder.py 原位置 |
|---|---|
| `_combine_pitch_type_data` | L94 |
| `_combine_vs_pitch_types` | L166 |
| `_combine_pitch_outcomes` | L179 |
| `_combine_pitch_arsenal` | L192 |
| `_combine_pitch_usage_by_count` | L205 |
| `_combine_pitcher_bat_side_splits` | L274 |
| `_combine_pitch_plinko` | L306 |
| `_combine_pitch_movement` | L418 |
| `_combine_statcast_dicts` | L479 |

搬移時做以下機械替換:
1. `_is_unknown_pitch_type(` → `is_unknown_pitch_type(`
2. `_ratio(` → `ratio(`,並在每個原呼叫處保留原精度:builder 版 `_ratio` 預設 4 位,因此所有 `ratio(x, y)` 呼叫改為 `ratio(x, y, digits=4)`(statcast 版預設 3 位,顯式傳 4 保持輸出不變)。
3. `_BAT_SIDE_SPLITS` → `BAT_SIDE_SPLITS`
4. `_PLINKO_COUNTS` → `PLINKO_COUNT_LABELS`(builder 版本來就是 label 字串 tuple,語意相同)
5. `_PLINKO_EDGES` → `PLINKO_EDGES`

`_combine_pitch_usage_by_count` 是唯一需要**邏輯修改**的函式(bucket 結構從 builder 的 3-tuple 改為 statcast 的 dict,且不再有 `all` bucket),完整新版:

```python
def _combine_pitch_usage_by_count(entries: list[dict]) -> dict:
    """Combine per-level count-bucket pitch usage by summing raw counts.

    bucket 定義(key/中文 label/counts_label)以 COUNT_USAGE_BUCKETS 為
    單一來源;不含 'all' bucket(模板本來就跳過 row.key == 'all')。
    """
    type_names: dict[str, str] = {}
    totals_by_type: dict[str, int] = {}
    bucket_data = {
        b["key"]: {"pitches": 0, "type_counts": {}}
        for b in COUNT_USAGE_BUCKETS
    }

    for e in entries:
        if e.get("sport_level") == "_combined":
            continue
        usage = ((e.get("sc") or {}).get("pitch_usage_by_count") or {})
        for pt in usage.get("pitch_types") or []:
            ptype = pt.get("type") or "UN"
            if is_unknown_pitch_type(ptype, pt.get("name")):
                continue
            type_names[ptype] = pt.get("name") or ptype
            totals_by_type[ptype] = totals_by_type.get(ptype, 0) + (pt.get("count") or 0)

        for row in usage.get("rows") or []:
            key = row.get("key")
            if key not in bucket_data:
                continue
            bucket = bucket_data[key]
            bucket["pitches"] += row.get("pitches") or 0
            for pt in row.get("pitch_types") or []:
                ptype = pt.get("type") or "UN"
                if is_unknown_pitch_type(ptype, pt.get("name")):
                    continue
                type_names.setdefault(ptype, pt.get("name") or ptype)
                bucket["type_counts"][ptype] = (
                    bucket["type_counts"].get(ptype, 0) + (pt.get("count") or 0)
                )

    if not totals_by_type:
        return {"pitch_types": [], "rows": []}

    ordered_types = sorted(totals_by_type, key=lambda t: totals_by_type[t], reverse=True)
    pitch_types = [
        {"type": t, "name": type_names.get(t, t), "count": totals_by_type[t]}
        for t in ordered_types
    ]

    rows = []
    for b in COUNT_USAGE_BUCKETS:
        bucket = bucket_data[b["key"]]
        total = bucket["pitches"]
        rows.append({
            "key": b["key"],
            "label": b["label"],
            "counts_label": b["counts_label"],
            "pitches": total,
            "pitch_types": [
                {
                    "type": t,
                    "name": type_names.get(t, t),
                    "count": bucket["type_counts"].get(t, 0),
                    "pct": ratio(bucket["type_counts"].get(t, 0), total, digits=4),
                }
                for t in ordered_types
            ],
        })

    return {"pitch_types": pitch_types, "rows": rows}
```

- [ ] **Step 4: builder.py 刪除重複、改 import**

從 `builder.py` 刪除:
- L48–79 的 `_BAT_SIDE_SPLITS`、`_COUNT_USAGE_BUCKETS`、`_PLINKO_COUNTS`、`_PLINKO_EDGES`
- L82–84 `_ratio`、L86–91 `_is_unknown_pitch_type`
- L94–557 全部 `_combine_*` 函式

在 import 區(`from site_builder.statcast import ...` 旁)加:

```python
from site_builder.statcast_combine import _combine_statcast_dicts
```

(builder 只直接呼叫 `_combine_statcast_dicts`;以 `grep -n "_combine_" site_builder/builder.py` 確認無其他引用殘留。)

- [ ] **Step 5: 測試 + 建置 + 中英文驗證**

Run: `python3 -m pytest tests/ -v && python build.py build`
然後:

```bash
grep -c "Pitcher Ahead" dist/player/678906/index.html
```

Expected: `0`(修正前為 36)

```bash
grep -c "球數領先" dist/player/678906/index.html
```

Expected: 非 0(中文標籤一致存在)

- [ ] **Step 6: Commit**

```bash
git add tests/test_combine.py && git commit -m "test: cover cross-level combine labels and weighted averages"
git add site_builder/statcast_combine.py && git commit -m "refactor: extract cross-level statcast combining into statcast_combine"
git add site_builder/builder.py && git commit -m "refactor: drop duplicated combine logic/constants from builder"
```

### Task 8: 抽取 `_pa_outcome_totals` 消除三份 wOBA/AVG 迴圈

`_compute_woba`(statcast.py:902)、`_compute_pitch_outcomes_pitcher`(:1088)、`_compute_vs_pitch_types_batter`(:1300)有三份幾乎相同的 PA 結算迴圈。

**Files:**
- Modify: `site_builder/statcast.py`
- Test: `tests/test_statcast.py`

- [ ] **Step 1: 寫失敗測試**

附加到 `tests/test_statcast.py`:

```python
from site_builder.statcast import _pa_outcome_totals, get_woba_weights


def test_pa_outcome_totals():
    w = get_woba_weights(2024)
    pa_final = [
        {"pa_event": "single"},
        {"pa_event": "walk"},
        {"pa_event": "strikeout"},
        {"pa_event": "sac_bunt"},             # 排除於 wOBA 分母與 AB
        {"pa_event": "caught_stealing_2b"},   # 非打席事件,完全排除
        {"pa_event": "intent_walk"},          # 故意四壞,排除
    ]
    hits, ab, woba_num, woba_den = _pa_outcome_totals(pa_final, w)
    assert (hits, ab, woba_den) == (1, 2, 3)   # single+strikeout 計 AB
    assert abs(woba_num - (w["single"] + w["walk"])) < 1e-9
```

- [ ] **Step 2: 執行確認失敗**

Run: `python3 -m pytest tests/test_statcast.py::test_pa_outcome_totals -v`
Expected: FAIL — ImportError

- [ ] **Step 3: 實作並替換三處呼叫**

在 `_compute_woba` 上方新增:

```python
def _pa_outcome_totals(
    pa_final: list[dict], woba_w: dict
) -> tuple[int, int, float, int]:
    """單一來源的 PA 結算:回傳 (hits, ab, woba_num, woba_den)。

    排除規則:故意四壞、犧牲觸擊不入 wOBA 分母;
    非打席跑壘事件(盜壘刺、牽制出局)完全排除;
    AB = 扣除 BB / HBP / SF / SH。
    """
    hits = 0
    ab = 0
    woba_num = 0.0
    woba_den = 0
    for p in pa_final:
        ev = p.get("pa_event", "")
        if ev in _NON_PA_EVENTS or ev in ("intent_walk", "sac_bunt"):
            continue
        woba_den += 1
        key = WOBA_EVENT_MAP.get(ev)
        if key:
            woba_num += woba_w[key]
        if ev not in ("walk", "hit_by_pitch", "sac_fly", "sac_bunt", "intent_walk"):
            ab += 1
            if ev in ("single", "double", "triple", "home_run"):
                hits += 1
    return hits, ab, woba_num, woba_den
```

`_compute_woba` 改為薄包裝:

```python
def _compute_woba(pa_final: list[dict], woba_w: dict) -> tuple[float, int]:
    """Compute wOBA numerator and denominator from PA-final pitches."""
    _, _, woba_num, woba_den = _pa_outcome_totals(pa_final, woba_w)
    return woba_num, woba_den
```

`_compute_pitch_outcomes_pitcher` 中(搜尋錨點 `hits = 0` 起到 `hits += 1` 的整段迴圈)替換為:

```python
        hits, ab, woba_num, woba_den = _pa_outcome_totals(agg["pa_final"], woba_w)
```

`_compute_vs_pitch_types_batter` 中相同錨點的整段迴圈同樣替換為:

```python
        hits, ab, woba_num, woba_den = _pa_outcome_totals(agg["pa_final"], woba_w)
```

- [ ] **Step 4: 測試 + 建置驗證輸出不變**

Run: `python3 -m pytest tests/ -v && python build.py build`
Expected: 通過、建置成功(此為純重構,顯示數字不應變動)。

- [ ] **Step 5: Commit**

```bash
git add tests/test_statcast.py && git commit -m "test: cover shared PA outcome totals"
git add site_builder/statcast.py && git commit -m "refactor: dedupe wOBA/AVG PA loops into _pa_outcome_totals"
```

### Task 9: 移除 builder 重複計算的 iso

`builder.py:771-773` 計算未捨入的 iso,`_compute_advanced_stats`(helpers.py)又算一次(被前者擋住)。保留 helpers 版(有 round)。

**Files:**
- Modify: `site_builder/builder.py:771-773`

- [ ] **Step 1: 刪除重複行**

`_load_player_bundle` 中刪除:

```python
        slg = safe_float(data.get("slg"))
        avg = safe_float(data.get("avg"))
        data.iso = (slg - avg) if (slg is not None and avg is not None) else None
```

並從檔頭 import 移除 `safe_float`(先 `grep -n "safe_float" site_builder/builder.py` 確認沒有其他使用;若 L924 附近 chart 數據仍在用則保留 import)。

- [ ] **Step 2: 建置驗證 ISO 仍有值**

Run: `python build.py build`

```bash
grep -o '<b>ISO</b>' dist/player/701678/index.html | wc -l
```

Expected: 非 0,且打開頁面 ISO 欄非全 "-"(`annotate_computed_stats` 在渲染前已補算)。

- [ ] **Step 3: Commit**

```bash
git add site_builder/builder.py && git commit -m "refactor: drop duplicated iso computation in player bundle loader"
```

### Task 10: 球種顏色/名稱 JS 單一來源 `pitch-meta.js`

`PITCH_COLORS`/`PITCH_NAMES`/`FALLBACK_COLORS` 在 `pitcher-charts.js` 與 `pitch-plinko.js` 各一份。

**Files:**
- Create: `src/static/js/pitch-meta.js`
- Modify: `src/static/js/pitcher-charts.js`(刪除本地常數)
- Modify: `src/static/js/pitch-plinko.js`(刪除本地常數)
- Modify: `src/templates/player_detail.j2`(載入順序)

- [ ] **Step 1: 建立 `pitch-meta.js`**

```js
/**
 * pitch-meta.js — 球種顏色 / 名稱單一來源
 * 載入於:player_detail.j2(必須在 pitcher-charts.js / pitch-plinko.js 之前)
 * 注:gamelogs.css 的 .pitch-* 標籤色與 m-advanced.css 的 .m-useg 色塊
 * 為「半透明標籤色系」,與此處圖表用飽和色系刻意不同,不在此合併。
 */
window.PITCH_META = {
    COLORS: {
        FF: "#ff0a78", FA: "#ff0a78",
        SI: "#94165d",
        FC: "#c45aa0",
        ST: "#2fc5a7",
        SL: "#68d986",
        CH: "#ff9568",
        CU: "#3326d6", KC: "#3326d6", CS: "#3326d6",
        FS: "#ff6b00", FO: "#ff6b00",
        SV: "#7c3aed",
        KN: "#a3a3a3",
        UN: "#9ca3af"
    },
    NAMES: {
        FF: "4-Seam", FA: "4-Seam",
        SI: "Sinker",
        FC: "Cutter",
        ST: "Sweeper",
        SL: "Slider",
        CH: "Changeup",
        CU: "Curveball", KC: "Curveball", CS: "Curveball",
        FS: "Splitter", FO: "Splitter",
        SV: "Slurve",
        KN: "Knuckleball",
        UN: "Unknown"
    },
    FALLBACK_COLORS: ["#ff0a78", "#94165d", "#c45aa0", "#2fc5a7",
                      "#ff9568", "#68d986", "#3326d6", "#ff6b00"]
};
```

- [ ] **Step 2: 兩個消費端改讀全域**

`pitcher-charts.js` 把本地 `var PITCH_COLORS = {...};`、`var FALLBACK_COLORS = [...];`、`var PITCH_NAMES = {...};` 三段刪除,改為:

```js
    var PITCH_COLORS = (window.PITCH_META || {}).COLORS || {};
    var PITCH_NAMES = (window.PITCH_META || {}).NAMES || {};
    var FALLBACK_COLORS = (window.PITCH_META || {}).FALLBACK_COLORS || [];
```

`pitch-plinko.js` 同樣處理(注意它的 NAMES 是大寫版 "4-SEAM";改讀共用版後在使用處統一:`pitch-plinko.js` 中顯示名稱的地方(搜尋 `PITCH_NAMES[`)外包 `.toUpperCase()`)。

- [ ] **Step 3: 模板載入順序**

`player_detail.j2` 的 `{% block extra_scripts %}` 中,在 `pitcher-charts.js` 之前插入:

```jinja
<script src="{{ static_url('js/pitch-meta.js') }}"></script>
```

- [ ] **Step 4: 建置 + 手動驗證**

Run: `python build.py build && python -m http.server 8000 --directory dist`
打開任一投手頁 → 數據圖表 tab → 確認球種位移散點圖與 Plinko 顏色與改前相同、Plinko 圖例為大寫名稱。

- [ ] **Step 5: Commit**

```bash
git add src/static/js/pitch-meta.js && git commit -m "refactor: add single source for pitch colors/names"
git add src/static/js/pitcher-charts.js && git commit -m "refactor: read pitch meta from shared PITCH_META"
git add src/static/js/pitch-plinko.js && git commit -m "refactor: read pitch meta from shared PITCH_META"
git add src/templates/player_detail.j2 && git commit -m "chore: load pitch-meta.js before chart scripts"
```

### Task 11: 手機模板共用 `mcell` macro

`mcell` 在 `m_stats.j2`/`m_gamelogs.j2`/`m_advanced.j2`/`m_fielding.j2` 各定義一次。

**Files:**
- Create: `src/templates/mobile/_macros.j2`
- Modify: 上述四個 `m_*.j2`

- [ ] **Step 1: 建立共用 macro 檔**

`src/templates/mobile/_macros.j2`:

```jinja
{# 手機版數據卡片共用 macro #}
{% macro mcell(label, value) -%}
<div class="mc-cell"><b>{{ label }}</b><span>{{ value }}</span></div>
{%- endmacro %}
```

- [ ] **Step 2: 四個模板改 import**

每個檔案把開頭的:

```jinja
{% macro mcell(label, value) -%}
<div class="mc-cell"><b>{{ label }}</b><span>{{ value }}</span></div>
{%- endmacro %}
```

替換為:

```jinja
{% from 'mobile/_macros.j2' import mcell %}
```

- [ ] **Step 3: 建置 + diff 驗證輸出完全相同**

```bash
python build.py build && cp dist/player/678906/index.html /tmp/claude/before_macro.html
```

(在改模板「之前」先存基準檔;改完後再 build 一次)

```bash
python build.py build && diff /tmp/claude/before_macro.html dist/player/678906/index.html && echo IDENTICAL
```

Expected: `IDENTICAL`(僅允許 build_time 時間戳行不同;可先 `grep -v "更新："` 再 diff)

- [ ] **Step 4: Commit(每檔一個)**

```bash
git add src/templates/mobile/_macros.j2 && git commit -m "refactor: add shared mobile mcell macro"
git add src/templates/mobile/sections/m_stats.j2 && git commit -m "refactor: import shared mcell macro in m_stats"
git add src/templates/mobile/sections/m_gamelogs.j2 && git commit -m "refactor: import shared mcell macro in m_gamelogs"
git add src/templates/mobile/sections/m_advanced.j2 && git commit -m "refactor: import shared mcell macro in m_advanced"
git add src/templates/mobile/sections/m_fielding.j2 && git commit -m "refactor: import shared mcell macro in m_fielding"
```

---

## Phase 3 — 安全性

### Task 12: `pitch-log.js` 補 HTML 轉義

**問題**:`_buildPitchTable` 把 `p.result`、`p.pa_event`、`p.pitch_name`、`p.pitch_type`(MLB API 第三方資料)未轉義直接拼進 innerHTML — stored XSS 面。

**Files:**
- Modify: `src/static/js/pitch-log.js`

- [ ] **Step 1: 加入轉義函式**

在 `_fmt` 旁新增:

```js
// XSS 防護:API 回傳字串一律轉義後才進 innerHTML
function _esc(v) {
    return String(v == null ? '' : v)
        .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
}
```

- [ ] **Step 2: 套用到所有字串插值點**

`_buildPitchTable` 中:

```js
        var pt = String(p.pitch_type || '').toLowerCase().replace(/[^a-z0-9]/g, '');
        var pn = _esc(p.pitch_name || p.pitch_type || '—');
```

(原本 `var pt = (p.pitch_type || '').toLowerCase();` 改為白名單過濾,避免 class 屬性注入。)

```js
            '<td>' + (_esc(p.result) || '—') + '</td>' +
```

```js
            '<td>' + (p.pa_event ? '<span class="pa-event-tag">' + _esc(p.pa_event) + '</span>' : '') + '</td></tr>';
```

- [ ] **Step 3: 驗證**

Run: `python build.py build && python -m http.server 8000 --directory dist`
打開球員頁 → 比賽紀錄 → 展開逐球紀錄,確認表格正常顯示(球種標籤、結果、PA Event 中文無亂碼)。

並用 node(若有)或瀏覽器 console 快驗:

```js
_esc('<img src=x onerror=alert(1)>')
// 應輸出 "&lt;img src=x onerror=alert(1)&gt;"
```

- [ ] **Step 4: Commit**

```bash
git add src/static/js/pitch-log.js && git commit -m "fix: escape API strings in pitch log innerHTML rendering"
```

### Task 13: Chart.js 本地 vendor 取代未鎖版 CDN

**問題**:`player_detail.j2:95` 以 `https://cdn.jsdelivr.net/npm/chart.js` 載入「永遠最新版」— 供應鏈風險 + 上游 major 改版直接破圖。全站其餘資源皆自託管,Chart.js 比照。

**Files:**
- Create: `src/static/js/vendor/chart.umd.min.js`
- Modify: `src/templates/player_detail.j2:95`

- [ ] **Step 1: 查最新 4.x 版本並下載**

```bash
curl -s https://data.jsdelivr.com/v1/packages/npm/chart.js/resolved?specifier=4 | python3 -c "import sys,json;print(json.load(sys.stdin)['version'])"
```

以回傳版本(例 `4.4.9`,以實際為準,記為 `$VER`)下載:

```bash
mkdir -p src/static/js/vendor
curl -fL "https://cdn.jsdelivr.net/npm/chart.js@$VER/dist/chart.umd.min.js" \
  -o src/static/js/vendor/chart.umd.min.js
head -c 200 src/static/js/vendor/chart.umd.min.js   # 確認是 JS 不是錯誤頁
```

並在檔案第一行上方加註來源(方便日後升版):

```bash
printf '/*! chart.js %s — vendored from https://cdn.jsdelivr.net/npm/chart.js@%s/dist/chart.umd.min.js */\n' "$VER" "$VER" | cat - src/static/js/vendor/chart.umd.min.js > /tmp/claude/chart.tmp && mv /tmp/claude/chart.tmp src/static/js/vendor/chart.umd.min.js
```

- [ ] **Step 2: 模板改引用本地檔**

`player_detail.j2` 把:

```jinja
<script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
```

改為:

```jinja
<script src="{{ static_url('js/vendor/chart.umd.min.js') }}"></script>
```

- [ ] **Step 3: 驗證**

Run: `python build.py build && python -m http.server 8000 --directory dist`
打開有出賽紀錄的球員頁 → 數據圖表 → 賽季走勢折線圖正常渲染(桌面 `#performanceChart` 與手機 `#mPerformanceChart` 皆檢查)。

```bash
grep -c "cdn.jsdelivr.net" dist/player/678906/index.html
```

Expected: `0`

- [ ] **Step 4: Commit**

```bash
git add src/static/js/vendor/chart.umd.min.js && git commit -m "chore: vendor chart.js (pinned) to remove unpinned CDN dependency"
git add src/templates/player_detail.j2 && git commit -m "fix: load vendored chart.js instead of unpinned CDN"
```

---

## Phase 4 — 網頁效能

### Task 14: 圖表 JSON 外部化 + 懶載入(最大單項,~50% 頁面瘦身)

**問題**:`tab_plot.j2` 與 `m_plot.j2` 把 `pitch-movement-data`(實測 1,079KB)、`pitch-usage-hand-data`(340KB)、`pitch-plinko-data`(240KB)以 inline JSON 嵌入,且桌面/手機各一份;`pitch-plinko.js`/`pitcher-charts.js` 還在 DOMContentLoaded 對「所有隱藏容器」eager 渲染 SVG。

**Fix**:builder 將三種 blob 合併輸出為外部 JSON(桌面/手機共用同一 URL);新增 `chart-lazy.js` 統一 fetch + 快取 + 「容器可見才渲染」;三個圖表 JS 改註冊 renderer。

**注意:本 Task 的 6 個 Step 必須一次完成才可部署**(中途狀態圖表會空白)。

**Files:**
- Modify: `site_builder/builder.py`(輸出 JSON、entry 加 chart_src)
- Modify: `src/templates/tabs/tab_plot.j2`
- Modify: `src/templates/mobile/sections/m_plot.j2`
- Create: `src/static/js/chart-lazy.js`
- Modify: `src/static/js/pitch-plinko.js`
- Modify: `src/static/js/pitcher-charts.js`
- Modify: `src/static/js/mobile/m-charts.js`
- Modify: `src/templates/player_detail.j2`(script 順序)

- [ ] **Step 1: builder 輸出圖表 JSON 並在 entry 標 `chart_src`**

`build_static_site` 的 player 迴圈內、`statcast_by_year` 與 `_combined` 插入邏輯完成之後(搜尋錨點 `statcast_available = bool(statcast_by_year)` 之前)插入:

```python
        # ── 圖表資料外部化:plinko / 球種使用 / 位移圖輸出為外部 JSON,
        #    桌面與手機共用同一 URL,由 chart-lazy.js 懶載入。
        charts_dir = out_dir / "data" / "charts" / str(player.mlb_id)
        charts_url_base = f"{normalized_base_url}data/charts/{player.mlb_id}"
        for yr_key, yr_entries in statcast_by_year.items():
            for idx, entry in enumerate(yr_entries):
                sc = entry.get("sc") or {}
                payload = {"plinko": sc.get("pitch_plinko") or {}}
                if player.is_pitcher:
                    payload["usage_hand"] = sc.get("pitcher_bat_side_splits") or {}
                    payload["movement"] = sc.get("pitch_movement") or {}
                charts_dir.mkdir(parents=True, exist_ok=True)
                fname = f"{yr_key}-{idx}.json"
                (charts_dir / fname).write_text(
                    dumps_json(payload), encoding="utf-8"
                )
                entry["chart_src"] = f"{charts_url_base}/{fname}"
```

- [ ] **Step 2: 兩個模板移除 inline JSON、改掛 `data-chart-src`**

`tab_plot.j2` 的 level 容器:

```jinja
            <div class="pitch-plinko-level-container"
                 data-level="{{ _level }}"
                 data-level-label="{% if _level == '_combined' %}All Levels{% else %}{{ _level }}{% endif %}"
                 data-chart-src="{{ _e.chart_src }}"
                 {% if not loop.first %}style="display: none;"{% endif %}>
                {% if is_pitcher %}
                <div class="pitch-chart-grid">
                    <section class="pitch-chart-section">
                        <div class="pitch-usage-hand-root"></div>
                    </section>
                    <section class="pitch-chart-section">
                        <div class="pitch-movement-root"></div>
                    </section>
                </div>
                {% endif %}
                <div class="pitch-plinko-root"></div>
            </div>
```

(刪除三個 `<script type="application/json" class="...">` 與 `{% set _splits %}`/`{% set _movement %}`/`{% set _plinko %}` 行。)

`m_plot.j2` 同樣處理(容器 class 為 `pitch-plinko-level-container m-pitch-plinko-level-container`,同樣加 `data-chart-src="{{ _e.chart_src }}"`、刪三個 inline script 與三個 `{% set %}`)。

- [ ] **Step 3: 建立 `src/static/js/chart-lazy.js`**

```js
/**
 * chart-lazy.js — 圖表資料懶載入器
 * 載入於:player_detail.j2(必須在 pitch-plinko.js / pitcher-charts.js /
 * m-charts.js 之前)
 *
 * 作用:
 *  - 以 data-chart-src 為 key fetch + 快取圖表 JSON(桌面/手機共用同一 URL,
 *    只會下載一次)
 *  - 各圖表模組以 ChartLazy.register(fn) 註冊 renderer;
 *    activate(container) 在資料抵達後依序呼叫所有 renderer
 *  - 只渲染「目前可見」的層級容器;年份/層級切換時由篩選 JS 呼叫
 *    ChartLazy.activateVisible() 補渲染
 */
(function() {
    var cache = Object.create(null);
    var renderers = [];

    function load(src) {
        if (!cache[src]) {
            cache[src] = fetch(src).then(function(resp) {
                if (!resp.ok) throw new Error('HTTP ' + resp.status);
                return resp.json();
            });
        }
        return cache[src];
    }

    function activate(container) {
        if (!container || container.dataset.chartRendered) return;
        var src = container.dataset.chartSrc;
        if (!src) return;
        container.dataset.chartRendered = '1';
        load(src).then(function(data) {
            renderers.forEach(function(fn) { fn(container, data); });
        }).catch(function() {
            delete container.dataset.chartRendered; // 失敗可重試
        });
    }

    function activateVisible() {
        document.querySelectorAll('.pitch-plinko-level-container[data-chart-src]')
            .forEach(function(c) {
                var yearBox = c.parentElement;
                if (c.style.display !== 'none' &&
                    (!yearBox || yearBox.style.display !== 'none')) {
                    activate(c);
                }
            });
    }

    window.ChartLazy = {
        register: function(fn) { renderers.push(fn); },
        activate: activate,
        activateVisible: activateVisible
    };

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', activateVisible);
    } else {
        activateVisible();
    }
})();
```

- [ ] **Step 4: 三個圖表 JS 改為 renderer 註冊制**

`pitch-plinko.js` — 把 `initPitchPlinkoCharts`(eager 全量渲染)整個函式刪除,DOMContentLoaded 區塊改為:

```js
    if (window.ChartLazy) {
        window.ChartLazy.register(function(container, data) {
            var root = container.querySelector('.pitch-plinko-root');
            if (root) renderPitchPlinko(root, (data && data.plinko) || {});
        });
    }

    document.addEventListener("DOMContentLoaded", function() {
        initPitchPlinkoFilters();
    });
```

並在 `initPitchPlinkoFilters` 的 `showLevel` 與 `showYear` 末尾各加:

```js
            if (window.ChartLazy) window.ChartLazy.activateVisible();
```

`pitcher-charts.js` — 把 `initPitcherCharts` 與其 DOMContentLoaded 綁定刪除,檔尾改為:

```js
    if (window.ChartLazy) {
        window.ChartLazy.register(function(container, data) {
            var usageRoot = container.querySelector('.pitch-usage-hand-root');
            if (usageRoot) renderUsageByHand(usageRoot, (data && data.usage_hand) || {});
            var movementRoot = container.querySelector('.pitch-movement-root');
            if (movementRoot) renderMovement(movementRoot, (data && data.movement) || {});
        });
    }
```

(`readJson` 函式若無其他使用者一併刪除。)

`m-charts.js` — `initMobilePlinkoFilters` 的 `showLevel` 與 `showYear` 末尾各加:

```js
            if (window.ChartLazy) window.ChartLazy.activateVisible();
```

- [ ] **Step 5: `player_detail.j2` 調整 script 順序**

在 `pitcher-charts.js` 之前(`pitch-meta.js` 之後)插入:

```jinja
<script src="{{ static_url('js/chart-lazy.js') }}"></script>
```

- [ ] **Step 6: 建置 + 體積與功能驗證**

```bash
python build.py build
ls -lh dist/player/678906/index.html
ls dist/data/charts/678906/ | head -5
grep -c "pitch-movement-data" dist/player/678906/index.html
```

Expected:
- 678906 頁從 ~3.6MB 降至 **~2.1MB 以下**
- `dist/data/charts/678906/` 存在 `{year}-{idx}.json`
- `pitch-movement-data` 出現次數 = 0

手動驗證(`python -m http.server 8000 --directory dist`):
1. 桌面投手頁 → 數據圖表:走勢圖、使用率橫條、位移散點、Plinko 全部渲染
2. 切換年度/層級下拉:新容器的圖即時補渲染
3. 手機模擬器:plot tab 同樣正常,Network 面板確認同一 JSON 只 fetch 一次
4. 打者頁(701678):Plinko 正常、無 console error

- [ ] **Step 7: Commit(每檔一個)**

```bash
git add site_builder/builder.py && git commit -m "perf: externalize chart payloads to per-level JSON files"
git add src/templates/tabs/tab_plot.j2 && git commit -m "perf: replace inline chart JSON with data-chart-src on desktop plot tab"
git add src/templates/mobile/sections/m_plot.j2 && git commit -m "perf: replace inline chart JSON with data-chart-src on mobile plot tab"
git add src/static/js/chart-lazy.js && git commit -m "perf: add lazy chart data loader with shared cache"
git add src/static/js/pitch-plinko.js && git commit -m "perf: render plinko lazily via ChartLazy"
git add src/static/js/pitcher-charts.js && git commit -m "perf: render usage/movement charts lazily via ChartLazy"
git add src/static/js/mobile/m-charts.js && git commit -m "perf: activate visible charts on mobile filter change"
git add src/templates/player_detail.j2 && git commit -m "chore: load chart-lazy.js before chart renderers"
```

### Task 15: 建置時打包 CSS,消除 @import 三層瀑布

**問題**:`style.css` → 12 個 `@import` → `mobile/mobile.css` → 再 10 個,首繪前需序列發現 23 個 CSS 請求。

**Fix**:builder 在複製 static 後,遞迴 inline `@import` 將 `dist/static/css/style.css` 覆寫為單一打包檔(原始分檔仍保留於 dist,無人引用無妨;src 開發體驗不變)。已確認全部 css 僅 gamelogs.css 有一個 data-URI 的 `url()`,無相對路徑資源,inline 安全。

**Files:**
- Modify: `site_builder/builder.py`
- Test: `tests/test_builder.py`

- [ ] **Step 1: 寫失敗測試**

附加到 `tests/test_builder.py`:

```python
from pathlib import Path

from site_builder.builder import _bundle_css


def test_bundle_css_inlines_nested_imports(tmp_path: Path):
    (tmp_path / "sub").mkdir()
    (tmp_path / "a.css").write_text(
        '@import "b.css";\n@import "sub/c.css";\nbody { color: red; }\n',
        encoding="utf-8")
    (tmp_path / "b.css").write_text(".b { x: 1; }\n", encoding="utf-8")
    # 巢狀 import:c.css 內的相對路徑以 c.css 所在目錄為準
    (tmp_path / "sub" / "c.css").write_text(
        '@import "d.css";\n.c { x: 2; }\n', encoding="utf-8")
    (tmp_path / "sub" / "d.css").write_text(".d { x: 3; }\n", encoding="utf-8")

    out = _bundle_css(tmp_path / "a.css")
    assert "@import" not in out
    for token in (".b", ".c", ".d", "body"):
        assert token in out
    # 順序:import 內容在引用位置展開
    assert out.index(".b") < out.index(".c") < out.index("body")
```

- [ ] **Step 2: 執行確認失敗**

Run: `python3 -m pytest tests/test_builder.py -v`
Expected: FAIL — ImportError `_bundle_css`

- [ ] **Step 3: 實作 `_bundle_css` 並接到建置流程**

`builder.py`(import 區補 `import re`)新增:

```python
_CSS_IMPORT_RE = re.compile(r'@import\s+"([^"]+)"\s*;')


def _bundle_css(entry: Path) -> str:
    """遞迴 inline @import,輸出單一 CSS 字串。

    路徑以「目前檔案所在目錄」解析,支援 mobile/mobile.css 這種巢狀
    相對 import。全站 CSS 僅含 data-URI 的 url(),inline 不會破壞資源路徑。
    """
    css = entry.read_text(encoding="utf-8")

    def _inline(match: re.Match) -> str:
        target = (entry.parent / match.group(1)).resolve()
        return _bundle_css(target)

    return _CSS_IMPORT_RE.sub(_inline, css)
```

`build_static_site` 中 `shutil.copytree(static_src, out_dir / "static")` 之後加:

```python
    # 打包 CSS:把 @import 鏈 inline 成單一檔,消除序列請求瀑布
    style_entry = static_src / "css" / "style.css"
    if style_entry.exists():
        (out_dir / "static" / "css" / "style.css").write_text(
            _bundle_css(style_entry), encoding="utf-8"
        )
```

- [ ] **Step 4: 測試 + 建置驗證**

Run: `python3 -m pytest tests/ -v && python build.py build`

```bash
grep -c "@import" dist/static/css/style.css
grep -c "mc-card" dist/static/css/style.css
```

Expected: `@import` = 0;`mc-card` > 0(手機卡片樣式已 inline)。
手動開首頁與球員頁確認樣式無異常。

- [ ] **Step 5: Commit**

```bash
git add tests/test_builder.py && git commit -m "test: cover recursive CSS import bundling"
git add site_builder/builder.py && git commit -m "perf: bundle CSS imports into single stylesheet at build time"
```

### Task 16: `player_detail.j2` script 全面 defer

**Files:**
- Modify: `src/templates/player_detail.j2:84-101`

- [ ] **Step 1: 加 defer**

`{% block extra_scripts %}` 內所有 `<script src=...>` 加上 `defer`(defer 保證依序執行,既有 `pitch-log.js → gamelogs.js` 等依賴順序不變;`type="application/json"` 的兩個資料標籤不動):

```jinja
{% block extra_scripts %}
<script defer src="{{ static_url('js/stats-table.js') }}"></script>
<script defer src="{{ static_url('js/stats-tooltip.js') }}"></script>
<script defer src="{{ static_url('js/pitch-log.js') }}"></script>
<script defer src="{{ static_url('js/gamelogs.js') }}"></script>
<script defer src="{{ static_url('js/mobile/m-pitch-log.js') }}"></script>
<script defer src="{{ static_url('js/mobile/m-gamelogs.js') }}"></script>
<script defer src="{{ static_url('js/arsenal-filters.js') }}"></script>
<script defer src="{{ static_url('js/mobile/m-advanced.js') }}"></script>
<script defer src="{{ static_url('js/pitch-meta.js') }}"></script>
<script defer src="{{ static_url('js/chart-lazy.js') }}"></script>
<script defer src="{{ static_url('js/pitcher-charts.js') }}"></script>
<script defer src="{{ static_url('js/pitch-plinko.js') }}"></script>
{% if chart_data %}
<script defer src="{{ static_url('js/vendor/chart.umd.min.js') }}"></script>
<script type="application/json" id="chart-labels">{{ chart_labels|tojson_safe }}</script>
<script type="application/json" id="chart-data">{{ chart_data|tojson_safe }}</script>
<script defer src="{{ static_url('js/charts.js') }}"></script>
{% endif %}
<script defer src="{{ static_url('js/mobile/m-charts.js') }}"></script>
<script defer src="{{ static_url('js/tabs.js') }}"></script>
{% endblock %}
```

- [ ] **Step 2: 驗證**

`python build.py build` 後手動測試:tab 切換、年度/層級篩選、逐球展開、各圖表渲染、手機底部導覽,全部正常且 console 無錯。

- [ ] **Step 3: Commit**

```bash
git add src/templates/player_detail.j2 && git commit -m "perf: defer all player-page scripts"
```

### Task 17: 移除死碼(JS、CSS)

已驗證:`m-stats.js` 為空殼、`data-m-accordion` 無使用者、`.adv-definitions`/`.def-grid`/`.def-item`/`.def-abbr`/`.def-text` 無模板引用。

**Files:**
- Delete: `src/static/js/mobile/m-stats.js`
- Delete: `src/static/js/mobile/m-accordion.js`
- Modify: `src/templates/base.j2:72,74`
- Modify: `src/static/css/advanced.css`(刪 `.adv-definitions` 區塊)

- [ ] **Step 1: 刪除前最終確認**

```bash
grep -rn "m-stats.js\|m-accordion\|data-m-accordion" src/ | grep -v "js/mobile/m-stats.js\|js/mobile/m-accordion.js"
grep -rn "adv-definitions\|def-grid\|def-item\|def-abbr\|def-text" src/templates/ src/static/js/
```

Expected: 第一條只剩 `base.j2` 兩行 script 標籤;第二條無輸出。

- [ ] **Step 2: 刪檔與引用**

```bash
rm src/static/js/mobile/m-stats.js src/static/js/mobile/m-accordion.js
```

`base.j2` 刪除:

```jinja
<script defer src="{{ static_url('js/mobile/m-accordion.js') }}"></script>
```

```jinja
<script defer src="{{ static_url('js/mobile/m-stats.js') }}"></script>
```

`advanced.css` 刪除 `.adv-definitions`、`.adv-definitions h3`、`.def-grid`、`.def-item`、`.def-abbr`、`.def-text` 六個規則區塊(檔頭註解的對應行一併更新)。

- [ ] **Step 3: 建置 + 驗證**

`python build.py build` 後手動檢查首頁與球員頁 console 無 404、無 JS 錯誤。

- [ ] **Step 4: Commit**

```bash
git add -A src/static/js/mobile/m-stats.js && git commit -m "chore: remove empty m-stats.js module"
git add -A src/static/js/mobile/m-accordion.js && git commit -m "chore: remove unused m-accordion.js module"
git add src/templates/base.j2 && git commit -m "chore: drop script tags for removed mobile JS"
git add src/static/css/advanced.css && git commit -m "chore: remove unused adv-definitions styles"
```

---

## Phase 5 — 可維護性與基礎品質

### Task 18: arsenal 篩選 JS 範圍鎖定,消除桌面/手機互踩

**問題**:`arsenal-filters.js` 的 `showArsenalYear` 用 `document.querySelectorAll(".arsenal-table-container")` 把手機版 `m-arsenal-*` 容器也隱藏,目前僅靠 script 載入順序碰巧蓋回。

**Files:**
- Modify: `src/static/js/arsenal-filters.js`

- [ ] **Step 1: 修改 `showArsenalYear`**

```js
    // 切換年份:只隱藏桌面版年份容器(id 為 arsenal-YYYY),
    // 不可誤傷手機版的 m-arsenal-YYYY(同 class 不同 id 前綴)
    function showArsenalYear() {
        if (!yrSel) return;
        var yr = yrSel.value;
        document.querySelectorAll(".arsenal-table-container").forEach(function(t) {
            if (/^arsenal-\d{4}$/.test(t.id)) t.style.display = "none";
        });
        var tbl = document.getElementById("arsenal-" + yr);
        if (tbl) tbl.style.display = "block";
        updateArsenalLevelOptions();
        showArsenalLevel();
    }
```

- [ ] **Step 2: 驗證**

`python build.py build` + 瀏覽器:
1. 桌面寬度切換進階數據年份 → 用 DevTools 確認 `#m-arsenal-*` 容器的 inline display 不被改動。
2. 縮成手機寬度 → 進階數據球種分析正常顯示、可切年份/層級/左右打。

- [ ] **Step 3: Commit**

```bash
git add src/static/js/arsenal-filters.js && git commit -m "fix: scope desktop arsenal year toggle away from mobile containers"
```

### Task 19: api.py 改用 thread-local Session + Retry

**Files:**
- Modify: `site_builder/api.py`
- Test: `tests/test_api.py`(新檔)

- [ ] **Step 1: 寫失敗測試**

`tests/test_api.py`:

```python
"""api.py HTTP session 管理測試(不打網路)。"""

import threading

from site_builder.api import _session


def test_session_reused_within_thread():
    assert _session() is _session()


def test_session_distinct_across_threads():
    other = {}

    def grab():
        other["s"] = _session()

    t = threading.Thread(target=grab)
    t.start()
    t.join()
    assert other["s"] is not _session()


def test_session_has_retry_adapter():
    adapter = _session().get_adapter("https://statsapi.mlb.com")
    assert adapter.max_retries.total == 3
```

- [ ] **Step 2: 執行確認失敗**

Run: `python3 -m pytest tests/test_api.py -v`
Expected: FAIL — ImportError `_session`

- [ ] **Step 3: 實作**

`api.py` import 區加:

```python
import threading

from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
```

`TIMEOUT = 15` 之後加:

```python
_thread_local = threading.local()


def _session() -> requests.Session:
    """每執行緒一個 Session:連線重用(keep-alive)+ 對暫時性錯誤重試。

    sync.py 以 ThreadPoolExecutor 平行抓取,requests.Session 非執行緒安全,
    因此用 thread-local 隔離。
    """
    s = getattr(_thread_local, "session", None)
    if s is None:
        s = requests.Session()
        retry = Retry(
            total=3,
            backoff_factor=0.5,
            status_forcelist=(429, 500, 502, 503, 504),
            allowed_methods=("GET",),
        )
        adapter = HTTPAdapter(max_retries=retry)
        s.mount("https://", adapter)
        _thread_local.session = s
    return s
```

把檔內全部 13 處 `requests.get(` 改為 `_session().get(`:

```bash
grep -n "requests.get(" site_builder/api.py   # 改完應為 0 筆
```

- [ ] **Step 4: 測試 + 線上煙測**

Run: `python3 -m pytest tests/ -v`
然後對單一球員做真實同步煙測:

```bash
python build.py refresh --player 678906
```

Expected: 正常完成,無 exception。

- [ ] **Step 5: Commit**

```bash
git add tests/test_api.py && git commit -m "test: cover thread-local session with retry"
git add site_builder/api.py && git commit -m "perf: reuse thread-local HTTP sessions with retry/backoff"
```

### Task 20: `DEFAULT_SEASON_YEAR` 自動推算

**問題**:`helpers.py:22` 寫死 `"2026"`、`pages.yml:22` 又寫一份,每年要記得改兩處。

**Fix**:無環境變數時依日期推算(3 月起算當年球季,1–2 月顯示前一年);env 保留為覆寫機制;workflow 移除硬編碼。

**Files:**
- Modify: `site_builder/helpers.py:22`
- Modify: `.github/workflows/pages.yml:22`
- Test: `tests/test_helpers.py`

- [ ] **Step 1: 寫失敗測試**

附加到 `tests/test_helpers.py`:

```python
import datetime

from site_builder.helpers import _default_season_year


def test_default_season_year_in_season(monkeypatch):
    monkeypatch.delenv("DEFAULT_SEASON_YEAR", raising=False)
    assert _default_season_year(datetime.date(2026, 6, 11)) == 2026
    assert _default_season_year(datetime.date(2026, 3, 1)) == 2026


def test_default_season_year_offseason_january(monkeypatch):
    monkeypatch.delenv("DEFAULT_SEASON_YEAR", raising=False)
    # 1–2 月球季未開打,顯示上一個完整球季
    assert _default_season_year(datetime.date(2027, 1, 15)) == 2026


def test_default_season_year_env_override(monkeypatch):
    monkeypatch.setenv("DEFAULT_SEASON_YEAR", "2031")
    assert _default_season_year(datetime.date(2026, 6, 11)) == 2031
```

- [ ] **Step 2: 執行確認失敗**

Run: `python3 -m pytest tests/test_helpers.py -v`
Expected: FAIL — ImportError `_default_season_year`

- [ ] **Step 3: 實作**

`helpers.py` 把:

```python
DEFAULT_SEASON_YEAR = int(os.environ.get("DEFAULT_SEASON_YEAR", "2026"))
```

改為:

```python
def _default_season_year(today: Optional[datetime.date] = None) -> int:
    """目前球季年份:3 月起為當年,1–2 月為前一年。

    環境變數 DEFAULT_SEASON_YEAR 可強制覆寫(CI 或回溯建置用)。
    """
    env = os.environ.get("DEFAULT_SEASON_YEAR")
    if env:
        return int(env)
    today = today or datetime.date.today()
    return today.year if today.month >= 3 else today.year - 1


DEFAULT_SEASON_YEAR = _default_season_year()
```

`.github/workflows/pages.yml` 刪除:

```yaml
  DEFAULT_SEASON_YEAR: "2026"
```

- [ ] **Step 4: 測試 + Commit**

Run: `python3 -m pytest tests/ -v && python build.py build`

```bash
git add tests/test_helpers.py && git commit -m "test: cover season-year auto detection"
git add site_builder/helpers.py && git commit -m "feat: auto-derive DEFAULT_SEASON_YEAR from date with env override"
git add .github/workflows/pages.yml && git commit -m "chore: drop hardcoded DEFAULT_SEASON_YEAR from CI env"
```

### Task 21: UTC+8 時區常數化

**Files:**
- Modify: `site_builder/helpers.py`(新增常數)
- Modify: `site_builder/api.py:264`
- Modify: `site_builder/builder.py:836`

- [ ] **Step 1: helpers 新增常數**

`helpers.py` 的 `SPORT_LEVEL_ORDER` 上方加:

```python
# 台灣時區:全站顯示時間(建置時間、比賽時間)統一使用
TZ_UTC8 = datetime.timezone(datetime.timedelta(hours=8))
```

- [ ] **Step 2: 替換兩個使用點**

`api.py`(`get_next_game` 內):

```python
                            utc8 = datetime.timezone(datetime.timedelta(hours=8))
```

改為(檔頭加 `from site_builder.helpers import TZ_UTC8`,並把 `utc8` 用 `TZ_UTC8` 取代):

```python
                            game_time = dt.astimezone(TZ_UTC8).strftime(
                                "%m/%d %H:%M (UTC+8)"
                            )
```

`builder.py`:

```python
    now_utc8 = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=8)))
```

改為(import 區從 helpers 補 `TZ_UTC8`):

```python
    now_utc8 = datetime.datetime.now(TZ_UTC8)
```

- [ ] **Step 3: 驗證 + Commit**

Run: `python3 -m pytest tests/ -v && python build.py build`(頁尾「更新:」時間正常)

```bash
git add site_builder/helpers.py && git commit -m "refactor: add TZ_UTC8 timezone constant"
git add site_builder/api.py && git commit -m "refactor: use TZ_UTC8 constant in next-game formatting"
git add site_builder/builder.py && git commit -m "refactor: use TZ_UTC8 constant for build timestamp"
```

### Task 22: 文件更正(CLAUDE.md 排程時間)

**Files:**
- Modify: `CLAUDE.md`(此檔在 .gitignore 中,僅本地修改、**不 commit**)

- [ ] **Step 1: 修正排程描述**

`CLAUDE.md` 的 Data Updates 段落:

```markdown
1. **Twice daily** (11:17 AM and 2:17 PM UTC+8): `python build.py refresh --base-url /twbexpats/`
```

(workflow cron 為 `17 3 * * *` 與 `17 6 * * *` UTC,即 11:17 / 14:17 UTC+8;原文「3:17 AM and 6:17 AM UTC+8」是把 UTC 誤標成 UTC+8。)

同時在 Architecture 或 File Organization 段補上 Phase 2 新增的模組:

```markdown
  statcast_combine.py # 跨層級 Statcast 聚合合併(_combined 合計列)
```

---

## 最終驗收清單(全部 Phase 完成後)

- [ ] `python3 -m pytest tests/ -v` 全綠
- [ ] `python build.py build` 成功,`dist/player/678906/index.html` < 2.2MB
- [ ] `grep -rc "Pitcher Ahead" dist/player/*/index.html | grep -v ":0"` 無輸出
- [ ] `grep -c "@import" dist/static/css/style.css` = 0
- [ ] `grep -rc "cdn.jsdelivr.net" dist/player/678906/index.html` = 0
- [ ] 桌面 + 手機模擬器手動巡檢六個 tab:bio / 基礎數據 / 比賽紀錄 / 進階數據 / 守備數據 / 數據圖表,console 無錯誤
- [ ] `python build.py refresh --player 678906` 煙測通過(API session/retry 不影響同步)

---

## 附錄 A — 刻意不排入本計劃的項目(與理由)

| 項目 | 理由 |
|---|---|
| 桌面/手機 JS 成對合併(tabs/gamelogs/arsenal 三對) | 高風險低收益:行為已穩定、Task 18 已消除唯一的互踩點;合併需引入 prefix 參數化工廠,等下次功能需求觸及時再做 |
| 桌面/手機模板合一(響應式單一 markup) | 屬大型改版,需先有設計決策;目前以 Task 11 的共用 macro 降低欄位漂移風險 |
| `Obj.__getattr__` 回 None 的 typo 風險 | 改 strict 模式會牽動全部模板的 optional 欄位存取慣例;以測試覆蓋關鍵欄位替代 |
| 投打雙修球員 game_logs `stats_json` 互相覆蓋 | 現役名單無受影響球員;若未來加入二刀流,需把 hitting/pitching 拆欄位存 |
| FIP_CONSTANTS 補 2025/2026 | 需要聯盟層級的官方常數來源,不可杜撰;暫沿用 2024 fallback(已有註解),取得數據後直接補表即可 |
| GitHub Actions 鎖 commit SHA | 可選強化;若要做:`gh api repos/actions/checkout/git/ref/tags/v4.2.2 --jq .object.sha` 取得 SHA 後替換 `uses:` |

## 附錄 B — 待調查(各 30 分鐘內可得結論)

1. **profile 一次請求帶出 team sport**:驗證 `curl "https://statsapi.mlb.com/api/v1/people/678906?hydrate=currentTeam(sport)"` 回應中 `currentTeam.sport` 是否存在;若是,`get_player_profile` 可移除第二個 `/teams/{id}` 請求(api.py:91)。
2. **seasonAdvanced 一次抓全年份**:比較 `.../stats?stats=seasonAdvanced&group=hitting,pitching`(無 season 參數)與逐年抓取的 splits 是否一致;若一致,`get_player_advanced_stats` 在 sync 模式可從「每年 2 請求」降為「共 2 請求」。

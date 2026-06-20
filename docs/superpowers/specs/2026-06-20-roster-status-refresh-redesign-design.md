# Roster Status 分類與 Refresh 判斷邏輯重寫

**日期**:2026-06-20
**狀態**:設計待審

## 背景與問題

每次 `build.py refresh` 會對每位球員做三選一決策(`site_builder/sync.py`):

| 結果 | 觸發條件 | 行為 |
|---|---|---|
| 完全跳過 `(inactive, status cached)` | DB `players.is_active=0` + 已有 season_stats + 非 `--player` | 連 profile 都不抓,狀態凍結 |
| 只抓 profile `(inactive: profile only)` | 沒被跳過 + 重抓後 `status_category=="inactive"` + 已同步 + refresh 模式 | 更新 profile,跳過 stats/logs |
| 完整抓取 | 其餘 | 全抓 |

### 根本問題

「完全跳過」這層用 `players.is_active`(= MLB API 頂層 `people[0].active`)當開關,而這個訊號:

1. **不可靠**:劉致榮(692617)已 Released 卻頂層 `active=True`;林珺希(842537)`active=False` 卻沒有 rosterEntries。
2. **被凍結**:一旦 `is_active=0` 被跳過,該球員的 `roster_status_code` / `roster_is_active` 永遠停在最後一次抓到的值,不再更新。導致 `/retired` 頁面 76 位離隊球員出現過期狀態徽章。

此外 `categorize_roster_status` 把「已結束的 roster entry」誤判:只有 code ∈ {RL, RET, VL} 才歸 `inactive`,其餘已結束的 entry(code = A / FA / D60 / RES)全落到 `other`。

### API 行為佐證(2026-06-20 即時抓取)

| 球員 | 頂層 active | re0.isActive | code | 描述 | endDate |
|---|---|---|---|---|---|
| 黃暐傑 658791 | False | **False** | D60 | Injured 60-Day | 2024-10-31 |
| 王建民 425426 | False | **False** | RL | Released | 2016-09-22 |
| 陳金鋒 282600 | False | **False** | FA | Free Agent | 2005-10-03 |
| 胡金龍 464341 | False | **False** | **A** | **Active** | 2012-12-31 |
| 林子偉 624407 | False | **False** | **A** | **Active** | 2023-07-25 |
| 倪福德 547820 | False | **False** | RES | Reserve List | 2014-10-23 |
| 劉致榮 692617 | True | **False** | RL | Released | — |
| 鄭浩均 692059 | True | **False** | A | Active | — |

**結論**:`rosterEntries[0].isActive`(roster 層)是唯一可靠的主開關——所有離開體系的球員此值一律 `False`。`code` 只描述「最後那段 roster 關係的類型」,即使該段早已結束(胡金龍/林子偉 ended-`A`、黃暐傑 ended-`D60`),拿它當「現在狀態」必錯。

## 目標

1. 讓**所有**球員(尤其劉致榮、林珺希)每次 refresh 都刷新 profile 與狀態徽章 → 狀態永遠即時。
2. 修正 roster status 分類,讓離隊球員一律正確歸 `inactive`。
3. 維持成本:離隊球員的歷史重資料(yearByYear / advanced / gamelog)仍跳過。

## 設計

### Part A:`categorize_roster_status` 重寫(`helpers.py`)

以 `rosterEntries[0].isActive` 為主開關:

```python
def categorize_roster_status(code, is_active_entry, player_is_active):
    # 完全沒有 roster 歷史 → 退回頂層 active 旗標
    if not code:
        return "active" if player_is_active else "inactive"
    # 最近一段 roster 關係已結束(不在任何 40-man / MiLB 名單上)
    # → 一律 inactive,不管該段的 code 是 A / FA / RL / D60
    if not is_active_entry:
        return "inactive"
    # entry 仍進行中 → 才細分當下狀態
    if code in ROSTER_INJURED_CODES:
        return "injured"
    if code in ROSTER_RESTRICTED_CODES:
        return "restricted"
    if code in ROSTER_OTHER_CODES:
        return "other"
    return "active"
```

- **刪除 `ROSTER_INACTIVE_CODES`(RL/RET/VL)常數**:不再需要列舉碼,任何已結束 entry 都是 inactive。
- `ROSTER_INJURED_CODES` / `ROSTER_RESTRICTED_CODES` / `ROSTER_OTHER_CODES` 保留,只在 entry 進行中(isActive=True)時套用。
- 回傳值不變(active / injured / restricted / inactive / other),CSS 膠囊類別不受影響。

**修正效果**:鄭浩均 ended-A、黃暐傑 ended-D60、胡金龍/林子偉 ended-A 全部正確歸 inactive。

### Part B:徽章文字 `status_display`(`builder.py:769`)

保留 API 描述(Released / Free Agent / Retired),只修正「已離隊卻顯示在隊字樣」的誤導:

```python
MISLEADING_WHEN_OFF_ROSTER = ROSTER_INJURED_CODES | {"A"}

if player.status_category == "inactive" and player.roster_status_code in MISLEADING_WHEN_OFF_ROSTER:
    player.status_display = "Inactive"      # ended-A / ended-D60 等描述會誤導 → 中性標籤
else:
    player.status_display = player.roster_status or ("Active" if player.is_active else "Inactive")
```

- 胡金龍 ended-A → 「Inactive」(不再顯示 Active)
- 黃暐傑 ended-D60 → 「Inactive」(不再顯示 Injured 60-Day)
- 王建民 RL → 「Released」、陳金鋒 FA → 「Free Agent」、倪福德 RES → 「Reserve List (Minors)」(保留離開原因)

### Part C:refresh 判斷邏輯重寫(`sync.py:_run_pipeline` / `_fetch_player_data`)

**移除「完全跳過」層**:刪除 `cached_is_active` map、`players_to_fetch` 過濾迴圈、`(inactive, status cached)` 分支。每位球員都進入抓取流程。

新的每位球員流程(refresh 模式,`only_player=None`):

```
1. 一律抓 profile(1 次輕量 API)→ 更新狀態 / 球隊 / 徽章
2. 用新鮮 profile 算 status_category
3. 重資料(yearByYear / advanced / gamelog / next_game)決策:
   - 若 status_category=="inactive" 且 非首次同步(已有 season_stats)→ 只抓 profile
   - 否則 → 完整抓取(在隊球員、首次回填、或 sync 模式 fetch_all_years)
4. --player 一律完整抓取
```

- `_fetch_player_data` 既有的短路(`if status_category == "inactive" and not fetch_all_years`)維持,因為新的 categorize 讓 `inactive` 精準等於「離隊」。
- `next_game` 對 `status_category=="inactive"` 仍跳過(既有行為)。
- 保留 `_is_first_sync` / `_players_with_existing_stats` 做新人回填。
- DB `is_active` 欄位保留(仍由頂層 active 寫入,當 categorize 無 roster 歷史時的 fallback),但**不再是跳過閘門**。

**效果**:劉致榮、林珺希、所有退役球員每次 refresh 刷新 profile → 狀態即時;歷史重資料對離隊球員仍跳過。代價:每次多約 76 次輕量 profile 呼叫(refresh 一天兩次,可忽略)。

## 影響的檔案

| 檔案 | 變更 |
|---|---|
| `site_builder/helpers.py` | 重寫 `categorize_roster_status`;刪除 `ROSTER_INACTIVE_CODES` |
| `site_builder/builder.py` | `status_display` 加誤導修正邏輯 |
| `site_builder/sync.py` | 移除完全跳過層;`_run_pipeline` 對所有球員抓 profile |

## 測試

- `categorize_roster_status` 單元測試:ended-A/D60/FA/RES → inactive;ongoing injured/restricted/other/active 不變;無 code 退回頂層 active。
- `status_display` 誤導修正:ended-A → Inactive;RL → Released。
- refresh 後驗證:692617 / 842537 profile 有更新;黃暐傑徽章不再是 D60;離隊球員 season_stats 未被重抓(heavy fetch 確實跳過)。

## 不做(YAGNI)

- 不擷取 / 儲存 `endDate`(徽章顯示離開年份是另一個 scope)。
- 不改 `/retired` 頁面歸屬邏輯(`is_active_player` 仍以 season_stats / transaction 判定,與本案無關)。

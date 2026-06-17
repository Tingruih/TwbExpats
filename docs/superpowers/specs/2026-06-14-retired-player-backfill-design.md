# 設計：退休球員歷史數據回補

## 背景與問題

`site_builder/sync.py` 的 `_fetch_player_data()` 會先用 `categorize_roster_status()`
判斷球員的 `status_category`。當球員最新的 roster entry 狀態碼是
`RL`（Released）、`RET`（Retired）或 `VL`（Voluntarily Retired）時，
`status_category` 會是 `"inactive"`，函式會立刻 return，
完全跳過 yearByYear stats、seasonAdvanced stats、game logs 的抓取，
只更新 `players` 表的基本 profile。

這個早退判斷目前**不分「第一次同步」還是「日常 refresh」**：
只要球員被歸類為 inactive，無論他過去是否曾經被抓過資料，都會被跳過。

實測案例：王建民（`mlb_id=425426`）已在 `roster.json` 中，
`roster_status_code="RL"`，但 `season_stats` 表中他的紀錄數為 `0`
—— 自加入 roster 後從未被抓過任何歷史數據。

## 目標

1. `sync` 指令（`sync_database`，`fetch_all_years=True`）：
   對所有球員（不論 active/inactive）都抓取全部歷史年份的
   yearByYear stats、seasonAdvanced stats 與 game logs。
2. `refresh`/`update` 指令（`update_database`，`fetch_all_years=False`）：
   - 維持現有優化：`season_stats` 已有資料的 inactive 球員，
     繼續跳過 stats/game logs 重抓，只更新 profile。
   - 新增：`season_stats` 完全沒有資料的球員（不論 active/inactive，
     代表第一次同步），自動視為「全歷史抓取」，做一次完整回補。
3. inactive 球員（含首次回補）不寫入 `next_game_json`，
   避免顯示已退休球員「最後待過球隊」的下一場比賽。

## 設計

### 核心邏輯變更

將 inactive 早退判斷的條件，從只看 `status_category`：

```python
if status_category == "inactive":
    ...  # 早退，跳過 stats/game logs
```

改成同時看「該次抓取是否為全歷史抓取」：

```python
if status_category == "inactive" and not fetch_all_years:
    ...  # 早退，跳過 stats/game logs
```

**`sync` 指令下此條件永遠不成立**：`sync_database()` 在 pipeline 層級
傳入 `fetch_all_years=True`，因此 `not fetch_all_years` 恆為 `False`，
`and` 運算結果恆為 `False`。所有球員都會繼續走完整抓取路徑，
不論 active/inactive。

**`refresh`/`update` 指令下**：pipeline 層級 `fetch_all_years=False`，
但會針對「`season_stats` 完全沒有資料」的球員，將該球員的
有效 `fetch_all_years` 覆寫為 `True`（視為首次同步，全歷史回補）；
其餘已有資料的球員維持 `False`。只有「已有資料 + inactive」的球員，
條件才會成立並早退跳過。

### 實作位置（`site_builder/sync.py`）

1. **`_run_pipeline()`**：
   - 在組好 `players_config` 後，新增一次查詢
     `SELECT DISTINCT player_mlb_id FROM season_stats`，
     得到「已同步過」的 mlb_id 集合 `synced_ids`。
   - 提交到 `ThreadPoolExecutor` 時，為每位球員計算
     `effective_fetch_all_years = fetch_all_years or (mlb_id not in synced_ids)`，
     傳入 `_fetch_player_data()`。

2. **`_fetch_player_data()`**：
   - 早退條件改為 `if status_category == "inactive" and not fetch_all_years:`
     （此處 `fetch_all_years` 即上面算出的 per-player 有效值）。
   - 完整抓取路徑中，`next_game` 的抓取追加條件：
     只有 `status_category != "inactive"` 且有 `team_id` 時才呼叫
     `get_next_game()`；inactive 球員（含首次回補）一律不寫入
     `next_game_json`，維持空值。

### 不需要改動的部分

- **`sync_statcast`**：本身不檢查 active/inactive，只要 `game_logs`
  有資料就能正常抓 playByPlay、計算 Statcast/FIP/expected stats。
  回補完 `season_stats`/`game_logs` 後，可直接跑
  `python build.py statcast --player <id>`。
- **`_write_player_to_db`**：寫入邏輯本來就是「bundle 裡有什麼就寫什麼」，
  完整回補時 bundle 結構與一般 active 球員相同，無需修改。

## 使用者工作流程影響

新增退休球員到 `roster.json` 後：

- 手動跑 `python build.py sync --player <id>`（或全量 `sync`）：
  會抓到完整歷史 stats + game logs。
- 或什麼都不做，等下一次排程的 `refresh` 跑：因為該球員
  `season_stats` 是空的，會被偵測為「首次同步」，自動做一次
  全歷史回補（同一次 refresh 內仍會接著跑 statcast + build）。
- 之後的 `refresh`/`sync`：因為 `season_stats` 已有資料且該球員
  inactive，回到「只更新 profile，不重抓 stats/game logs」的
  省資源路徑。

已經有資料的 inactive 球員（例如其他已退休選手原本就有歷史資料）：
行為不變，繼續跳過重抓。

## 驗證計畫

以王建民（`425426`，目前 `season_stats=0`）作為測試案例：

1. 跑 `python build.py sync --player 425426`（或
   `refresh --player 425426`），確認：
   - `season_stats`/`game_logs` 開始有資料。
   - `players.next_game_json` 仍為空（`{}`）。
2. 再跑一次相同指令，確認第二次因為「已有資料 + inactive」而
   早退跳過（log 顯示類似 `(inactive: status only)`）。
3. 跑 `python build.py statcast --player 425426`，確認可正常
   處理回補後的 game logs 並計算 Statcast/FIP。
4. 跑 `python build.py build`，確認王建民頁面正常顯示歷史數據，
   且未顯示誤導性的「下一場比賽」。

## Edge Cases

- 全新加入 roster、從未同步過的**現役**球員：第一次 `refresh`
  也會因 `synced_ids` 不包含該 mlb_id 而做全歷史回補
  （比現有「先手動 `sync --player`」的建議流程更省心，但非本次
  變更的主要目標，屬於自然的附帶效果）。
- 多位退休球員同時加入 roster：`synced_ids` 檢查對每位球員獨立
  生效，`sync`/`refresh` 都能一次性正確回補所有人。

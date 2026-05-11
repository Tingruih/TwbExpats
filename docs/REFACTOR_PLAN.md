# 前端重構計劃

> 目標：以更細粒度的模板拆分 + CSS/JS 分檔，讓每個檔案的職責單一，未來維護不需搜尋 2000 行巨型檔案。
> **本次不做行動**：不新增功能、不改視覺、不優化效能——僅做結構性重組。

---

## 一、模板（Jinja2）架構

### 目標目錄結構

```
src/templates/
  base.j2                 ← 全站 HTML 骨架（head、header、main、scripts）
  index.j2                ← 首頁球員卡片 grid
  player_detail.j2        ← 球員詳細頁外殼（hero + tab nav + {% include tabs %}）
  404.j2
  tabs/
    tab_bio.j2            ← 球員資料 tab（個人資料、Next Game、異動紀錄、生涯累計）
    tab_stats.j2          ← 歷年數據 tab（season stats tables、year-group collapsible）
    tab_gamelogs.j2       ← 逐場紀錄 tab（year/level filter + gamelog tables + pitch log）
    tab_advanced.j2       ← 進階數據 tab（arsenal filter、pitch usage、pitch movement）
    tab_fielding.j2       ← 守備數據 tab（fielding stats table）
    tab_plot.j2           ← 數據圖表 tab（scatter plot、Chart.js canvas）
```

### 各檔分工說明

| 檔案 | 負責內容 | 現在在哪裡 |
|------|---------|-----------|
| `base.j2` | `<html>`、`<head>`、header、`{% block content %}`、全站 `<script>`（table-align、avatar-fallback、Cloudflare beacon） | `base.j2`（現況良好，不動） |
| `index.j2` | sort bar、`#player-grid`、player card loop（含 avatar、stats-row）、inline `sortCards()` script | `index.j2`（現況良好，不動） |
| `player_detail.j2` | hero section、**僅一套** tab nav（去除 mobile 版）、六個 `{% include 'tabs/tab_xxx.j2' %}`、tab 切換 script（`tabs.js`）| 現在全部塞在 `player_detail.j2`（2384 行） |
| `tabs/tab_bio.j2` | `.bio-grid`、個人資料 `<dl>`、Next Game card、異動紀錄 timeline、生涯累計 mini-stats | `player_detail.j2` 第 78–390 行 |
| `tabs/tab_stats.j2` | year-selector、season stats `.data-table`（含 year-group collapsible）、`toggleYearGroup()` script | `player_detail.j2` 第 391–1220 行 |
| `tabs/tab_gamelogs.j2` | gamelog year/level filter bar、`.gamelog-table-container`、pitch log 展開列、gamelog filter script、pitch-log fetch/render script | `player_detail.j2` 第 1233–1500 行 |
| `tabs/tab_advanced.j2` | arsenal filter bar、pitch usage table、pitch movement charts、pitch plinko | `player_detail.j2` 第 1501–2200 行 |
| `tabs/tab_fielding.j2` | fielding stats table | `player_detail.j2` 分散段落 |
| `tabs/tab_plot.j2` | Chart.js scatter plot canvas、初始化 script（含 `{% if is_pitcher %}` 邏輯）| `player_detail.j2` 最後 ~200 行 |

### 拆分後 `player_detail.j2` 骨架（示意）

```jinja2
{% extends 'base.j2' %}
{% block content %}

{# ── HERO ── #}
<div class="profile-hero glass-panel"> ... </div>

{# ── TAB NAV（單一，桌面版）── #}
<div class="tab-nav glass-panel">
  <label data-tab="bio"  class="tab-label tab-label--active">球員資料</label>
  ...
</div>

{# ── TAB PANELS ── #}
<div class="tab-panel tab-panel--active" id="panel-bio">
  {% include 'tabs/tab_bio.j2' %}
</div>
<div class="tab-panel" id="panel-stats">
  {% include 'tabs/tab_stats.j2' %}
</div>
...

{% endblock %}

{% block extra_scripts %}
<script src="{{ static_url('js/tabs.js') }}"></script>
{% endblock %}
```

---

## 二、CSS 拆分

### 目標目錄結構

```
src/static/css/
  base.css          ← CSS variables（:root）、reset（*, box-sizing）、body、scrollbar、range input、h1-h4、a
  layout.css        ← .container、header、.brand-logo、.brand-icon、.desktop-only（移除 .mobile-only）
  components.css    ← .glass-panel、.badge、.status-pill、.avatar、.level-tag
  index.css         ← .dashboard-grid、.player-card、.stats-row、.index-controls、sort-bar、.header-time-badge
  player-hero.css   ← .profile-hero、.hero-photo-wrap、.hero-avatar、.hero-info、.hero-stats-strip、.hs-item
  tabs.css          ← .tab-nav、.tab-label（移除 .tab-nav-mobile、.tab-nav-mobile-scroll、.tab-mobile-label）、.tab-panel
  bio.css           ← .bio-grid、.bio-card、.next-game-card、.ng-*、.tx-timeline、.tx-*、.mini-stats-grid、.career-combined-card
  stats.css         ← .data-table-section、.data-table、.year-selector、.year-group collapsible（.arrow、.toggle-arrow、.year-detail-row）
  gamelogs.css      ← .gamelog-table-container、gamelog filter bar、.pitch-log-cell、.pitch-log-scroll、.pitch-log-table、.pitch-tag、pitch type colors
  advanced.css      ← .arsenal-filter-bar、.arsenal-subsection、pitch usage table、.pitch-plinko-*、advanced stats definitions（.stat-def）
  fielding.css      ← fielding 專用樣式（目前極少，主要沿用 .data-table）
  charts.css        ← .chart-wrap、.pitch-chart-grid、.pitch-chart-section、.pitch-chart-title、.pitch-chart-legend、scatter plot canvas
  style.css         ← 入口檔，僅含 @import，所有頁面引用此單一 CSS
```

### `style.css` 入口（重構後）

```css
@import "base.css";
@import "layout.css";
@import "components.css";
@import "index.css";
@import "player-hero.css";
@import "tabs.css";
@import "bio.css";
@import "stats.css";
@import "gamelogs.css";
@import "advanced.css";
@import "fielding.css";
@import "charts.css";
```

> 建置時需確認 Jinja builder 不 minify/bundle CSS（目前直接 copy static）；`@import` 在現代瀏覽器可直接運作，若未來需合併可加 PostCSS 步驟。

### 現況 CSS 各段對應行號（`style.css`）

| 新檔案 | 現在行號範圍 |
|--------|-------------|
| `base.css` | 1–160（:root ~ .mobile-only） |
| `layout.css` | 148–235（.container、header、brand-logo） |
| `components.css` | 236–470（avatar、glass-panel、badge、status、sort-bar） |
| `index.css` | 269–535（dashboard-grid、player-card、stats-row、index-controls） |
| `player-hero.css` | 555–674 |
| `tabs.css` | 675–779（**移除** mobile tab 段落 715–768） |
| `bio.css` | 781–1000（bio-grid 到 arsenal-subsection 前） |
| `stats.css` | 1001–1100、1837–1900（data-table、year-group） |
| `gamelogs.css` | 2011–2144（pitch-log-*、pitch-tag、pitch type colors） |
| `advanced.css` | 901–999、1269–1340（arsenal filter、stat-def） |
| `charts.css` | 1317–1800（chart-wrap、plinko、pitch-chart） |

---

## 三、JavaScript 拆分

### 目標目錄結構

```
src/static/js/
  table-align.js      ← alignNumericTableColumns（目前在 base.j2 inline <script>）
  avatar-fallback.js  ← avatar error handler + initials fallback（目前在 base.j2 inline <script>）
  tabs.js             ← switchTab、label click binding、?tab= query param restore（目前在 player_detail.j2 末尾）
  stats-table.js      ← toggleYearGroup（目前在 player_detail.j2 第 1219 行）
  gamelogs.js         ← gamelog year/level filter、showYear、prefetchRowFromGameRow（目前在 player_detail.j2 第 1233 行）
  pitch-log.js        ← pitchLogCache、_fmt、_buildPitchTable、fetch & render（目前在 player_detail.j2 第 1342 行）
  charts.js           ← pitch movement Chart.js init、scatter plot init（目前在 player_detail.j2 末尾）
  index-sort.js       ← sortCards（目前在 index.j2 inline）
```

### 載入策略

| 檔案 | 載入位置 | 載入方式 |
|------|---------|---------|
| `table-align.js` | `base.j2` `</body>` 前 | `<script>` inline 改 `<script src>` |
| `avatar-fallback.js` | `base.j2` `</body>` 前 | `<script src>` |
| `index-sort.js` | `index.j2` `{% block extra_scripts %}` | `<script src>` |
| `tabs.js` | `player_detail.j2` `{% block extra_scripts %}` | `<script src>` |
| `stats-table.js` | `tabs/tab_stats.j2` 末尾 或 `player_detail.j2` extra_scripts | `<script src>` |
| `gamelogs.js` | `tabs/tab_gamelogs.j2` 末尾 | `<script src>` |
| `pitch-log.js` | `tabs/tab_gamelogs.j2` 末尾 | `<script src>` |
| `charts.js` | `tabs/tab_plot.j2` 末尾（含 `{% if %}` guard） | `<script src>` |

> `charts.js` 需以 `data-*` attribute 或 `<script type="application/json">` 取代現有 Jinja inline JSON，避免 JS 檔混入模板語法。

---

## 四、⚠️ 移除手機優化（重要提醒）

以下是**現有前端程式碼中所有針對手機的優化**，重構時須一併清除：

### 4-1. HTML 模板

| 位置 | 行號 | 內容 | 動作 |
|------|------|------|------|
| `player_detail.j2` | 57 | `<div class="tab-nav glass-panel desktop-only">` | 移除 `desktop-only` class |
| `player_detail.j2` | 66–76 | 整個 `{# ── MOBILE TAB NAV ── #}` 區塊（`tab-nav-mobile`） | **整段刪除** |
| `player_detail.j2` | 2364 | JS 中 `// Toggle label active state (both desktop + mobile)` comment | 無需改動，但下方 `querySelectorAll('[data-tab]')` 範圍縮小（mobile labels 已刪） |

### 4-2. CSS (`style.css`)

| 行號 | 內容 | 動作 |
|------|------|------|
| 148–154 | `.desktop-only { display: block; }` `.mobile-only { display: none; }` | **刪除** `.mobile-only`，`.desktop-only` 也無用可刪 |
| 715–768 | `.tab-nav-mobile`、`.tab-nav-mobile-scroll`、`.tab-mobile-label`（含 hover、active） | **整段刪除** |
| 703–713 | tab label 內 `touch-action: manipulation`、`-webkit-tap-highlight-color: transparent` | 可保留（無害），或刪除以保持桌面語意 |
| 1903–1910 | `@media (max-width: 1200px)` 整段（僅 `.bio-grid` 2-col） | **刪除** |
| 1909–1975 | `@media (max-width: 768px)` 整段 | **刪除** |
| 1977–2010 | `@media (max-width: 520px)` 整段 | **刪除** |

### 4-3. JS

| 位置 | 內容 | 動作 |
|------|------|------|
| `player_detail.j2` tab script | `querySelectorAll('[data-tab]')` 同時綁定 desktop + mobile label | 刪除 mobile label 後自動失效，無需改 JS；確認 mobile labels DOM 已消失即可 |

> **`<meta name="viewport" content="width=device-width, initial-scale=1.0">`** 保留在 `base.j2`，不影響桌面體驗但避免一些瀏覽器縮放問題。

---

## 五、執行順序建議

1. **移除手機優化**（風險最低，獨立 PR）
   - 刪除 `player_detail.j2` 中 mobile tab nav 區塊
   - 刪除 `style.css` 中三段 `@media` + mobile class 定義
   - 驗證：`python build.py build` → 瀏覽器確認 tab nav 正常

2. **CSS 拆分**
   - 建立 `src/static/css/` 子檔案
   - 將 `style.css` 段落移入對應檔案
   - `style.css` 改為純 `@import` 入口
   - 驗證：樣式無差異

3. **JS 拆分**
   - 建立 `src/static/js/` 目錄
   - 將各 inline `<script>` 搬出為獨立 `.js` 檔
   - 模板改為 `<script src="...">` 載入
   - 驗證：tab 切換、gamelog 展開、pitch log fetch、chart 正常

4. **Template 拆分**（最後，風險最高）
   - 建立 `src/templates/tabs/` 目錄
   - 將 `player_detail.j2` 各 panel 段落移至 `tab_xxx.j2`
   - `player_detail.j2` 改為 `{% include %}` 組合
   - 確認 builder `jinja_env.py` 的 `template_folder` 支援子目錄（Jinja2 預設支援）
   - 驗證：完整 build 後所有球員頁面正常

---

## 六、不在本次範圍

- 任何視覺改動
- CSS custom properties 重命名
- 新增 PostCSS / bundler
- 效能優化（lazy load、code split）
- 新增功能

---

---

# Phase 2：手機 UI 重構

> **前提**：Phase 1 必須完成（手機優化已清除、模板/CSS/JS 已拆分）。
> **核心原則**：手機 UI 與桌面 UI 在 HTML 層就完全分離——兩套獨立的 DOM，以單一 CSS 斷點在 wrapper 層控制顯示/隱藏，絕不在同一個元素上混用 desktop/mobile 樣式。

---

## 一、設計決策

### 手機 Player Detail 版面方向

| 項目 | 桌面（Phase 1） | 手機（Phase 2） |
|------|----------------|----------------|
| 導覽 | 水平 tab bar，6 個 label | **底部固定 tab bar**，6 個 icon+文字 |
| Hero | 橫向排列（照片、資料、stats strip 在同一列） | **直向堆疊**：照片置中 → 姓名 → key stats 水平捲動 |
| Bio | 4 欄 grid card | **單欄 accordion**，預設全展開 |
| Stats | 水平捲動 table | 同樣水平捲動，但加上**欄位凍結**（第一欄 sticky） + **年份 accordion** 預設收合 |
| Gamelogs | year/level dropdown + table | 相同 filter，table 改為**卡片式列表**（每場比賽一張卡片） |
| Advanced | pitch usage table + chart + plinko | chart 改單欄、plinko 改單欄；table 同桌面 |
| Fielding | table | 同 stats 處理方式 |
| Plot | Chart.js scatter | canvas 寬度 100%，移除 tooltip hover（改 tap） |
| Header | logo + 更新時間 同行 | logo + 更新時間 **直向堆疊** |

### 斷點策略

- **唯一斷點**：`768px`（低於此值切換至手機視圖）
- 切換機制：`<body>` 或最外層 `<div class="page-desktop"> / <div class="page-mobile">` 分別以 CSS `display: none` 控制

```css
/* mobile.css — 唯一的全域斷點規則 */
.page-desktop { display: block; }
.page-mobile  { display: none; }

@media (max-width: 768px) {
  .page-desktop { display: none; }
  .page-mobile  { display: block; }
}
```

> 所有手機專屬 CSS 均寫在 `css/mobile/` 下，**不使用 `@media` 在各自的 desktop CSS 檔案中**，確保手機樣式完全隔離。

---

## 二、檔案結構（Phase 2 新增）

```
src/
  templates/
    mobile/
      m_player_detail.j2        ← 手機版 player 頁外殼（hero + bottom tab bar + sections）
      sections/
        m_hero.j2               ← 手機版 hero（直向堆疊、照片居中）
        m_bottom_nav.j2         ← 底部固定 tab bar（6 icon + label）
        m_bio.j2                ← 手機版 bio（accordion 式卡片）
        m_stats.j2              ← 手機版歷年數據（sticky 首欄 + year accordion）
        m_gamelogs.j2           ← 手機版逐場紀錄（卡片式列表 + filter）
        m_advanced.j2           ← 手機版進階數據（單欄 chart/table）
        m_fielding.j2           ← 手機版守備數據
        m_plot.j2               ← 手機版 scatter plot（100% 寬、tap tooltip）

  static/
    css/
      mobile/
        m-base.css              ← 手機版 :root override、body font-size、間距 token
        m-layout.css            ← .page-mobile 容器、header 直向、bottom-nav 佔位 padding
        m-hero.css              ← 手機版 hero 樣式
        m-bottom-nav.css        ← 底部 tab bar 樣式（fixed、safe-area-inset）
        m-bio.css               ← accordion 卡片、dl 樣式
        m-stats.css             ← sticky 首欄、year accordion、table scroll wrapper
        m-gamelogs.css          ← 逐場卡片、filter bar
        m-advanced.css          ← 單欄 chart、plinko
        m-charts.css            ← canvas 樣式、tap tooltip
        mobile.css              ← 入口：@import 所有 m-*.css + 斷點切換規則

    js/
      mobile/
        m-tabs.js               ← 底部 tab bar 切換邏輯（show/hide .m-section-panel）
        m-accordion.js          ← bio accordion 展開/收合
        m-gamelogs.js           ← 手機版 gamelog filter + 卡片渲染
        m-pitch-log.js          ← pitch log fetch（複用 desktop pitch-log.js 的快取，避免重複 fetch）
        m-charts.js             ← Chart.js tap tooltip、resize 處理
```

### Phase 2 後完整 CSS 目錄

```
src/static/css/
  base.css / layout.css / components.css / ...（Phase 1，桌面）
  mobile/
    m-base.css
    m-layout.css
    m-hero.css
    m-bottom-nav.css
    m-bio.css
    m-stats.css
    m-gamelogs.css
    m-advanced.css
    m-charts.css
    mobile.css              ← 入口
  style.css                 ← 桌面入口（Phase 1 的 @import 列表，加一行 @import "mobile/mobile.css"）
```

---

## 三、HTML 隔離策略

### `player_detail.j2`（Phase 2 修改後）

```jinja2
{% extends 'base.j2' %}
{% block content %}

{# ════ DESKTOP VIEW ════ #}
<div class="page-desktop">
  {# hero、tab nav、tab panels — 全部 Phase 1 的 include 不動 #}
  <div class="profile-hero glass-panel"> ... </div>
  <div class="tab-nav glass-panel"> ... </div>
  <div class="tab-panel" id="panel-bio">{% include 'tabs/tab_bio.j2' %}</div>
  ...
</div>

{# ════ MOBILE VIEW ════ #}
<div class="page-mobile">
  {% include 'mobile/m_player_detail.j2' %}
</div>

{% endblock %}
```

> `m_player_detail.j2` 自行組合 `mobile/sections/m_xxx.j2`，與桌面 `tabs/tab_xxx.j2` 完全獨立。

### 資料共用

兩套 DOM 由同一個 Jinja2 context（`player`、`season_stats`、`gamelogs` 等）渲染，不需 builder 改動。手機版直接存取相同變數，只有 HTML 結構不同。

---

## 四、各 section 詳細規格

### 4-1. 手機 Hero（`m_hero.j2`）

```
┌─────────────────┐
│   [照片 80px]   │   ← 圓形，置中
│ 姓名（大字）     │
│ 隊伍 · 位置 · 層級 badge │
├─────────────────┤
│ ← key stats 橫向捲動 → │
│  AVG  OPS  HR  RBI  SB  │  (打者)
│  ERA  WHIP  K  W-L  IP  │  (投手)
└─────────────────┘
```

- stats strip：`display: flex; overflow-x: auto; scroll-snap-type: x mandatory`
- 每個 stat item：`scroll-snap-align: start`

### 4-2. 底部 Tab Bar（`m_bottom_nav.j2`）

```
┌───────────────────────────────────┐
│ 資料 │ 數據 │ 逐場 │ 進階 │ 守備 │ 圖表 │
└───────────────────────────────────┘  ← fixed bottom
```

- `position: fixed; bottom: 0; left: 0; right: 0`
- `padding-bottom: env(safe-area-inset-bottom)` — 預留 iPhone home indicator 空間
- `.m-bottom-nav` 高度 56px + safe-area
- `<main>` 加 `padding-bottom: calc(56px + env(safe-area-inset-bottom))`
- 6 個 `<button data-m-tab="bio">` + SVG icon（inline，避免額外請求）
- active 狀態：teal 底色 + 白字

### 4-3. Bio Accordion（`m_bio.j2`）

- 個人資料、Next Game、異動紀錄、生涯累計 各為一個 accordion 項目
- 預設**全部展開**（`open` attribute on `<details>`）
- 使用原生 `<details>/<summary>` 元素，無需 JS
- `m-accordion.js` 僅處理**記憶上次展開狀態**（`sessionStorage`）

### 4-4. 手機版 Stats（`m_stats.j2`）

- 繼承 Phase 1 的 `.data-table`，加以下處理：
  - 外層 `overflow-x: auto` wrapper（Phase 1 已有）
  - 第一欄（球隊/聯盟）加 `position: sticky; left: 0`（`m-stats.css` 控制）
  - year-group accordion 預設**收合**（與桌面相反）
- filter/selector 同桌面，不另做

### 4-5. 手機版 Gamelogs（`m_gamelogs.j2`）

每場比賽從 table row 改為**卡片**：

```
┌─────────────────────────────┐
│ 2026-05-09  vs OAK  W 5-2  │
│ 2 AB  1 H  0 HR  1 RBI     │  (打者)
│ [展開 pitch log ▾]          │
└─────────────────────────────┘
```

- `m-gamelogs.js` 負責 filter + 卡片 DOM 生成（複用桌面已存在的資料 `<script type="application/json">` inline data）
- pitch log 展開後在卡片內嵌入水平捲動 table（複用 `m-pitch-log.js`，共享 `pitchLogCache`）

### 4-6. 手機版 Advanced（`m_advanced.j2`）

- arsenal filter bar 同桌面
- pitch usage table：同桌面 table，但首欄 sticky
- pitch movement chart（Chart.js）：單欄，canvas 100% 寬
- pitch plinko：單欄

### 4-7. 手機版 Plot（`m_plot.j2`）

- Canvas 100% 寬
- hover tooltip 改為 tap（`m-charts.js` 監聽 `touchstart`，呼叫 `getElementsAtEvent`）
- Chart 初始化邏輯複用 `charts.js`，不重寫，只 override tooltip config

---

## 五、JS 共用策略

手機版 JS **不重複實作**已有邏輯，採用以下方式：

| 需求 | 策略 |
|------|------|
| Pitch log fetch/cache | `pitch-log.js` 的 `pitchLogCache` 為全域物件，`m-pitch-log.js` 直接呼叫 `window.pitchLogCache` |
| Table numeric alignment | 沿用 `table-align.js` 的 `window.alignNumericTableColumns`，在手機卡片渲染後重新呼叫 |
| Avatar fallback | 全域，已在 `base.j2` 載入，手機 DOM 渲染後 `<img>` 自動繼承 error handler |
| Chart.js 初始化 | `m-charts.js` 複用 `charts.js` 的 Chart config，只修改 `interaction`/`plugins` 層 |

### `base.j2` 載入調整（Phase 2）

```html
<!-- 桌面 JS（已存在） -->
<script src="{{ static_url('js/table-align.js') }}"></script>
<script src="{{ static_url('js/avatar-fallback.js') }}"></script>

<!-- 手機 JS（Phase 2 新增，全頁面載入，小檔） -->
<script src="{{ static_url('js/mobile/m-tabs.js') }}"></script>
<script src="{{ static_url('js/mobile/m-accordion.js') }}"></script>
```

`gamelogs.js`、`pitch-log.js`、`charts.js` 等較大的檔案仍在各自 tab template 末尾載入，手機版的對應 JS 在 `m_gamelogs.j2`、`m_plot.j2` 末尾以 `{% block extra_scripts %}` append 載入。

---

## 六、Builder 修改需求

Phase 2 不需要改動 `builder.py` 的主流程——同一個 render call 即可輸出包含雙套 DOM 的 HTML，CSS 媒體查詢負責切換。唯一需要確認的事項：

1. `jinja_env.py` 的 `template_folder` 已支援子目錄（Phase 1 驗證過）
2. `src/static/css/mobile/` 目錄下的檔案會被 builder 的 `copy_static` 步驟整個複製到 `dist/`
3. `style.css` 的 `@import "mobile/mobile.css"` 路徑在複製後仍正確

---

## 七、執行順序（Phase 2）

1. **設計稿確認**（HTML 骨架優先）
   - 先在 `m_player_detail.j2` 寫出完整 HTML 結構（暫無樣式）
   - 用 `python build.py build` 產生一個球員頁，在瀏覽器 devtools 模擬手機確認 DOM 結構正確

2. **底部 Tab Bar + 基本切換**
   - `m_bottom_nav.j2` + `m-bottom-nav.css` + `m-tabs.js`
   - 確認 6 個 section panel 可正常切換

3. **Hero + Bio**
   - `m_hero.j2` + `m-hero.css`
   - `m_bio.j2`（`<details>` 原生，無需 JS）+ `m-bio.css`
   - `m-accordion.js`（sessionStorage 記憶）

4. **Stats + Fielding**
   - `m_stats.j2` + `m-stats.css`（sticky 首欄）
   - `m_fielding.j2`

5. **Gamelogs**
   - `m_gamelogs.j2` + `m-gamelogs.js` + `m-gamelogs.css`
   - `m-pitch-log.js`（串接 `pitchLogCache`）

6. **Advanced + Plot**
   - `m_advanced.j2` + `m-advanced.css`
   - `m_plot.j2` + `m-charts.js`

7. **整合驗證**
   - 在多個球員頁（打者、投手、有/無 statcast 資料）完整測試
   - 確認桌面視圖完全不受影響

---

## 八、不在 Phase 2 範圍

- 手機版首頁（`index.j2`）重構（現有 player card 在手機已足夠）
- 手機版 404 頁
- 手機版 swipe 手勢切換 tab（可作 Phase 3）
- PWA / Service Worker
- 任何 A/B 測試機制

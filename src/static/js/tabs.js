/**
 * tabs.js — 球員詳細頁 Tab 切換邏輯
 * 載入於：player_detail.j2（球員詳細頁）
 *
 * 作用：管理六個功能分頁（bio/stats/gamelogs/advanced/fielding/plot）的切換：
 *  - 切換時顯示對應的 #panel-{name}，並在 .tab-label 上加/移除 .tab-label--active
 *  - 切換後發送自訂事件 player-tab-change（供 gamelogs.js / pitcher-charts.js 等監聽）
 *  - 支援 URL query string ?tab=xxx 讓頁面重整後恢復到上次的分頁
 */
(function(){
    var TABS = ['bio','stats','gamelogs','advanced','fielding','plot'];
    var panels = {};
    TABS.forEach(function(t){ panels[t] = document.getElementById('panel-' + t); });

    // 切換到指定 tab：更新面板顯示狀態 + 按鈕 active 狀態 + 觸發事件
    function switchTab(name) {
        if (TABS.indexOf(name) === -1) name = 'bio';
        // Toggle panels
        TABS.forEach(function(t){
            var p = panels[t];
            if (!p) return;
            if (t === name) { p.classList.add('tab-panel--active'); }
            else { p.classList.remove('tab-panel--active'); }
        });
        // Toggle label active state (tab labels)
        document.querySelectorAll('[data-tab]').forEach(function(lbl){
            if (lbl.dataset.tab === name) lbl.classList.add('tab-label--active');
            else lbl.classList.remove('tab-label--active');
        });
        // 通知其他模組（如 gamelogs.js 的 pitch log 預載）目前在哪個 tab
        document.dispatchEvent(new CustomEvent('player-tab-change', {
            detail: { tab: name }
        }));
    }

    // 綁定每個 Tab 按鈕的點擊事件
    document.querySelectorAll('[data-tab]').forEach(function(lbl){
        lbl.addEventListener('click', function(){ switchTab(this.dataset.tab); });
    });

    // 頁面載入時：從 URL ?tab= 參數恢復上次選擇的分頁
    var p = new URLSearchParams(location.search).get('tab');
    if (p && TABS.indexOf(p) !== -1) switchTab(p);
})();

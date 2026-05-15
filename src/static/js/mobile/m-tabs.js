(function() {
    var TABS = ['bio', 'stats', 'gamelogs', 'advanced', 'fielding', 'plot'];

    function switchMobileTab(name, updateUrl) {
        if (TABS.indexOf(name) === -1) name = 'bio';

        document.querySelectorAll('[data-m-panel]').forEach(function(panel) {
            panel.classList.toggle('m-section-panel--active', panel.dataset.mPanel === name);
        });

        document.querySelectorAll('[data-m-tab]').forEach(function(button) {
            var active = button.dataset.mTab === name;
            button.classList.toggle('m-bottom-nav-btn--active', active);
            if (active) button.setAttribute('aria-current', 'page');
            else button.removeAttribute('aria-current');
        });

        if (updateUrl && window.history && window.URLSearchParams) {
            var url = new URL(window.location.href);
            url.searchParams.set('tab', name);
            window.history.replaceState(null, '', url.toString());
        }

        document.dispatchEvent(new CustomEvent('player-mobile-tab-change', {
            detail: { tab: name }
        }));
    }

    function toggleMobileYearGroup(tableId, yr) {
        var arrow = document.getElementById('m-arrow-' + tableId + '-' + yr);
        // 卡片形式：切換子列表容器
        var sublist = document.getElementById('m-subdetail-' + tableId + '-' + yr);
        if (sublist) {
            var open = sublist.style.display !== 'none';
            sublist.style.display = open ? 'none' : '';
            if (arrow) arrow.style.transform = open ? '' : 'rotate(90deg)';
            return;
        }
        // 表格形式（進階數據等）：切換子列
        var table = document.getElementById('m-stats-table-' + tableId);
        if (!table) return;
        var rows = table.querySelectorAll('tr[data-tbl="m-' + tableId + '"][data-grp="' + yr + '"]');
        var open = rows.length > 0 && rows[0].style.display !== 'none';
        rows.forEach(function(row) {
            row.style.display = open ? 'none' : '';
        });
        if (arrow) arrow.style.transform = open ? '' : 'rotate(90deg)';
    }

    function init() {
        document.querySelectorAll('[data-m-tab]').forEach(function(button) {
            button.addEventListener('click', function() {
                switchMobileTab(button.dataset.mTab, true);
            });
        });

        var param = new URLSearchParams(window.location.search).get('tab');
        if (param && TABS.indexOf(param) !== -1) switchMobileTab(param, false);
    }

    window.switchMobileTab = switchMobileTab;
    window.toggleMobileYearGroup = toggleMobileYearGroup;

    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init);
    else init();
})();
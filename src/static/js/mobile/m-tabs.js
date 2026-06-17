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
        // 多球隊年度卡片：切換子卡片列表容器
        var sublist = document.getElementById('m-subdetail-' + tableId + '-' + yr);
        if (!sublist) return;
        var open = sublist.style.display !== 'none';
        sublist.style.display = open ? 'none' : '';
        if (arrow) arrow.style.transform = open ? '' : 'rotate(90deg)';
    }

    function initBottomNavAutoHide() {
        var nav = document.querySelector('.m-bottom-nav');
        if (!nav) return;

        var lastY = window.scrollY;
        var ticking = false;

        function onScroll() {
            var currentY = window.scrollY;
            var delta = currentY - lastY;

            if (currentY <= 0 || delta < 0) {
                nav.classList.remove('m-bottom-nav--hidden');
            } else if (delta > 0) {
                nav.classList.add('m-bottom-nav--hidden');
            }

            lastY = currentY;
            ticking = false;
        }

        window.addEventListener('scroll', function() {
            if (!ticking) {
                window.requestAnimationFrame(onScroll);
                ticking = true;
            }
        }, { passive: true });
    }

    function init() {
        initBottomNavAutoHide();

        document.querySelectorAll('[data-m-tab]').forEach(function(button) {
            button.addEventListener('click', function() {
                switchMobileTab(button.dataset.mTab, true);
            });
        });

        // iOS :focus 在 picker 關閉後仍殘留，改用自訂 class 控制高亮
        document.querySelectorAll('.page-mobile .filter-select').forEach(function(sel) {
            sel.addEventListener('focus',  function() { this.classList.add('is-picking'); });
            sel.addEventListener('change', function() { this.classList.remove('is-picking'); });
            sel.addEventListener('blur',   function() { this.classList.remove('is-picking'); });
        });
        // 點旁邊取消時 iOS 不一定觸發 blur，document touchstart 作為 fallback
        document.addEventListener('touchstart', function(e) {
            if (!e.target.classList.contains('filter-select')) {
                document.querySelectorAll('.filter-select.is-picking').forEach(function(s) {
                    s.classList.remove('is-picking');
                });
            }
        }, { passive: true });

        var param = new URLSearchParams(window.location.search).get('tab');
        if (param && TABS.indexOf(param) !== -1) switchMobileTab(param, false);
    }

    window.switchMobileTab = switchMobileTab;
    window.toggleMobileYearGroup = toggleMobileYearGroup;

    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init);
    else init();
})();
(function() {
    var mobileChart = null;

    function readJson(id, fallback) {
        var el = document.getElementById(id);
        if (!el) return fallback;
        try { return JSON.parse(el.textContent || 'null'); }
        catch (err) { return fallback; }
    }

    function initMobilePerformanceChart() {
        var canvas = document.getElementById('mPerformanceChart');
        if (!canvas || typeof Chart === 'undefined' || mobileChart) return;
        var labels = readJson('chart-labels', []);
        var data = readJson('chart-data', []);
        var ctx = canvas.getContext('2d');
        var grad = ctx.createLinearGradient(0, 0, 0, 260);
        grad.addColorStop(0, 'rgba(20,184,166,0.32)');
        grad.addColorStop(1, 'rgba(20,184,166,0.0)');

        mobileChart = new Chart(ctx, {
            type: 'line',
            data: {
                labels: labels,
                datasets: [{
                    label: canvas.dataset.chartLabel || 'AVG',
                    data: data,
                    borderColor: '#14b8a6',
                    backgroundColor: grad,
                    borderWidth: 2.25,
                    pointBackgroundColor: '#14b8a6',
                    pointBorderColor: '#09090b',
                    pointBorderWidth: 2,
                    pointRadius: 3.5,
                    pointHoverRadius: 5,
                    fill: true,
                    tension: 0.35
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                interaction: { mode: 'nearest', intersect: false },
                plugins: { legend: { labels: { color: '#f8fafc' } } },
                scales: {
                    x: { grid: { color: 'rgba(255,255,255,0.05)' }, ticks: { color: '#94a3b8' } },
                    y: {
                        grid: { color: 'rgba(255,255,255,0.05)' },
                        ticks: { color: '#94a3b8' },
                        reverse: canvas.dataset.reverseY === 'true'
                    }
                }
            }
        });

        canvas.addEventListener('touchstart', function(event) {
            if (!mobileChart || !event.touches || !event.touches.length) return;
            var touch = event.touches[0];
            var points = mobileChart.getElementsAtEventForMode(event, 'nearest', { intersect: false }, true);
            if (!points.length || !mobileChart.tooltip) return;
            mobileChart.setActiveElements(points);
            mobileChart.tooltip.setActiveElements(points, { x: touch.clientX, y: touch.clientY });
            mobileChart.update();
        }, { passive: true });
    }

    function initMobilePlinkoFilters() {
        var yearSel = document.getElementById('m-plinko-year-select');
        var levelSel = document.getElementById('m-plinko-level-select');
        if (!yearSel || !levelSel) return;

        function activeYearContainer() {
            return document.getElementById('m-plinko-' + yearSel.value);
        }

        function updateLevelOptions() {
            var yearContainer = activeYearContainer();
            if (!yearContainer) return;
            levelSel.innerHTML = '';
            yearContainer.querySelectorAll('.m-pitch-plinko-level-container').forEach(function(container, index) {
                var option = document.createElement('option');
                option.value = container.dataset.level;
                option.textContent = container.dataset.levelLabel;
                if (index === 0) option.selected = true;
                levelSel.appendChild(option);
            });
        }

        function showLevel() {
            var yearContainer = activeYearContainer();
            if (!yearContainer) return;
            yearContainer.querySelectorAll('.m-pitch-plinko-level-container').forEach(function(container) {
                container.style.display = container.dataset.level === levelSel.value ? 'block' : 'none';
            });
        }

        function showYear() {
            document.querySelectorAll('.m-pitch-plinko-year-container').forEach(function(container) {
                container.style.display = 'none';
            });
            var active = activeYearContainer();
            if (active) active.style.display = 'block';
            updateLevelOptions();
            showLevel();
        }

        yearSel.addEventListener('change', showYear);
        levelSel.addEventListener('change', showLevel);
        showYear();
    }

    function init() {
        initMobilePerformanceChart();
        initMobilePlinkoFilters();
    }

    document.addEventListener('player-mobile-tab-change', function(event) {
        if (event.detail && event.detail.tab === 'plot') {
            window.setTimeout(function() {
                initMobilePerformanceChart();
                if (mobileChart) mobileChart.resize();
            }, 40);
        }
    });

    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init);
    else init();
})();
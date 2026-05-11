(function() {
    var yearSel;
    var levelSel;

    function activeYearContainer() {
        return yearSel ? document.getElementById('m-gamelogs-' + yearSel.value) : null;
    }

    function updateLevelOptions() {
        var container = activeYearContainer();
        if (!container || !levelSel) return;
        var levels = [];
        container.querySelectorAll('.m-gamelog-card').forEach(function(card) {
            var level = card.dataset.level;
            if (level && levels.indexOf(level) === -1) levels.push(level);
        });

        levelSel.innerHTML = '';
        if (levels.length > 1) {
            var all = document.createElement('option');
            all.value = '_all';
            all.textContent = 'All Levels';
            levelSel.appendChild(all);
        }
        levels.forEach(function(level) {
            var option = document.createElement('option');
            option.value = level;
            option.textContent = level;
            levelSel.appendChild(option);
        });
    }

    function filterCards() {
        var container = activeYearContainer();
        if (!container || !levelSel) return;
        var level = levelSel.value;
        container.querySelectorAll('.m-gamelog-card').forEach(function(card) {
            var show = level === '_all' || level === '' || card.dataset.level === level;
            card.style.display = show ? '' : 'none';
            if (!show) {
                var panel = card.querySelector('.m-pitch-log-panel');
                if (panel) panel.style.display = 'none';
            }
        });
    }

    function showYear() {
        if (!yearSel) return;
        document.querySelectorAll('.m-gamelog-year').forEach(function(container) {
            container.style.display = 'none';
        });
        var container = activeYearContainer();
        if (container) container.style.display = 'flex';
        updateLevelOptions();
        filterCards();
    }

    function warmupVisiblePitchLogs() {
        if (typeof window.prefetchMobilePitchLogs !== 'function') return;
        window.prefetchMobilePitchLogs();
    }

    function init() {
        yearSel = document.getElementById('m-gamelog-year-select');
        levelSel = document.getElementById('m-gamelog-level-select');
        if (yearSel) yearSel.addEventListener('change', showYear);
        if (levelSel) levelSel.addEventListener('change', filterCards);
        showYear();

        document.addEventListener('player-mobile-tab-change', function(event) {
            if (event.detail && event.detail.tab === 'gamelogs') warmupVisiblePitchLogs();
        });
    }

    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init);
    else init();
})();
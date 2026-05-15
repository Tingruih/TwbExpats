/**
 * pitch-log.js — 逐球 Pitch Log 載入與渲染
 * 載入於：tab_gamelogs.j2（逐場紀錄 Tab）
 *
 * 作用：點擊比賽列展開箭頭時，動態 fetch 並渲染該場比賽的逐球資料表格。
 * 資料格式：JSON 陣列（每個物件為一球的速度/球種/結果等）
 *
 * 主要函式：
 *  - pitchLogCache            ：記憶體快取，避免同一場比賽重複 fetch
 *  - _buildPitchTable(pitches)：將逐球 JSON 資料轉成 HTML 表格字串
 *  - _loadPitchLogData(src)   ：fetch + 解析 JSON + 存入快取，回傳 Promise
 *  - prefetchPitchLogRow(row) ：預先 fetch 單一比賽列的 pitch log（但不渲染）
 *  - prefetchFilteredPitchLogs：批次預載目前篩選結果中所有可見比賽的 pitch log
 *  - togglePitchLog(id)       ：展開/收合逐球區域，首次展開時觸發懶載入渲染
 */
var pitchLogCache = Object.create(null);

// 格式化數值，null/空值回傳 '-'
function _fmt(v, d) {
    if (v == null || v === '') return '-';
    return d != null ? Number(v).toFixed(d) : v;
}
// 將逐球 JSON 數據轉成 HTML 表格字串（編號/球數/局倒/球種/車速/區帶等欄位）
function _buildPitchTable(pitches) {
    var h = '<table class="pitch-log-table"><thead><tr>' +
        '<th data-tooltip="逐球序號">#</th><th data-tooltip="投球前球數">Count</th><th data-tooltip="局數">INN</th><th data-tooltip="球種">Type</th><th data-tooltip="球速">Speed</th>' +
        '<th data-tooltip="進壘區域">Zone</th><th data-tooltip="單球結果">Result</th><th data-tooltip="擊球初速">EV</th><th data-tooltip="擊球仰角">LA</th>' +
        '<th data-tooltip="誘導垂直位移">iVB</th><th data-tooltip="水平位移">HB</th><th data-tooltip="轉速">Spin</th><th data-tooltip="出手延伸距離">Ext</th>' +
        '<th data-tooltip="打席結果">PA Event</th></tr></thead><tbody>';
    var prevBalls = 0, prevStrikes = 0, paEnded = true;
    for (var i = 0; i < pitches.length; i++) {
        var p = pitches[i];
        // Pre-pitch count: if PA just ended (or first pitch), reset to 0-0
        var preBalls = paEnded ? 0 : prevBalls;
        var preStrikes = paEnded ? 0 : prevStrikes;
        var countStr = (p.balls != null) ? (preBalls + '-' + preStrikes) : '-';
        // Track for next pitch: if this pitch ends the PA, next starts fresh
        paEnded = !!p.pa_event;
        if (p.balls != null) { prevBalls = p.balls; prevStrikes = p.strikes != null ? p.strikes : 0; }
        var cls = p.pa_event ? ' class="pitch-pa-final"' : '';
        var pt = (p.pitch_type || '').toLowerCase();
        var pn = p.pitch_name || p.pitch_type || '\u2014';
        h += '<tr' + cls + '>' +
            '<td class="num">' + (i+1) + '</td>' +
            '<td class="num">' + countStr + '</td>' +
            '<td class="num">' + _fmt(p.inning) + '</td>' +
            '<td><span class="pitch-tag pitch-' + pt + '">' + pn + '</span></td>' +
            '<td class="num">' + _fmt(p.speed,1) + '</td>' +
            '<td class="num">' + _fmt(p.zone) + '</td>' +
            '<td>' + (p.result || '\u2014') + '</td>' +
            '<td class="num">' + _fmt(p.ev,1) + '</td>' +
            '<td class="num">' + _fmt(p.la,1) + '</td>' +
            '<td class="num">' + _fmt(p.ivb,1) + '</td>' +
            '<td class="num">' + _fmt(p.hb,1) + '</td>' +
            '<td class="num">' + _fmt(p.spin) + '</td>' +
            '<td class="num">' + _fmt(p.extension,2) + '</td>' +
            '<td>' + (p.pa_event ? '<span class="pa-event-tag">' + p.pa_event + '</span>' : '') + '</td></tr>';
    }
    h += '</tbody></table>';
    return h;
}

// 取得或建立快取檔對應的項目物件
function _getPitchLogEntry(src) {
    if (!src) return null;
    if (!pitchLogCache[src]) pitchLogCache[src] = {};
    return pitchLogCache[src];
}

// fetch JSON 數據存入快取；已有快取或進行中的請求則從對應項目回傳
function _loadPitchLogData(src) {
    var entry = _getPitchLogEntry(src);
    if (!entry) return Promise.resolve(null);
    if (entry.html) return Promise.resolve(entry);
    if (entry.promise) return entry.promise;

    entry.promise = fetch(src)
        .then(function(resp) {
            if (!resp.ok) throw new Error('HTTP ' + resp.status);
            return resp.json();
        })
        .then(function(pitches) {
            entry.pitches = Array.isArray(pitches) ? pitches : [];
            entry.html = _buildPitchTable(entry.pitches);
            return entry;
        })
        .catch(function(err) {
            delete pitchLogCache[src];
            throw err;
        })
        .finally(function() {
            if (pitchLogCache[src]) delete pitchLogCache[src].promise;
        });

    return entry.promise;
}

// 將已載入的快取 HTML 插入容器，並觸發表格欄位對齊
function _renderPitchLog(container, entry) {
    container.innerHTML = entry && entry.html ? entry.html : _buildPitchTable([]);
    container.dataset.rendered = '1';
    if (typeof window.alignNumericTableColumns === 'function') {
        window.alignNumericTableColumns(container);
    }
}

// 預載單一比賽列的 pitch log（不渲染，僅將數據存入快取）
function prefetchPitchLogRow(row) {
    if (!row || !row.dataset || !row.dataset.src) return Promise.resolve(null);
    return _loadPitchLogData(row.dataset.src).catch(function() {
        return null;
    });
}

// 取得目前年份/職業耳漈筛選後所有可見比賽列的 pitch-log-row
function _getFilteredPitchLogRows() {
    var yearSel = document.getElementById('gamelog-year-select');
    var yr = yearSel ? yearSel.value : '';
    var tbl = yr ? document.getElementById('gamelogs-' + yr) : null;
    var rows = [];
    if (!tbl) return rows;

    tbl.querySelectorAll('tbody tr.game-row-expandable').forEach(function(gameRow) {
        if (gameRow.offsetParent === null || gameRow.style.display === 'none') return;
        var detailRow = gameRow.nextElementSibling;
        if (!detailRow || !detailRow.classList.contains('pitch-log-row') || !detailRow.dataset.src) return;
        rows.push(detailRow);
    });

    return rows;
}

// 批次預載多個比賽列的 pitch log，限制同時進行中的請求數 (concurrency)
function prefetchPitchLogRows(rows, concurrency) {
    var queue = (rows || []).filter(function(row) {
        if (!row || !row.dataset || !row.dataset.src) return false;
        var entry = pitchLogCache[row.dataset.src];
        return !entry || (!entry.html && !entry.promise);
    });
    var maxConcurrent = Math.max(1, concurrency || 6);
    var index = 0;

    if (!queue.length) return Promise.resolve([]);

    function worker() {
        if (index >= queue.length) return Promise.resolve();
        var row = queue[index++];
        return prefetchPitchLogRow(row).then(worker);
    }

    var workers = [];
    var workerCount = Math.min(maxConcurrent, queue.length);
    for (var i = 0; i < workerCount; i++) {
        workers.push(worker());
    }

    return Promise.all(workers);
}

// 預載目前頁面筛選結果中所有可見比賽列的 pitch log（最多 6 個並行）
function prefetchFilteredPitchLogs() {
    return prefetchPitchLogRows(_getFilteredPitchLogRows(), 6);
}

// 展開/收合比賽列的 pitch log 區域；首次展開時做懶性渲染
function togglePitchLog(id) {
    var row = document.getElementById(id);
    if (!row) return;
    var open = row.style.display !== 'none';
    row.style.display = open ? 'none' : '';
    var arrow = document.getElementById('arrow-' + id);
    if (arrow) arrow.style.transform = open ? '' : 'rotate(90deg)';
    // Lazy-render: build table on first open
    if (!open) {
        var container = document.getElementById(id.replace('pitchlog-', 'pitchlog-content-'));
        if (container && !container.dataset.rendered) {
            var src = row.dataset.src;
            if (src && !container.dataset.loading) {
                var cached = pitchLogCache[src];
                if (cached && cached.html) {
                    _renderPitchLog(container, cached);
                    return;
                }
                container.dataset.loading = '1';
                container.innerHTML = '<div class="pitch-log-loading">載入逐球資料中...</div>';
                _loadPitchLogData(src)
                    .then(function(entry) {
                        _renderPitchLog(container, entry);
                    })
                    .catch(function() {
                        container.innerHTML = '<div class="pitch-log-loading">逐球資料載入失敗</div>';
                    })
                    .finally(function() {
                        delete container.dataset.loading;
                    });
            }
        }
    }
}

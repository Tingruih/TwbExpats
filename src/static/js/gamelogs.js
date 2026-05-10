/**
 * gamelogs.js — 逐場紀錄 Tab 年份/聯盟篩選
 * 載入於：tab_gamelogs.j2（逐場紀錄 Tab）
 *
 * 作用：
 *  - yearSel  (#gamelog-year-select)  ：切換顯示哪一個球季的逐場表格
 *  - levelSel (#gamelog-level-select) ：切換聯盟層級篩選（MLB/AAA/AA 等）
 *  - 切換年份/聯盟後隱藏不符合的資料列（含對應的 pitch-log-row）
 *  - 切換到逐場紀錄 Tab 時觸發 Pitch Log 預載入（schedulePitchLogWarmup）
 */
document.addEventListener("DOMContentLoaded", function() {
    var yearSel = document.getElementById("gamelog-year-select");
    var levelSel = document.getElementById("gamelog-level-select");
    var prefetchScheduled = false;

    // 判斷目前是否正在看逐場紀錄 Tab（pitch log 預載前先確認）
    function isGamelogsPanelActive() {
        var panel = document.getElementById("panel-gamelogs");
        return !!panel && panel.classList.contains("tab-panel--active");
    }

    // 在瀏覽器閒置時觸發所有可見比賽列的 pitch log 預載（減少點開時的等待）
    function schedulePitchLogWarmup() {
        if (!isGamelogsPanelActive() || prefetchScheduled || typeof prefetchFilteredPitchLogs !== 'function') return;
        prefetchScheduled = true;
        var run = function() {
            prefetchScheduled = false;
            if (isGamelogsPanelActive()) prefetchFilteredPitchLogs();
        };
        if ('requestIdleCallback' in window) {
            window.requestIdleCallback(run, { timeout: 900 });
        } else {
            window.setTimeout(run, 150);
        }
    }

    // 使用者按下比賽列時，立即預載對應的 pitch log（降低展開延遲）
    function prefetchRowFromGameRow(gameRow) {
        if (!gameRow || typeof prefetchPitchLogRow !== 'function') return;
        var detailRow = gameRow.nextElementSibling;
        if (detailRow && detailRow.classList.contains("pitch-log-row")) {
            prefetchPitchLogRow(detailRow);
        }
    }

    // 依目前選擇的年份，動態更新聯盟篩選下拉的選項
    function updateLevelOptions() {
        if (!yearSel || !levelSel) return;
        var yr = yearSel.value;
        var tbl = document.getElementById("gamelogs-" + yr);
        if (!tbl) return;
        var levels = [];
        tbl.querySelectorAll("tbody tr.gamelog-data-row").forEach(function(r) {
            var lv = r.dataset.level;
            if (lv && levels.indexOf(lv) === -1) levels.push(lv);
        });
        levelSel.innerHTML = '';
        if (levels.length > 1) {
            var allOpt = document.createElement("option");
            allOpt.value = "_all";
            allOpt.textContent = "All Levels";
            levelSel.appendChild(allOpt);
        }
        levels.forEach(function(lv) {
            var opt = document.createElement("option");
            opt.value = lv;
            opt.textContent = lv;
            levelSel.appendChild(opt);
        });
    }

    // 依年份 + 聯盟篩選，顯示/隱藏對應的資料列（含 pitch log 展開列）
    function filterRows() {
        if (!yearSel || !levelSel) return;
        var yr = yearSel.value;
        var lv = levelSel.value;
        var tbl = document.getElementById("gamelogs-" + yr);
        if (!tbl) return;
        tbl.querySelectorAll("tbody tr.gamelog-data-row").forEach(function(r) {
            var show = lv === "_all" || lv === "" || r.dataset.level === lv || r.dataset.level === "";
            r.style.display = show ? "" : "none";
            var next = r.nextElementSibling;
            if (next && next.classList.contains("pitch-log-row")) {
                if (!show) next.style.display = "none";
            }
        });
        schedulePitchLogWarmup();
    }

    // 切換年份：隱藏所有年份表格容器，只顯示選擇的年份
    function showYear() {
        if (!yearSel) return;
        var yr = yearSel.value;
        document.querySelectorAll(".gamelog-table-container").forEach(function(t) {
            t.style.display = "none";
        });
        var tbl = document.getElementById("gamelogs-" + yr);
        if (tbl) tbl.style.display = "block";
        updateLevelOptions();
        filterRows();
        schedulePitchLogWarmup();
    }

    if (yearSel) yearSel.addEventListener("change", showYear);
    if (levelSel) levelSel.addEventListener("change", filterRows);

    // 滑鼠按下比賽列時觸發 pitch log 預載
    document.querySelectorAll(".game-row-expandable").forEach(function(row) {
        row.addEventListener("pointerdown", function() {
            prefetchRowFromGameRow(row);
        });
    });

    // 切換到逐場紀錄 Tab 時也觸發預載
    document.addEventListener("player-tab-change", function(event) {
        if (event.detail && event.detail.tab === "gamelogs") {
            schedulePitchLogWarmup();
        }
    });

    // Init
    if (yearSel) showYear();
});

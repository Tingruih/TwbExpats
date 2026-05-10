/**
 * arsenal-filters.js — 進階數據 Tab 球種使用率篩選
 * 載入於：tab_advanced.j2（進階數據 Tab）
 *
 * 作用：控制「進階數據」Tab 中球種使用率表格的三層篩選：
 *  - yrSel  (#arsenal-year-select)     ：切換年份
 *  - lvSel  (#arsenal-level-select)    ：切換聯盟層級（MLB/AAA/AA 等）
 *  - batSel (#arsenal-bat-side-select) ：切換對左打/右打的配球數據
 *
 * 篩選結果通過顯示/隱藏 .arsenal-table-container /
 * .arsenal-level-container / .arsenal-split-container 來實現。
 */
document.addEventListener("DOMContentLoaded", function() {
    var yrSel = document.getElementById("arsenal-year-select");
    var lvSel = document.getElementById("arsenal-level-select");
    var batSel = document.getElementById("arsenal-bat-side-select");

    // 依選擇的年份，更新聯盟層級下拉選項
    function updateArsenalLevelOptions() {
        if (!yrSel || !lvSel) return;
        var yr = yrSel.value;
        var yearContainer = document.getElementById("arsenal-" + yr);
        if (!yearContainer) return;
        var containers = yearContainer.querySelectorAll(".arsenal-level-container");
        lvSel.innerHTML = "";
        if (containers.length <= 1) {
            containers.forEach(function(c) {
                var opt = document.createElement("option");
                opt.value = c.dataset.level;
                opt.textContent = c.dataset.levelLabel;
                opt.selected = true;
                lvSel.appendChild(opt);
            });
        } else {
            containers.forEach(function(c, i) {
                var opt = document.createElement("option");
                opt.value = c.dataset.level;
                opt.textContent = c.dataset.levelLabel;
                if (i === 0) opt.selected = true;
                lvSel.appendChild(opt);
            });
        }
    }

    // 依年份 + 聯盟顯示對應的 arsenal 容器，並更新左右打篩選
    function showArsenalLevel() {
        if (!yrSel || !lvSel) return;
        var yr = yrSel.value;
        var lv = lvSel.value;
        var yearContainer = document.getElementById("arsenal-" + yr);
        if (!yearContainer) return;
        var activeLevel = null;
        yearContainer.querySelectorAll(".arsenal-level-container").forEach(function(c) {
            var isActive = c.dataset.level === lv;
            c.style.display = isActive ? "block" : "none";
            if (isActive) activeLevel = c;
        });
        showArsenalBatSide(activeLevel);
    }

    // 依對手打者慣用手（左/右/全部）顯示對應的配球數據欄
    function showArsenalBatSide(scope) {
        if (!batSel) return;
        var side = batSel.value || "all";
        var root = scope || document;
        root.querySelectorAll(".arsenal-split-container").forEach(function(c) {
            c.style.display = c.dataset.batSide === side ? "block" : "none";
        });
    }

    // 切換年份：隱藏所有年份容器，只顯示選擇的年份
    function showArsenalYear() {
        if (!yrSel) return;
        var yr = yrSel.value;
        document.querySelectorAll(".arsenal-table-container").forEach(function(t) {
            t.style.display = "none";
        });
        var tbl = document.getElementById("arsenal-" + yr);
        if (tbl) tbl.style.display = "block";
        updateArsenalLevelOptions();
        showArsenalLevel();
    }

    if (yrSel) yrSel.addEventListener("change", showArsenalYear);
    if (lvSel) lvSel.addEventListener("change", showArsenalLevel);
    if (batSel) batSel.addEventListener("change", function() {
        showArsenalLevel();
    });

    // Init
    if (yrSel) showArsenalYear();
});

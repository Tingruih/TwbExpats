/**
 * m-advanced.js — 手機版進階數據 Tab 球種篩選
 * 對應 m_advanced.j2 中的 m-arsenal-* 選單與容器
 */
document.addEventListener("DOMContentLoaded", function () {
    var yrSel = document.getElementById("m-arsenal-year-select");
    var lvSel = document.getElementById("m-arsenal-level-select");
    var batSel = document.getElementById("m-arsenal-bat-side-select");

    function updateLevelOptions() {
        if (!yrSel || !lvSel) return;
        var yr = yrSel.value;
        var yearContainer = document.getElementById("m-arsenal-" + yr);
        if (!yearContainer) return;
        var containers = yearContainer.querySelectorAll(".arsenal-level-container");
        lvSel.innerHTML = "";
        containers.forEach(function (c, i) {
            var opt = document.createElement("option");
            opt.value = c.dataset.level;
            opt.textContent = c.dataset.levelLabel;
            if (i === 0) opt.selected = true;
            lvSel.appendChild(opt);
        });
    }

    function showBatSide(scope) {
        if (!batSel) return;
        var side = batSel.value || "all";
        var root = scope || document;
        root.querySelectorAll(".arsenal-split-container").forEach(function (c) {
            c.style.display = c.dataset.batSide === side ? "block" : "none";
        });
    }

    function showLevel() {
        if (!yrSel || !lvSel) return;
        var yr = yrSel.value;
        var lv = lvSel.value;
        var yearContainer = document.getElementById("m-arsenal-" + yr);
        if (!yearContainer) return;
        var activeLevel = null;
        yearContainer.querySelectorAll(".arsenal-level-container").forEach(function (c) {
            var isActive = c.dataset.level === lv;
            c.style.display = isActive ? "block" : "none";
            if (isActive) activeLevel = c;
        });
        showBatSide(activeLevel);
    }

    function showYear() {
        if (!yrSel) return;
        var yr = yrSel.value;
        // Only hide/show containers that belong to the mobile arsenal (m-arsenal-*)
        document.querySelectorAll("[id^='m-arsenal-']").forEach(function (t) {
            // Only target year containers (direct children, not level containers)
            if (/^m-arsenal-\d{4}$/.test(t.id)) {
                t.style.display = "none";
            }
        });
        var tbl = document.getElementById("m-arsenal-" + yr);
        if (tbl) tbl.style.display = "block";
        updateLevelOptions();
        showLevel();
    }

    if (yrSel) yrSel.addEventListener("change", showYear);
    if (lvSel) lvSel.addEventListener("change", showLevel);
    if (batSel) batSel.addEventListener("change", function () { showLevel(); });

    if (yrSel) showYear();
});

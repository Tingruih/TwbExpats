/**
 * index-sort.js — 首頁球員卡片排序
 * 載入於：index.j2（僅首頁）
 *
 * 作用：點擊首頁「依層級」或「依最近出賽」按鈕時，
 * 重新排列 #player-grid 內的球員卡片順序，不重新整理頁面。
 *
 * 對外暴露：window.sortCards(mode)
 *   mode = "level"  → 依 data-level-order 升冪（AAA→AA→A）
 *   mode = "recent" → 依 data-last-game 降冪（最新出賽在前）
 */
document.addEventListener("DOMContentLoaded", function () {
    function sortCards(mode) {
        var grid = document.getElementById("player-grid");
        var cards = Array.from(grid.querySelectorAll(".player-card"));

        // 依照模式排序：層級順序 或 最近出賽日期
        cards.sort(function(a, b) {
            if (mode === "level") {
                return parseInt(a.dataset.levelOrder) - parseInt(b.dataset.levelOrder);
            } else {
                var da = a.dataset.lastGame || "0000-00-00";
                var db = b.dataset.lastGame || "0000-00-00";
                return da > db ? -1 : da < db ? 1 : 0;
            }
        });

        // 將排序後的卡片重新插入 Grid（appendChild 會自動移動 DOM 位置）
        cards.forEach(function(c) { grid.appendChild(c); });

        // 更新排序按鈕的 active 狀態
        document.getElementById("btn-level").classList.toggle("sort-btn-active", mode === "level");
        document.getElementById("btn-recent").classList.toggle("sort-btn-active", mode === "recent");
    }
    // Expose to inline onclick
    window.sortCards = sortCards;
});

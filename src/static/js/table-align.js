/**
 * table-align.js — 數字欄位對齊工具
 * 載入於：base.j2（每個頁面都有）
 *
 * 作用：掃描頁面中所有 .data-table 和 .pitch-log-table，
 * 將「資料列中含有 .num class 的欄」對應的表頭 (th) 也加上 .num，
 * 讓表格的標頭與內容的數字欄位一起靠右對齊。
 *
 * 對外暴露：window.alignNumericTableColumns(root)
 * 呼叫時機：DOMContentLoaded 時自動執行；
 *           pitch-log.js 在動態插入 pitch log 表格後也會呼叫。
 */
(function () {
    // 收集 table 所有 tbody 的資料列（排除空行）
    function rowsFor(table) {
        var rows = [];
        Array.prototype.forEach.call(table.tBodies, function (tbody) {
            Array.prototype.forEach.call(tbody.rows, function (row) {
                if (row.cells.length) rows.push(row);
            });
        });
        return rows;
    }

    // 比對每一欄：資料列有 .num 就在對應表頭也加上 .num
    function markNumericHeaders(table) {
        if (!table.tHead || !table.tHead.rows.length) return;

        var headerRow = table.tHead.rows[table.tHead.rows.length - 1];
        var bodyRows = rowsFor(table);
        Array.prototype.forEach.call(headerRow.cells, function (header, index) {
            var match = bodyRows.find(function (row) {
                return row.cells.length > index && row.cells[index].colSpan === 1;
            });
            header.classList.toggle("num", !!match && match.cells[index].classList.contains("num"));
        });
    }

    // 對外暴露：可傳入特定 root DOM 節點限縮搜尋範圍（提升效能）
    window.alignNumericTableColumns = function (root) {
        var scope = root || document;
        scope.querySelectorAll(".data-table, .pitch-log-table").forEach(markNumericHeaders);
    };

    document.addEventListener("DOMContentLoaded", function () {
        window.alignNumericTableColumns(document);
    });
}());

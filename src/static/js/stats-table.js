/**
 * stats-table.js — 賽季數據年份組展開/收合
 * 載入於：tab_stats.j2（賽季數據 Tab）
 *
 * 作用：當球員同一年效力多支球隊時，數據表格會有「年份匯總列」
 * 可以點擊展開/收合該年度各球隊的細節列。
 *
 * toggleYearGroup(tableId, yr)
 *   tableId : 對應 stats-table-{tableId} 的表格 id
 *   yr      : 年份字串，控制 data-grp="{yr}" 的列
 *             同時旋轉 #arrow-{tableId}-{yr} 的展開箭頭
 */
function toggleYearGroup(tableId, yr) {
    // Find all detail rows for this table + year
    const table = document.getElementById('stats-table-' + tableId);
    if (!table) return;
    const rows = table.querySelectorAll('tr[data-tbl="' + tableId + '"][data-grp="' + yr + '"]');
    const arrow = document.getElementById('arrow-' + tableId + '-' + yr);
    const open = rows.length > 0 && rows[0].style.display !== 'none';
    // 切換顯示/隱藏細節列
    rows.forEach(r => r.style.display = open ? 'none' : '');
    // 旋轉箭頭圖示（展開時轉 90 度）
    if (arrow) arrow.style.transform = open ? '' : 'rotate(90deg)';
}

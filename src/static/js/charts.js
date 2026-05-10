/**
 * charts.js — Chart.js 折線圖初始化
 * 載入於：tab_plot.j2（圖表 Tab）
 *
 * 作用：讀取頁面中 #chart-labels 和 #chart-data（<script type="application/json"> 嵌入）
 * 在 #performanceChart (<canvas>) 上渲染 Chart.js 折線圖，
 * 呈現球員本季逐月/逐場的某項指標（如打擊率/防禦率）走勢。
 *
 * 特殊屬性：
 *  - canvas[data-chart-label]  ：圖表 Y 軸的指標名稱（如 "AVG"）
 *  - canvas[data-reverse-y]    ：若為 "true" 則 Y 軸倒置（防禦率/WHIP 越低越好）
 */
document.addEventListener("DOMContentLoaded", function () {
    var canvas = document.getElementById("performanceChart");
    if (!canvas || typeof Chart === "undefined") return;
    var labelsEl = document.getElementById("chart-labels");
    var dataEl = document.getElementById("chart-data");
    if (!labelsEl || !dataEl) return;

    var ctx = canvas.getContext("2d");
    var labels = JSON.parse(labelsEl.textContent);
    var data = JSON.parse(dataEl.textContent);

    // teal 漸層填充背景（上方較深 → 下方透明）
    var grad = ctx.createLinearGradient(0, 0, 0, 300);
    grad.addColorStop(0, "rgba(20,184,166,0.35)");
    grad.addColorStop(1, "rgba(20,184,166,0.0)");

    new Chart(ctx, {
        type: "line",
        data: {
            labels: labels,
            datasets: [{
                label: canvas.dataset.chartLabel || "AVG",
                data: data,
                borderColor: "#14b8a6",
                backgroundColor: grad,
                borderWidth: 2.5,
                pointBackgroundColor: "#14b8a6",
                pointBorderColor: "#09090b",
                pointBorderWidth: 2,
                pointRadius: 4,
                pointHoverRadius: 6,
                fill: true,
                tension: 0.35,
            }]
        },
        options: {
            responsive: true,
            plugins: { legend: { labels: { color: "#f8fafc" } } },
            scales: {
                x: { grid: { color: "rgba(255,255,255,0.05)" }, ticks: { color: "#94a3b8" } },
                y: {
                    grid: { color: "rgba(255,255,255,0.05)" },
                    ticks: { color: "#94a3b8" },
                    // data-reverse-y="true" 表示指標越低越好（防禦率/WHIP 等），Y 軸倒置
                    reverse: canvas.dataset.reverseY === "true"
                }
            }
        }
    });
});

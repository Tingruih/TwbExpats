/**
 * pitcher-charts.js — 投手球種 SVG 圖表渲染
 * 載入於：tab_plot.j2（圖表 Tab）
 *
 * 作用：讀取嵌入頁面的 JSON 資料，渲染兩種 SVG 圖表：
 *  1. renderUsageByHand(root, data)
 *     對左打/右打的球種使用率橫條圖（左右對稱棒狀圖）
 *     位置：圖表 Tab 的「對左右打球種使用率」區塊
 *
 *  2. renderMovement(root, data)
 *     球種位移散點圖（水平/垂直位移的 x-y scatter plot）
 *     位置：圖表 Tab 的「球種位移」區塊，滑鼠移入圓點顯示 tooltip
 *
 * 依賴：頁面中以 <script type="application/json"> 嵌入的 arsenal 數據
 */
(function() {
    // 球種顏色對應表（按球種代碼）
    var PITCH_COLORS = {
        FF: "#ff0a78", FA: "#ff0a78",
        SI: "#94165d",
        FC: "#c45aa0",
        ST: "#2fc5a7",
        SL: "#68d986",
        CH: "#ff9568",
        CU: "#3326d6", KC: "#3326d6", CS: "#3326d6",
        FS: "#ff6b00", FO: "#ff6b00",
        SV: "#7c3aed",
        KN: "#a3a3a3",
        UN: "#9ca3af",
    };
    var FALLBACK_COLORS = ["#ff0a78", "#94165d", "#c45aa0", "#2fc5a7", "#ff9568", "#68d986", "#3326d6", "#ff6b00"];
    var PITCH_NAMES = {
        FF: "4-Seam", FA: "4-Seam",
        SI: "Sinker",
        FC: "Cutter",
        ST: "Sweeper",
        SL: "Slider",
        CH: "Changeup",
        CU: "Curveball", KC: "Curveball", CS: "Curveball",
        FS: "Splitter", FO: "Splitter",
        SV: "Slurve",
        KN: "Knuckleball",
        UN: "Unknown",
    };

    // XSS 防護：將字串中的 HTML 特殊字元做 escape
    function escapeHtml(value) {
        return String(value == null ? "" : value)
            .replace(/&/g, "&amp;")
            .replace(/</g, "&lt;")
            .replace(/>/g, "&gt;")
            .replace(/"/g, "&quot;")
            .replace(/'/g, "&#39;");
    }

    // 從 DOM 中讀取 <script type="application/json"> 的 JSON 資料
    function readJson(container, selector) {
        var script = container.querySelector(selector);
        if (!script) return {};
        try { return JSON.parse(script.textContent || "{}"); }
        catch (err) { return {}; }
    }

    function num(value) {
        if (value == null || value === "") return null;
        var n = Number(value);
        return Number.isFinite(n) ? n : null;
    }

    // 格式化百分比（0~1 的小數 → "12.3%" 字串）
    function fmtPct(value, digits) {
        var n = num(value);
        return n == null ? "-" : (n * 100).toFixed(digits == null ? 1 : digits) + "%";
    }

    // 格式化一般數值（速度/轉速等），null 回傳 '-'
    function fmtStat(value, digits) {
        var n = num(value);
        if (n == null) return "-";
        return digits == null ? String(Math.round(n)) : n.toFixed(digits);
    }

    function pitchName(item) {
        var type = item && item.type ? String(item.type).toUpperCase() : "UN";
        if (PITCH_NAMES[type]) return PITCH_NAMES[type];
        return String((item && item.name) || type).replace(/ Fastball$/i, "");
    }

    function pitchColor(type, index) {
        var key = String(type || "UN").toUpperCase();
        return PITCH_COLORS[key] || FALLBACK_COLORS[index % FALLBACK_COLORS.length];
    }

    function splitArsenal(data, key) {
        var split = data && data[key] ? data[key] : null;
        return split && Array.isArray(split.pitch_arsenal) ? split.pitch_arsenal : [];
    }

    function mapPitchRows(rows) {
        var out = Object.create(null);
        (rows || []).forEach(function(row) {
            var type = row.type || "UN";
            out[type] = row;
        });
        return out;
    }

    function sumCounts(rows) {
        return (rows || []).reduce(function(total, row) {
            return total + Number(row.count || 0);
        }, 0);
    }

    function emptyChart(root, message) {
        if (!root) return;
        root.innerHTML = '<div class="pitch-chart-empty">' + escapeHtml(message) + '</div>';
    }

    // 渲染「對左右打球種使用率」橫條圖 SVG
    function renderUsageByHand(root, data) {
        if (!root) return;
        var leftRows = splitArsenal(data, "L");
        var rightRows = splitArsenal(data, "R");
        var leftByType = mapPitchRows(leftRows);
        var rightByType = mapPitchRows(rightRows);
        var types = [];
        Object.keys(leftByType).concat(Object.keys(rightByType)).forEach(function(type) {
            if (types.indexOf(type) === -1) types.push(type);
        });
        types.sort(function(a, b) {
            var ac = Number((leftByType[a] && leftByType[a].count) || 0) + Number((rightByType[a] && rightByType[a].count) || 0);
            var bc = Number((leftByType[b] && leftByType[b].count) || 0) + Number((rightByType[b] && rightByType[b].count) || 0);
            return bc - ac;
        });

        if (!types.length) {
            emptyChart(root, "尚無左右打配球資料");
            return;
        }

        var width = 760;
        var minHeight = 516;
        var top = 18;
        var bottom = 78;
        var left = 116;
        var right = 54;
        var plotWidth = width - left - right;
        var center = left + plotWidth / 2;
        var half = plotWidth / 2;
        var height = Math.max(minHeight, top + bottom + types.length * 52);
        var rowStep = (height - top - bottom) / types.length;
        var ticks = [-1, -0.75, -0.5, -0.25, 0, 0.25, 0.5, 0.75, 1];
        var grid = ticks.map(function(tick) {
            var x = center + tick * half;
            var cls = tick === 0 ? "pitch-chart-zero-line" : "pitch-chart-gridline";
            return '<line class="' + cls + '" x1="' + x.toFixed(1) + '" y1="' + top + '" x2="' + x.toFixed(1) + '" y2="' + (height - bottom + 12) + '" />' +
                '<text class="pitch-chart-tick-label" x="' + x.toFixed(1) + '" y="' + (height - 42) + '">' + Math.round(Math.abs(tick) * 100) + '%</text>';
        }).join("");
        var centerLine = '<line class="pitch-chart-zero-line" x1="' + center.toFixed(1) + '" y1="' + top + '" x2="' + center.toFixed(1) + '" y2="' + (height - bottom + 12) + '" />';

        var rows = types.map(function(type, index) {
            var leftRow = leftByType[type] || null;
            var rightRow = rightByType[type] || null;
            var leftPct = Math.max(0, Math.min(1, num(leftRow && leftRow.pct) || 0));
            var rightPct = Math.max(0, Math.min(1, num(rightRow && rightRow.pct) || 0));
            var y = top + index * rowStep + rowStep / 2;
            var barHeight = Math.min(34, Math.max(24, rowStep - 18));
            var color = pitchColor(type, index);
            var labelItem = leftRow || rightRow || { type: type };
            var leftWidth = leftPct * half;
            var rightWidth = rightPct * half;
            var leftLabelX = Math.max(10, center - leftWidth - 9);
            var rightLabelX = Math.min(width - 10, center + rightWidth + 9);
            return '<g>' +
                '<text class="pitch-chart-row-label" x="' + (left - 18) + '" y="' + y.toFixed(1) + '">' + escapeHtml(pitchName(labelItem)) + '</text>' +
                (leftWidth ? '<rect class="pitch-usage-bar" x="' + (center - leftWidth).toFixed(1) + '" y="' + (y - barHeight / 2).toFixed(1) + '" width="' + leftWidth.toFixed(1) + '" height="' + barHeight + '" fill="' + color + '" />' : '') +
                (rightWidth ? '<rect class="pitch-usage-bar" x="' + center.toFixed(1) + '" y="' + (y - barHeight / 2).toFixed(1) + '" width="' + rightWidth.toFixed(1) + '" height="' + barHeight + '" fill="' + color + '" />' : '') +
                (leftRow ? '<text class="pitch-usage-value-label pitch-usage-value-label--left" x="' + leftLabelX.toFixed(1) + '" y="' + y.toFixed(1) + '">' + fmtPct(leftPct, 1) + '</text>' : '') +
                (rightRow ? '<text class="pitch-usage-value-label" x="' + rightLabelX.toFixed(1) + '" y="' + y.toFixed(1) + '">' + fmtPct(rightPct, 1) + '</text>' : '') +
                '</g>';
        }).join("");

        var leftTotal = sumCounts(leftRows);
        var rightTotal = sumCounts(rightRows);
        root.innerHTML = '<div class="pitch-chart-heading"><h3>對左右打球種使用率</h3></div>' +
            '<svg class="pitch-chart-svg pitch-usage-hand-svg" viewBox="0 0 ' + width + ' ' + height + '" role="img" aria-label="Pitch Usage by Batter Hand">' +
            grid + rows + centerLine +
            '<text class="pitch-chart-axis-label" x="' + center + '" y="' + (height - 16) + '">Usage %</text>' +
            '<text class="pitch-chart-hand-label" x="' + (center - half * 0.5) + '" y="' + (height - 16) + '">vs LHH (' + leftTotal + ')</text>' +
            '<text class="pitch-chart-hand-label" x="' + (center + half * 0.5) + '" y="' + (height - 16) + '">vs RHH (' + rightTotal + ')</text>' +
            '</svg>';
    }

    function ceilStep(value, step) {
        return Math.ceil(value / step) * step;
    }

    function floorStep(value, step) {
        return Math.floor(value / step) * step;
    }

    function ticks(min, max, step) {
        var out = [];
        for (var v = min; v <= max + 0.0001; v += step) out.push(v);
        return out;
    }

    function moveTooltip(root, tooltip, event) {
        var rect = root.getBoundingClientRect();
        var left = event.clientX - rect.left + 14;
        var top = event.clientY - rect.top - tooltip.offsetHeight / 2;
        left = Math.min(left, root.clientWidth - tooltip.offsetWidth - 8);
        top = Math.max(8, Math.min(top, root.clientHeight - tooltip.offsetHeight - 8));
        tooltip.style.left = left + "px";
        tooltip.style.top = top + "px";
    }

    function movementTooltipHtml(el) {
        return '<div class="pitch-chart-tooltip-title">' + escapeHtml(el.dataset.name || el.dataset.type || "Pitch") + '</div>' +
            '<div class="pitch-chart-tooltip-row"><span>Velo</span><strong>' + escapeHtml(fmtStat(el.dataset.velo, 1)) + '</strong></div>' +
            '<div class="pitch-chart-tooltip-row"><span>Spin</span><strong>' + escapeHtml(fmtStat(el.dataset.spin)) + '</strong></div>' +
            '<div class="pitch-chart-tooltip-row"><span>HB</span><strong>' + escapeHtml(fmtStat(el.dataset.hb, 1)) + '</strong></div>' +
            '<div class="pitch-chart-tooltip-row"><span>iVB</span><strong>' + escapeHtml(fmtStat(el.dataset.ivb, 1)) + '</strong></div>';
    }

    function bindMovementTooltips(root) {
        var tooltip = root.querySelector(".pitch-chart-tooltip");
        if (!tooltip) return;
        root.querySelectorAll(".pitch-movement-point").forEach(function(point) {
            point.addEventListener("pointerenter", function(event) {
                tooltip.innerHTML = movementTooltipHtml(point);
                tooltip.classList.add("pitch-chart-tooltip--visible");
                moveTooltip(root, tooltip, event);
            });
            point.addEventListener("pointermove", function(event) {
                if (tooltip.classList.contains("pitch-chart-tooltip--visible")) {
                    moveTooltip(root, tooltip, event);
                }
            });
            point.addEventListener("pointerleave", function() {
                tooltip.classList.remove("pitch-chart-tooltip--visible");
            });
        });
    }

    // \u6e32\u67d3\u300c\u7403\u7a2e\u4f4d\u79fb\u6563\u9ede\u5716\u300d SVG\uff08\u6c34\u5e73\u4f4d\u79fb HB vs. \u5782\u76f4\u4f4d\u79fb iVB\uff09
    function renderMovement(root, data) {
        if (!root) return;
        var points = ((data && data.points) || []).filter(function(point) {
            return num(point.hb) != null && num(point.ivb) != null;
        });
        if (!points.length) {
            emptyChart(root, "尚無投球位移資料");
            return;
        }

        var width = 760;
        var height = 520;
        var left = 74;
        var right = 28;
        var top = 18;
        var bottom = 82;
        var plotWidth = width - left - right;
        var plotHeight = height - top - bottom;
        var xs = points.map(function(point) { return num(point.hb) || 0; });
        var ys = points.map(function(point) { return num(point.ivb) || 0; });
        var maxAbsX = Math.max(10, ceilStep(Math.max.apply(null, xs.map(Math.abs)), 5));
        var minY = Math.min.apply(null, ys);
        var maxY = Math.max.apply(null, ys);
        var yMin = Math.min(-10, floorStep(minY, 5));
        var yMax = Math.max(10, ceilStep(maxY, 5));
        if (yMax - yMin < 20) {
            yMin -= 5;
            yMax += 5;
        }
        var xStep = maxAbsX > 20 ? 10 : 5;
        var yStep = (yMax - yMin) > 30 ? 10 : 5;
        var xTicks = ticks(-maxAbsX, maxAbsX, xStep);
        var yTicks = ticks(yMin, yMax, yStep);
        var orderedTypes = ((data && data.pitch_types) || []).map(function(pt) { return pt.type || "UN"; });
        var colorIndexByType = Object.create(null);
        orderedTypes.forEach(function(type, index) { colorIndexByType[type] = index; });

        function xScale(value) {
            return left + ((value + maxAbsX) / (maxAbsX * 2)) * plotWidth;
        }

        function yScale(value) {
            return top + ((yMax - value) / (yMax - yMin)) * plotHeight;
        }

        var grid = xTicks.map(function(tick) {
            var x = xScale(tick);
            var cls = tick === 0 ? "pitch-chart-zero-line" : "pitch-chart-gridline";
            return '<line class="' + cls + '" x1="' + x.toFixed(1) + '" y1="' + top + '" x2="' + x.toFixed(1) + '" y2="' + (height - bottom) + '" />' +
                '<text class="pitch-chart-tick-label" x="' + x.toFixed(1) + '" y="' + (height - bottom + 25) + '">' + tick + '</text>';
        }).join("") + yTicks.map(function(tick) {
            var y = yScale(tick);
            var cls = tick === 0 ? "pitch-chart-zero-line pitch-chart-zero-line--horizontal" : "pitch-chart-gridline";
            return '<line class="' + cls + '" x1="' + left + '" y1="' + y.toFixed(1) + '" x2="' + (width - right) + '" y2="' + y.toFixed(1) + '" />' +
                '<text class="pitch-chart-y-tick-label" x="' + (left - 12) + '" y="' + y.toFixed(1) + '">' + tick + '</text>';
        }).join("");

        var pointSvg = points.map(function(point, index) {
            var type = point.type || "UN";
            var typeIndex = colorIndexByType[type] == null ? index : colorIndexByType[type];
            var color = pitchColor(type, typeIndex);
            return '<circle class="pitch-movement-point" cx="' + xScale(num(point.hb)).toFixed(1) + '" cy="' + yScale(num(point.ivb)).toFixed(1) + '" r="4.6" fill="' + color + '" ' +
                'data-type="' + escapeHtml(type) + '" data-name="' + escapeHtml(pitchName(point)) + '" data-velo="' + escapeHtml(point.velo == null ? "" : point.velo) + '" ' +
                'data-spin="' + escapeHtml(point.spin == null ? "" : point.spin) + '" data-hb="' + escapeHtml(point.hb) + '" data-ivb="' + escapeHtml(point.ivb) + '" />';
        }).join("");

        var legend = '<div class="pitch-chart-legend">' + ((data && data.pitch_types) || []).map(function(pt, index) {
            return '<span class="pitch-chart-legend-item"><i style="background:' + pitchColor(pt.type, index) + '"></i>' + escapeHtml(pitchName(pt)) + '</span>';
        }).join("") + '</div>';

        root.innerHTML = '<div class="pitch-chart-heading"><h3>球種位移</h3></div>' +
            '<svg class="pitch-chart-svg pitch-movement-svg" viewBox="0 0 ' + width + ' ' + height + '" role="img" aria-label="Pitch Movement">' +
            grid + pointSvg +
            '<text class="pitch-chart-axis-label" x="' + (left + plotWidth / 2) + '" y="' + (height - 20) + '">Horizontal Break (in)</text>' +
            '<text class="pitch-chart-axis-label pitch-chart-axis-label--vertical" x="22" y="' + (top + plotHeight / 2) + '" transform="rotate(-90 22 ' + (top + plotHeight / 2) + ')">Induced Vertical Break (in)</text>' +
            '</svg>' + legend + '<div class="pitch-chart-tooltip"></div>';
        bindMovementTooltips(root);
    }

    function initPitcherCharts() {
        document.querySelectorAll(".pitch-plinko-level-container").forEach(function(container) {
            var usageRoot = container.querySelector(".pitch-usage-hand-root");
            if (usageRoot) renderUsageByHand(usageRoot, readJson(container, ".pitch-usage-hand-data"));
            var movementRoot = container.querySelector(".pitch-movement-root");
            if (movementRoot) renderMovement(movementRoot, readJson(container, ".pitch-movement-data"));
        });
    }

    document.addEventListener("DOMContentLoaded", initPitcherCharts);
})();

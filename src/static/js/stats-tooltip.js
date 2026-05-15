// stats-tooltip.js — 表格欄位說明 Tooltip（position:fixed，不受 overflow 裁切）
(function () {
    const tip = document.createElement('div');
    Object.assign(tip.style, {
        position:     'fixed',
        background:   'rgba(12,12,28,0.97)',
        color:        '#dde',
        fontSize:     '0.73rem',
        lineHeight:   '1.4',
        padding:      '5px 10px',
        borderRadius: '6px',
        border:       '1px solid rgba(255,255,255,0.12)',
        boxShadow:    '0 4px 14px rgba(0,0,0,0.45)',
        pointerEvents:'none',
        zIndex:       '9999',
        whiteSpace:   'nowrap',
        visibility:   'hidden',
        opacity:      '0',
        transition:   'opacity 0.12s',
    });
    document.body.appendChild(tip);

    var activeHeader = null;

    function positionTip(header) {
        var rect = header.getBoundingClientRect();
        var tipWidth = tip.offsetWidth;
        var tipHeight = tip.offsetHeight;
        var left = rect.left + rect.width / 2 - tipWidth / 2;
        var top = rect.top - tipHeight - 6;

        // 超出左右視窗邊界時夾住
        left = Math.max(4, Math.min(left, window.innerWidth - tipWidth - 4));
        // 若頂部空間不足則改為顯示在下方
        if (top < 4) top = rect.bottom + 6;

        tip.style.left = left + 'px';
        tip.style.top = top + 'px';
    }

    function showTip(header) {
        activeHeader = header;
        tip.textContent = header.dataset.tooltip;
        tip.style.visibility = 'visible';
        tip.style.opacity = '1';
        positionTip(header);
    }

    function hideTip() {
        activeHeader = null;
        tip.style.opacity = '0';
        tip.style.visibility = 'hidden';
    }

    document.addEventListener('mouseover', function (event) {
        var header = event.target.closest && event.target.closest('th[data-tooltip]');
        if (!header || header === activeHeader || header.contains(event.relatedTarget)) return;
        showTip(header);
    });

    document.addEventListener('mouseout', function (event) {
        if (!activeHeader || activeHeader.contains(event.relatedTarget)) return;
        hideTip();
    });

    window.addEventListener('resize', function () {
        if (activeHeader) positionTip(activeHeader);
    });
}());

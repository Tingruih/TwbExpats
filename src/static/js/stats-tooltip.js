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

    document.querySelectorAll('th[data-tooltip]').forEach(function (th) {
        th.addEventListener('mouseenter', function () {
            tip.textContent = th.dataset.tooltip;
            tip.style.visibility = 'visible';
            tip.style.opacity = '1';

            var r    = th.getBoundingClientRect();
            var tipW = tip.offsetWidth;
            var tipH = tip.offsetHeight;
            var left = r.left + r.width / 2 - tipW / 2;
            var top  = r.top - tipH - 6;

            // 超出左右視窗邊界時夾住
            left = Math.max(4, Math.min(left, window.innerWidth - tipW - 4));
            // 若頂部空間不足則改為顯示在下方
            if (top < 4) top = r.bottom + 6;

            tip.style.left = left + 'px';
            tip.style.top  = top  + 'px';
        });
        th.addEventListener('mouseleave', function () {
            tip.style.opacity    = '0';
            tip.style.visibility = 'hidden';
        });
    });
}());

(function () {
    var menu = document.getElementById('menu');
    var toggleBtn = document.getElementById('menu-toggle');

    if (!menu || !toggleBtn) return;

    function isOpen() {
        return menu.classList.contains('menu--open');
    }

    function openMenu() {
        menu.classList.add('menu--open');
        toggleBtn.setAttribute('aria-expanded', 'true');
    }

    function closeMenu() {
        menu.classList.remove('menu--open');
        toggleBtn.setAttribute('aria-expanded', 'false');
    }

    toggleBtn.addEventListener('click', function (e) {
        e.stopPropagation();
        if (isOpen()) closeMenu();
        else openMenu();
    });

    // 點選單以外的任何地方就關閉
    document.addEventListener('click', function (e) {
        if (isOpen() && !menu.contains(e.target)) closeMenu();
    });

    // Esc 關閉並把焦點移回按鈕
    document.addEventListener('keydown', function (e) {
        if (e.key === 'Escape' && isOpen()) {
            closeMenu();
            toggleBtn.focus();
        }
    });

})();

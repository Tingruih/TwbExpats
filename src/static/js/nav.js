(function () {
    var nav = document.getElementById('site-nav');
    var toggleBtn = document.querySelector('.menu-toggle');
    var backdrop = document.getElementById('site-nav-backdrop');

    if (!nav || !toggleBtn) return;

    function openNav() {
        nav.classList.add('site-nav--open');
        toggleBtn.setAttribute('aria-expanded', 'true');
        document.body.style.overflow = 'hidden';
    }

    function closeNav() {
        nav.classList.remove('site-nav--open');
        toggleBtn.setAttribute('aria-expanded', 'false');
        document.body.style.overflow = '';
    }

    toggleBtn.addEventListener('click', function () {
        if (nav.classList.contains('site-nav--open')) closeNav();
        else openNav();
    });

    if (backdrop) backdrop.addEventListener('click', closeNav);

    document.addEventListener('keydown', function (e) {
        if (e.key === 'Escape' && nav.classList.contains('site-nav--open')) closeNav();
    });

})();

document.addEventListener('click', function (e) {
    const btn = e.target.closest('[data-m-show-more]');
    if (!btn) return;
    const timeline = btn.previousElementSibling;
    if (!timeline || !timeline.hasAttribute('data-m-timeline')) return;
    timeline.classList.add('is-expanded');
    btn.remove();
});

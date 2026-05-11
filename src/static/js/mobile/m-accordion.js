(function() {
    var STORAGE_PREFIX = 'twbexpats.mobile.accordion.';

    function storageKey(details) {
        return STORAGE_PREFIX + details.dataset.mAccordion;
    }

    function restore(details) {
        if (!details.dataset.mAccordion || !window.sessionStorage) return;
        var value = sessionStorage.getItem(storageKey(details));
        if (value === 'open') details.open = true;
        if (value === 'closed') details.open = false;
    }

    function bind(details) {
        restore(details);
        details.addEventListener('toggle', function() {
            if (!details.dataset.mAccordion || !window.sessionStorage) return;
            sessionStorage.setItem(storageKey(details), details.open ? 'open' : 'closed');
        });
    }

    function init() {
        document.querySelectorAll('[data-m-accordion]').forEach(bind);
    }

    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init);
    else init();
})();
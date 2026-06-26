/**
 * avatar-fallback.js — 球員頭像分批載入 + 備用顯示
 * 載入於：base.j2（每個頁面都有）
 *
 * 作用：
 *  1. 分批載入：帶有 data-src 的頭像（lazy=True）不會立刻載入，
 *     先載入目前畫面內可見的頭像，全部完成（含失敗）後才載入畫面外其他球員的頭像。
 *  2. 失敗備援：所有 .avatar-img 圖片，若載入失敗：
 *     a. 先嘗試 data-cdn-src 屬性指定的 CDN 備用網址
 *     b. 若 CDN 也失敗，隱藏 img 並顯示 .avatar-fallback（文字縮寫頭像）
 */
document.addEventListener("DOMContentLoaded", function () {
    var avatars = document.querySelectorAll(".avatar-img");

    avatars.forEach(function (img) {
        img.addEventListener("error", function () {
            // 第一次失敗：嘗試 CDN 備用來源
            if (!this.dataset.cdnTried) {
                this.dataset.cdnTried = "1";
                var cdn = this.dataset.cdnSrc;
                if (cdn) { this.src = cdn; return; }
            }
            // CDN 也失敗：隱藏圖片，顯示文字縮寫頭像
            this.style.display = "none";
            var fallback = this.parentElement.querySelector(".avatar-fallback");
            if (fallback) fallback.style.display = "flex";
        });
    });

    var deferred = Array.prototype.filter.call(avatars, function (img) {
        return img.dataset.src;
    });
    if (!deferred.length) return;

    // 依目前畫面可見範圍分成「畫面內」與「畫面外」兩批
    var viewportBottom = window.innerHeight;
    var visible = [];
    var rest = [];
    deferred.forEach(function (img) {
        var top = img.getBoundingClientRect().top;
        (top < viewportBottom ? visible : rest).push(img);
    });

    function load(img) {
        return new Promise(function (resolve) {
            img.addEventListener("load", resolve, { once: true });
            img.addEventListener("error", resolve, { once: true });
            img.src = img.dataset.src;
        });
    }

    // 畫面內頭像全部載入完成（成功或失敗）後，才開始載入畫面外的頭像
    Promise.all(visible.map(load)).then(function () {
        rest.forEach(load);
    });
});

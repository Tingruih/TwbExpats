/**
 * avatar-fallback.js — 球員頭像備用顯示
 * 載入於：base.j2（每個頁面都有）
 *
 * 作用：所有帶有 .avatar-img class 的圖片，若載入失敗時：
 *  1. 先嘗試 data-cdn-src 屬性指定的 CDN 備用網址
 *  2. 若 CDN 也失敗，隱藏 img 並顯示 .avatar-fallback（文字縮寫頭像）
 */
document.addEventListener("DOMContentLoaded", function () {
    document.querySelectorAll(".avatar-img").forEach(function(img) {
        img.addEventListener("error", function() {
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
});

function initPage() {
    document.documentElement.dataset.js = "ready";
}

if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", initPage, { once: true });
} else {
    initPage();
}
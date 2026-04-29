document.documentElement.dataset.js = "ready";

const pageInitializers = [];

if (document.querySelector("[data-index-card]") || document.querySelector("[data-index-delete-button]")) {
    pageInitializers.push(
        import("./index.js").then(({ initIndexPage }) => {
            initIndexPage();
        })
    );
}

if (document.getElementById("event-playlist") || document.querySelector("[data-viewer-delete-button]")) {
    pageInitializers.push(
        import("./event_player.js").then(({ initPlayerPage }) => {
            initPlayerPage();
        })
    );
}

Promise.allSettled(pageInitializers).then((results) => {
    for (const result of results) {
        if (result.status === "rejected") {
            console.error(result.reason);
        }
    }
});

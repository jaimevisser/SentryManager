import { initEventPlayer } from "./event_player-page.js";
import { initViewerDelete } from "./event_player-viewer-delete.js";

export function initPlayerPage() {
    initViewerDelete();
    initEventPlayer();
}

import {
    getBottomCornerSafeRect,
    getContainedVideoRect,
    getTopCornerSafeRect,
    getVideoAspectRatio,
} from "./event_player-page-helpers.js";

export function createStageSafeZoneController({
    windowObject,
    player,
    viewFrame,
    stageSafeZones,
    secondaryPlayers,
}) {
    let stageSafeZoneUpdatePending = false;

    function applyStageSafeZone(node, rect) {
        if (!node || !rect || rect.width < 1 || rect.height < 1) {
            if (node) {
                node.hidden = true;
                node.style.width = "0px";
                node.style.height = "0px";
                node.style.setProperty("--player-safe-zone-width", "0px");
                node.style.setProperty("--player-safe-zone-height", "0px");
            }
            return;
        }

        node.hidden = false;
        node.style.width = `${rect.width}px`;
        node.style.height = `${rect.height}px`;
        node.style.setProperty("--player-safe-zone-width", `${rect.width}px`);
        node.style.setProperty("--player-safe-zone-height", `${rect.height}px`);
    }

    function updateStageSafeZones() {
        if (!viewFrame || !stageSafeZones.left || !stageSafeZones.right) {
            return;
        }

        const masterAspectRatio = getVideoAspectRatio(player);
        const leftAspectRatio = getVideoAspectRatio(secondaryPlayers.left) || masterAspectRatio;
        const rightAspectRatio = getVideoAspectRatio(secondaryPlayers.right) || masterAspectRatio;
        if (!(masterAspectRatio > 0)) {
            applyStageSafeZone(stageSafeZones.left, null);
            applyStageSafeZone(stageSafeZones.right, null);
            applyStageSafeZone(stageSafeZones.topLeft, null);
            return;
        }

        const frameWidth = viewFrame.clientWidth;
        const frameHeight = viewFrame.clientHeight;
        if (!(frameWidth > 0) || !(frameHeight > 0)) {
            applyStageSafeZone(stageSafeZones.left, null);
            applyStageSafeZone(stageSafeZones.right, null);
            applyStageSafeZone(stageSafeZones.topLeft, null);
            return;
        }

        const frameStyles = getComputedStyle(viewFrame);
        const leftPadding = Number.parseFloat(frameStyles.paddingLeft) || 0;
        const rightPadding = Number.parseFloat(frameStyles.paddingRight) || 0;
        const columnGap = Number.parseFloat(frameStyles.columnGap) || 0;
        const usableWidth = Math.max(0, frameWidth - leftPadding - rightPadding);
        if (!(usableWidth > 0)) {
            applyStageSafeZone(stageSafeZones.left, null);
            applyStageSafeZone(stageSafeZones.right, null);
            applyStageSafeZone(stageSafeZones.topLeft, null);
            return;
        }

        const contentRects = [];
        const pushContainedRect = (containerRect, aspectRatio) => {
            const contentRect = getContainedVideoRect(containerRect, aspectRatio);
            if (contentRect) {
                contentRects.push(contentRect);
            }
        };

        pushContainedRect({
            left: leftPadding,
            top: 0,
            width: usableWidth,
            height: frameHeight,
        }, masterAspectRatio);

        const doubleShellWidth = Math.max(0, (usableWidth - columnGap) / 2);
        pushContainedRect({
            left: leftPadding,
            top: 0,
            width: doubleShellWidth,
            height: frameHeight,
        }, leftAspectRatio);
        pushContainedRect({
            left: leftPadding + doubleShellWidth + columnGap,
            top: 0,
            width: doubleShellWidth,
            height: frameHeight,
        }, masterAspectRatio);

        const tripleMainHeight = frameHeight * (2 / 3);
        const tripleBottomHeight = frameHeight - tripleMainHeight;
        const tripleBottomShellWidth = Math.min(usableWidth / 2, tripleBottomHeight * (16 / 9));
        const tripleCenterX = leftPadding + (usableWidth / 2);

        pushContainedRect({
            left: leftPadding,
            top: 0,
            width: usableWidth,
            height: tripleMainHeight,
        }, masterAspectRatio);
        pushContainedRect({
            left: tripleCenterX - tripleBottomShellWidth,
            top: tripleMainHeight,
            width: tripleBottomShellWidth,
            height: tripleBottomHeight,
        }, leftAspectRatio);
        pushContainedRect({
            left: tripleCenterX,
            top: tripleMainHeight,
            width: tripleBottomShellWidth,
            height: tripleBottomHeight,
        }, rightAspectRatio);

        const leftRect = getBottomCornerSafeRect(contentRects, frameWidth, frameHeight, "left");
        const rightRect = getBottomCornerSafeRect(contentRects, frameWidth, frameHeight, "right");
        const topLeftRect = getTopCornerSafeRect(contentRects, frameWidth, frameHeight, "left");
        applyStageSafeZone(stageSafeZones.left, leftRect);
        applyStageSafeZone(stageSafeZones.right, rightRect);
        applyStageSafeZone(stageSafeZones.topLeft, topLeftRect);
    }

    function scheduleStageSafeZoneUpdate() {
        if (stageSafeZoneUpdatePending) {
            return;
        }
        stageSafeZoneUpdatePending = true;
        windowObject.requestAnimationFrame(() => {
            stageSafeZoneUpdatePending = false;
            updateStageSafeZones();
        });
    }

    return {
        updateStageSafeZones,
        scheduleStageSafeZoneUpdate,
    };
}
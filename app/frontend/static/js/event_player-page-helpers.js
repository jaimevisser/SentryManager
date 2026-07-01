export function getSecondaryCameraKeyMapForSelection(layout, cameraKey, cameraLayoutSequence) {
    if (layout === "single") {
        return { left: null, right: null };
    }
    if (layout === "double") {
        return { left: getCameraOffsetKey(cameraKey, -1, cameraLayoutSequence), right: null };
    }
    return {
        left: getCameraOffsetKey(cameraKey, -1, cameraLayoutSequence),
        right: getCameraOffsetKey(cameraKey, 1, cameraLayoutSequence),
    };
}

export function getVisibleCameraKeysForSelection(
    layout,
    cameraKey,
    cameraLayoutSequence,
    getFirstAvailableCameraKey,
    hasCameraPlaylist,
) {
    const safeCameraKey = getFirstAvailableCameraKey(cameraKey);
    const visibleCameraKeys = new Set(safeCameraKey ? [safeCameraKey] : []);
    const secondaryCameraKeys = getSecondaryCameraKeyMapForSelection(layout, safeCameraKey, cameraLayoutSequence);
    for (const nextCameraKey of Object.values(secondaryCameraKeys)) {
        if (nextCameraKey && hasCameraPlaylist(nextCameraKey)) {
            visibleCameraKeys.add(nextCameraKey);
        }
    }
    return visibleCameraKeys;
}

export function normalizePersistedTime(value) {
    return Math.round(Math.max(0, value) * 1000) / 1000;
}

export function normalizeExportFormat(value) {
    return value === "hd" ? "hd" : "4k";
}

export function isRenderJobActive(job) {
    return Boolean(job && (job.status === "queued" || job.status === "running"));
}

export function getRenderJobStatusMessage(job, hasLatestRender) {
    if (!job || typeof job !== "object") {
        return hasLatestRender ? "Ready" : "";
    }
    if (job.status === "queued") {
        return formatRenderStatusMessage(job.progressMessage, "Queued...");
    }
    if (job.status === "running") {
        return formatRenderStatusMessage(job.progressMessage, "Rendering...");
    }
    if (job.status === "failed") {
        return formatRenderStatusMessage(job.errorMessage, "Could not render export.");
    }
    return "Ready";
}

export function formatSpeedText(speedKph) {
    if (speedKph === null) {
        return "";
    }
    const roundedSpeed = Math.round(speedKph);
    return `<span class="player-safe-zone-value-number">${roundedSpeed}</span><span class="player-safe-zone-value-unit">km/h</span>`;
}

export function normalizeDriverAssistDisplay(rawDriverAssistDisplay) {
    if (!rawDriverAssistDisplay || typeof rawDriverAssistDisplay !== "object") {
        return null;
    }

    const rawLabel = rawDriverAssistDisplay.label;
    const rawPercent = rawDriverAssistDisplay.percent;
    const rawText = rawDriverAssistDisplay.text;
    if ((rawLabel !== "FSD" && rawLabel !== "AP") || typeof rawPercent !== "number" || !Number.isFinite(rawPercent)) {
        return null;
    }

    const percent = Math.max(0, Math.min(100, rawPercent));
    return {
        label: rawLabel,
        percent,
        text: typeof rawText === "string" && rawText.trim()
            ? rawText
            : `${rawLabel} ${Math.round(percent)}%`,
    };
}

export function formatDriverAssistDisplayText(driverAssistDisplay) {
    if (driverAssistDisplay === null) {
        return "";
    }
    return driverAssistDisplay.text;
}

export function findTelemetrySampleIndex(timeMs, telemetry) {
    const times = telemetry?.timeMs;
    if (!times || times.length === 0) {
        return -1;
    }

    let low = 0;
    let high = times.length - 1;
    while (low <= high) {
        const middle = Math.floor((low + high) / 2);
        const candidate = times[middle];
        if (candidate <= timeMs) {
            low = middle + 1;
            continue;
        }
        high = middle - 1;
    }

    if (high >= 0) {
        return high;
    }
    return 0;
}

export function getCompassDirectionLabel(headingDeg) {
    const normalizedHeading = ((headingDeg % 360) + 360) % 360;
    if (normalizedHeading >= 45 && normalizedHeading < 135) {
        return "E";
    }
    if (normalizedHeading >= 135 && normalizedHeading < 225) {
        return "S";
    }
    if (normalizedHeading >= 225 && normalizedHeading < 315) {
        return "W";
    }
    return "N";
}

export function getVideoAspectRatio(videoElement) {
    if (!videoElement) {
        return null;
    }
    if (videoElement.videoWidth > 0 && videoElement.videoHeight > 0) {
        return videoElement.videoWidth / videoElement.videoHeight;
    }
    return null;
}

export function getContainedVideoRect(containerRect, aspectRatio) {
    if (!containerRect || !(containerRect.width > 0) || !(containerRect.height > 0) || !(aspectRatio > 0)) {
        return null;
    }

    const containerAspectRatio = containerRect.width / containerRect.height;
    if (containerAspectRatio > aspectRatio) {
        const height = containerRect.height;
        const width = height * aspectRatio;
        const left = containerRect.left + ((containerRect.width - width) / 2);
        return {
            left,
            top: containerRect.top,
            right: left + width,
            bottom: containerRect.top + height,
        };
    }

    const width = containerRect.width;
    const height = width / aspectRatio;
    const top = containerRect.top + ((containerRect.height - height) / 2);
    return {
        left: containerRect.left,
        top,
        right: containerRect.left + width,
        bottom: top + height,
    };
}

export function getBottomCornerSafeRect(contentRects, frameWidth, frameHeight, side) {
    const breakpoints = new Set([0, frameHeight]);
    for (const rect of contentRects) {
        breakpoints.add(Math.max(0, Math.min(frameHeight, rect.top)));
        breakpoints.add(Math.max(0, Math.min(frameHeight, rect.bottom)));
    }

    let bestRect = { width: 0, height: 0 };
    let bestArea = 0;

    for (const top of Array.from(breakpoints).sort((left, right) => left - right)) {
        let availableWidth = frameWidth;
        for (const rect of contentRects) {
            if (rect.bottom <= top || rect.top >= frameHeight) {
                continue;
            }
            if (side === "left") {
                availableWidth = Math.min(availableWidth, rect.left);
            } else {
                availableWidth = Math.min(availableWidth, frameWidth - rect.right);
            }
        }

        const height = frameHeight - top;
        const width = Math.max(0, availableWidth);
        const area = width * height;
        if (area > bestArea) {
            bestArea = area;
            bestRect = { width, height };
        }
    }

    return bestRect;
}

export function getTopCornerSafeRect(contentRects, frameWidth, frameHeight, side) {
    const breakpoints = new Set([0, frameHeight]);
    for (const rect of contentRects) {
        breakpoints.add(Math.max(0, Math.min(frameHeight, rect.top)));
        breakpoints.add(Math.max(0, Math.min(frameHeight, rect.bottom)));
    }

    let bestRect = { width: 0, height: 0 };
    let bestArea = 0;

    for (const bottom of Array.from(breakpoints).sort((left, right) => left - right)) {
        let availableWidth = frameWidth;
        for (const rect of contentRects) {
            if (rect.bottom <= 0 || rect.top >= bottom) {
                continue;
            }
            if (side === "left") {
                availableWidth = Math.min(availableWidth, rect.left);
            } else {
                availableWidth = Math.min(availableWidth, frameWidth - rect.right);
            }
        }

        const height = Math.max(0, bottom);
        const width = Math.max(0, availableWidth);
        const area = width * height;
        if (area > bestArea) {
            bestArea = area;
            bestRect = { width, height };
        }
    }

    return bestRect;
}

function getCameraOffsetKey(cameraKey, offset, cameraLayoutSequence) {
    const currentIndex = cameraLayoutSequence.indexOf(cameraKey);
    if (currentIndex < 0) {
        return null;
    }
    const nextIndex = (currentIndex + offset + cameraLayoutSequence.length) % cameraLayoutSequence.length;
    return cameraLayoutSequence[nextIndex];
}

function formatRenderStatusMessage(message, fallbackMessage) {
    if (typeof message !== "string") {
        return fallbackMessage;
    }
    const compactMessage = message.replace(/\s+/g, " ").trim();
    if (!compactMessage) {
        return fallbackMessage;
    }
    if (compactMessage.length <= 180) {
        return compactMessage;
    }
    return `${compactMessage.slice(0, 179).trimEnd()}...`;
}
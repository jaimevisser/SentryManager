function initPage() {
    document.documentElement.dataset.js = "ready";
    initEventPlayer();
}

function initEventPlayer() {
    const player = document.querySelector("[data-event-player]");
    const playlistNode = document.getElementById("event-playlist");
    if (!player || !playlistNode) {
        return;
    }

    let playlistConfig;
    try {
        playlistConfig = JSON.parse(playlistNode.textContent || "{}");
    } catch {
        return;
    }

    const allPlaylists = playlistConfig?.playlists;
    const defaultViewKey = playlistConfig?.defaultViewKey;
    const rawEventMarkerTime = playlistConfig?.eventMarkerTime;
    const eventMarkerTime = typeof rawEventMarkerTime === "number" && Number.isFinite(rawEventMarkerTime)
        ? rawEventMarkerTime
        : null;
    if (!allPlaylists || typeof allPlaylists !== "object" || !defaultViewKey) {
        return;
    }

    const compositeViews = {
        full_rear: {
            master: "back",
            secondarySlots: {
                left: "right_repeater",
                right: "left_repeater",
            },
        },
        full_front: {
            master: "front",
            secondarySlots: {
                left: "left_pillar",
                right: "right_pillar",
            },
        },
    };

    function getCompositeView(viewKey) {
        return compositeViews[viewKey] || null;
    }

    function getMasterCameraKey(viewKey) {
        return getCompositeView(viewKey)?.master || viewKey;
    }

    let activeViewKey = defaultViewKey;
    let activeCameraKey = getMasterCameraKey(activeViewKey);
    let playlist = allPlaylists[activeCameraKey];
    if (!Array.isArray(playlist) || playlist.length === 0) {
        return;
    }

    const currentTimeNode = document.querySelector("[data-player-current-time]");
    const totalTimeNode = document.querySelector("[data-player-total-time]");
    const scrubber = document.querySelector("[data-player-scrub]");
    const eventMarker = document.querySelector("[data-player-event-marker]");
    const toggleButton = document.querySelector("[data-player-toggle]");
    const toggleIcon = document.querySelector("[data-player-toggle-icon]");
    const viewButtons = Array.from(document.querySelectorAll("[data-view-option]"));
    const viewFrame = document.querySelector("[data-player-view-frame]");
    const compositeGrid = document.querySelector("[data-composite-grid]");
    const secondaryPlayers = {
        left: document.querySelector('[data-secondary-slot="left"]'),
        right: document.querySelector('[data-secondary-slot="right"]'),
    };
    const preloadPlayers = {
        master: document.createElement("video"),
        left: document.createElement("video"),
        right: document.createElement("video"),
    };
    let activeIndex = 0;
    let pendingSeekTime = null;
    let pendingEventTime = null;
    let shouldResumeAfterSeek = false;
    let playlistReady = false;
    let isScrubbing = false;
    let activeLoadToken = 0;
    let lastPointerCommitAt = 0;

    const durationCache = new Map();

    for (const preloadPlayer of Object.values(preloadPlayers)) {
        preloadPlayer.preload = "auto";
        preloadPlayer.muted = true;
        preloadPlayer.playsInline = true;
    }

    function isCompositeView() {
        return getCompositeView(activeViewKey) !== null;
    }

    function formatClockTime(totalSeconds) {
        const safeSeconds = Math.max(0, Math.floor(totalSeconds));
        const hours = Math.floor(safeSeconds / 3600);
        const minutes = Math.floor((safeSeconds % 3600) / 60);
        const seconds = safeSeconds % 60;
        if (hours > 0) {
            return `${hours}:${String(minutes).padStart(2, "0")}:${String(seconds).padStart(2, "0")}`;
        }
        return `${minutes}:${String(seconds).padStart(2, "0")}`;
    }

    function getClipStart(index) {
        return playlist.slice(0, index).reduce((sum, clip) => sum + (clip.duration || 0), 0);
    }

    function getTotalDuration() {
        return playlist.reduce((sum, clip) => sum + (clip.duration || 0), 0);
    }

    function syncTimelineUI() {
        const eventTime = pendingEventTime ?? (getClipStart(activeIndex) + player.currentTime);
        const totalDuration = getTotalDuration();

        if (currentTimeNode) {
            currentTimeNode.textContent = formatClockTime(eventTime);
        }
        if (totalTimeNode) {
            totalTimeNode.textContent = totalDuration > 0 ? formatClockTime(totalDuration) : "--:--";
        }
        if (scrubber && totalDuration > 0 && !isScrubbing) {
            scrubber.max = String(totalDuration);
            scrubber.value = String(Math.min(eventTime, totalDuration));
        }
        if (eventMarker) {
            if (eventMarkerTime === null || totalDuration <= 0) {
                eventMarker.hidden = true;
            } else {
                const markerTime = Math.min(Math.max(eventMarkerTime, 0), totalDuration);
                eventMarker.style.left = `${(markerTime / totalDuration) * 100}%`;
                eventMarker.hidden = false;
            }
        }
        if (toggleButton) {
            const isPaused = player.paused;
            const nextLabel = isPaused ? "Play" : "Pause";
            toggleButton.setAttribute("aria-label", nextLabel);
            if (toggleIcon) {
                toggleIcon.src = isPaused ? toggleButton.dataset.playIcon : toggleButton.dataset.pauseIcon;
            }
        }
        if (viewFrame) {
            viewFrame.dataset.activeView = activeViewKey;
        }
        if (compositeGrid) {
            compositeGrid.hidden = !isCompositeView();
        }
        for (const button of viewButtons) {
            const isActive = button.dataset.viewOption === activeViewKey;
            button.classList.toggle("is-active", isActive);
            button.setAttribute("aria-pressed", isActive ? "true" : "false");
        }
    }

    function findClipForEventTime(eventTime) {
        let accumulated = 0;
        for (let index = 0; index < playlist.length; index += 1) {
            const duration = playlist[index].duration || 0;
            if (eventTime <= accumulated + duration || index === playlist.length - 1) {
                return { index, offset: Math.max(0, eventTime - accumulated) };
            }
            accumulated += duration;
        }
        return { index: 0, offset: 0 };
    }

    function seekToEventTime(eventTime) {
        const totalDuration = getTotalDuration();
        if (totalDuration <= 0) {
            return;
        }

        const clampedTime = Math.min(Math.max(eventTime, 0), totalDuration);
        const target = findClipForEventTime(clampedTime);
        const wantsPlayback = !player.paused;
        pendingEventTime = clampedTime;
        loadClip(target.index, { autoplay: false, targetTime: target.offset, secondaryShouldPlay: wantsPlayback });
    }

    function findClipBySegmentKey(cameraKey, segmentKey, fallbackIndex) {
        const cameraPlaylist = allPlaylists[cameraKey];
        if (!Array.isArray(cameraPlaylist) || cameraPlaylist.length === 0) {
            return null;
        }

        const matchedClip = cameraPlaylist.find((clip) => clip.segmentKey === segmentKey);
        if (matchedClip) {
            return matchedClip;
        }

        if (fallbackIndex >= 0 && fallbackIndex < cameraPlaylist.length) {
            return cameraPlaylist[fallbackIndex];
        }

        return cameraPlaylist[0];
    }

    function syncSecondaryPlayers(offset, shouldPlay) {
        const compositeView = getCompositeView(activeViewKey);
        if (!compositeView) {
            for (const secondaryPlayer of Object.values(secondaryPlayers)) {
                if (secondaryPlayer) {
                    secondaryPlayer.pause();
                }
            }
            return;
        }

        const masterClip = playlist[activeIndex];
        if (!masterClip) {
            return;
        }

        for (const [slotKey, secondaryPlayer] of Object.entries(secondaryPlayers)) {
            if (!secondaryPlayer) {
                continue;
            }

            const cameraKey = compositeView.secondarySlots[slotKey];
            if (!cameraKey) {
                secondaryPlayer.pause();
                continue;
            }

            const targetClip = findClipBySegmentKey(cameraKey, masterClip.segmentKey, activeIndex);
            if (!targetClip) {
                secondaryPlayer.pause();
                continue;
            }

            secondaryPlayer.dataset.pendingTime = String(offset);
            secondaryPlayer.dataset.shouldPlay = shouldPlay ? "true" : "false";
            if (!secondaryPlayer.currentSrc || !secondaryPlayer.currentSrc.endsWith(targetClip.url)) {
                secondaryPlayer.src = targetClip.url;
                secondaryPlayer.load();
                if (shouldPlay) {
                    const playPromise = secondaryPlayer.play();
                    if (playPromise && typeof playPromise.catch === "function") {
                        playPromise.catch(() => {});
                    }
                }
                continue;
            }

            if (Math.abs(secondaryPlayer.currentTime - offset) > 0.35) {
                secondaryPlayer.currentTime = offset;
            }
            if (shouldPlay) {
                const playPromise = secondaryPlayer.play();
                if (playPromise && typeof playPromise.catch === "function") {
                    playPromise.catch(() => {});
                }
                continue;
            }
            secondaryPlayer.pause();
        }
    }

    function synchronizeSecondaryDrift() {
        if (!isCompositeView()) {
            return;
        }

        for (const secondaryPlayer of Object.values(secondaryPlayers)) {
            if (!secondaryPlayer || secondaryPlayer.readyState < 2) {
                continue;
            }

            if (Math.abs(secondaryPlayer.currentTime - player.currentTime) > 0.35) {
                secondaryPlayer.currentTime = player.currentTime;
            }
        }
    }

    function clearSecondaryPlayers(resetSource = false) {
        for (const secondaryPlayer of Object.values(secondaryPlayers)) {
            if (!secondaryPlayer) {
                continue;
            }

            secondaryPlayer.pause();
            delete secondaryPlayer.dataset.pendingTime;
            delete secondaryPlayer.dataset.shouldPlay;
            if (!resetSource) {
                continue;
            }
            secondaryPlayer.removeAttribute("src");
            secondaryPlayer.load();
        }
    }

    function getViewTargets(index) {
        const masterClip = playlist[index];
        if (!masterClip) {
            return [];
        }

        const targets = [{ element: player, clip: masterClip }];
        const compositeView = getCompositeView(activeViewKey);
        if (!compositeView) {
            return targets;
        }

        for (const [slotKey, secondaryPlayer] of Object.entries(secondaryPlayers)) {
            if (!secondaryPlayer) {
                continue;
            }

            const cameraKey = compositeView.secondarySlots[slotKey];
            if (!cameraKey) {
                continue;
            }

            const clip = findClipBySegmentKey(cameraKey, masterClip.segmentKey, index);
            if (clip) {
                targets.push({ element: secondaryPlayer, clip });
            }
        }
        return targets;
    }

    function applyPendingPlayback(videoElement) {
        const loadToken = Number.parseInt(videoElement.dataset.loadToken || "0", 10);
        if (loadToken !== activeLoadToken) {
            return;
        }

        const pendingTime = Number.parseFloat(videoElement.dataset.pendingTime || "0");
        if (!Number.isNaN(pendingTime) && Math.abs(videoElement.currentTime - pendingTime) > 0.1) {
            videoElement.currentTime = pendingTime;
        }

        if (videoElement === player) {
            pendingEventTime = null;
            syncTimelineUI();
        }

        if (videoElement.dataset.shouldPlay === "true") {
            const playPromise = videoElement.play();
            if (playPromise && typeof playPromise.catch === "function") {
                playPromise.catch(() => {});
            }
            return;
        }
        videoElement.pause();
    }

    function ensureVideoReady(videoElement, url) {
        if (!videoElement.currentSrc || !videoElement.currentSrc.endsWith(url)) {
            videoElement.src = url;
        }
        videoElement.load();

        if (videoElement.readyState >= 1) {
            applyPendingPlayback(videoElement);
        }
    }

    function loadViewAtIndex(index, targetTime, shouldPlay) {
        const targets = getViewTargets(index);
        if (targets.length === 0) {
            return;
        }

        const loadToken = ++activeLoadToken;
        activeIndex = index;
        syncTimelineUI();

        for (const { element, clip } of targets) {
            element.dataset.loadToken = String(loadToken);
            element.dataset.pendingTime = String(targetTime);
            element.dataset.shouldPlay = shouldPlay ? "true" : "false";
            ensureVideoReady(element, clip.url);
        }

        preloadNextSegment(index + 1);
    }

    function preloadNextSegment(nextIndex) {
        if (nextIndex < 0 || nextIndex >= playlist.length) {
            return;
        }

        const targets = getViewTargets(nextIndex);
        for (const { element, clip } of targets) {
            const preloaderKey = element === player ? "master" : element.dataset.secondarySlot;
            const preloader = preloaderKey ? preloadPlayers[preloaderKey] : null;
            if (!preloader) {
                continue;
            }
            if (!preloader.currentSrc || !preloader.currentSrc.endsWith(clip.url)) {
                preloader.src = clip.url;
            }
            preloader.load();
        }
    }

    function loadClip(index, options = {}) {
        const { autoplay = false, targetTime = 0, secondaryShouldPlay = autoplay } = options;
        const clip = playlist[index];
        if (!clip) {
            return;
        }

        loadViewAtIndex(index, targetTime, secondaryShouldPlay);
    }

    player.addEventListener("ended", () => {
        if (activeIndex >= playlist.length - 1) {
            syncTimelineUI();
            return;
        }
        loadClip(activeIndex + 1, { autoplay: true, targetTime: 0, secondaryShouldPlay: true });
    });

    player.addEventListener("loadedmetadata", () => {
        applyPendingPlayback(player);
        syncTimelineUI();
    });

    player.addEventListener("timeupdate", () => {
        synchronizeSecondaryDrift();
        syncTimelineUI();
    });
    player.addEventListener("play", () => {
        syncSecondaryPlayers(player.currentTime, true);
        syncTimelineUI();
    });
    player.addEventListener("pause", () => {
        syncSecondaryPlayers(player.currentTime, false);
        syncTimelineUI();
    });

    for (const secondaryPlayer of Object.values(secondaryPlayers)) {
        if (!secondaryPlayer) {
            continue;
        }

        secondaryPlayer.addEventListener("loadedmetadata", () => {
            applyPendingPlayback(secondaryPlayer);
        });
    }

    if (toggleButton) {
        toggleButton.addEventListener("click", () => {
            if (player.paused) {
                const playPromise = player.play();
                if (playPromise && typeof playPromise.catch === "function") {
                    playPromise.catch(() => {});
                }
                return;
            }
            player.pause();
        });
    }

    if (scrubber) {
        const previewScrubTime = () => {
            if (!playlistReady) {
                return;
            }
            const nextTime = Number.parseFloat(scrubber.value);
            if (Number.isNaN(nextTime)) {
                return;
            }
            pendingEventTime = nextTime;
            syncTimelineUI();
        };

        const commitScrubTime = () => {
            if (!playlistReady) {
                return;
            }
            const nextTime = Number.parseFloat(scrubber.value);
            if (Number.isNaN(nextTime)) {
                return;
            }
            isScrubbing = false;
            seekToEventTime(nextTime);
        };

        scrubber.addEventListener("pointerdown", () => {
            isScrubbing = true;
        });

        scrubber.addEventListener("input", previewScrubTime);
        scrubber.addEventListener("change", () => {
            if (isScrubbing) {
                return;
            }
            if (performance.now() - lastPointerCommitAt < 250) {
                return;
            }
            commitScrubTime();
        });
        scrubber.addEventListener("pointerup", () => {
            lastPointerCommitAt = performance.now();
            commitScrubTime();
        });
        scrubber.addEventListener("keyup", (event) => {
            if (["ArrowLeft", "ArrowRight", "Home", "End", "PageUp", "PageDown"].includes(event.key)) {
                commitScrubTime();
            }
        });
        scrubber.addEventListener("blur", () => {
            if (!isScrubbing) {
                return;
            }
            commitScrubTime();
        });
    }

    function populatePlaylistDurations(playlistToPopulate) {
        return populateClipDurations(playlistToPopulate, player, durationCache, syncTimelineUI).catch(() => {
            playlistToPopulate.forEach((clip) => {
                clip.duration = Number.isFinite(clip.duration) ? clip.duration : 0;
            });
            return playlistToPopulate;
        });
    }

    function switchView(nextViewKey) {
        const nextCameraKey = getMasterCameraKey(nextViewKey);
        if (!allPlaylists[nextCameraKey] || nextViewKey === activeViewKey) {
            return;
        }

        const currentEventTime = pendingEventTime ?? (getClipStart(activeIndex) + player.currentTime);
        const wantsPlayback = !player.paused;
        if (isCompositeView() && !getCompositeView(nextViewKey)) {
            clearSecondaryPlayers(true);
        }
        activeViewKey = nextViewKey;
        activeCameraKey = nextCameraKey;
        playlist = allPlaylists[activeCameraKey];
        activeIndex = 0;
        pendingSeekTime = null;
        pendingEventTime = currentEventTime;
        shouldResumeAfterSeek = false;
        playlistReady = false;
        syncTimelineUI();

        populatePlaylistDurations(playlist).then(() => {
            playlistReady = true;
            pendingEventTime = currentEventTime;
            if (wantsPlayback) {
                shouldResumeAfterSeek = true;
            }
            seekToEventTime(currentEventTime);
        });
    }

    for (const button of viewButtons) {
        button.addEventListener("click", () => {
            const nextViewKey = button.dataset.viewOption;
            if (!nextViewKey) {
                return;
            }
            switchView(nextViewKey);
        });
    }

    populatePlaylistDurations(playlist).then(() => {
        playlistReady = true;
        syncTimelineUI();
    });

    syncTimelineUI();
}

async function populateClipDurations(playlist, player, durationCache, onDurationUpdate) {
    if (playlist.length === 0) {
        return playlist;
    }

    const activeUrl = playlist[0].url;
    const standardDuration = activeUrl ? await getStandardDuration(player, activeUrl, durationCache) : 0;

    playlist.forEach((clip) => {
        clip.duration = standardDuration;
    });

    if (playlist.length > 1) {
        const lastIndex = playlist.length - 1;
        loadClipDuration(playlist[lastIndex].url, durationCache).then((lastDuration) => {
            playlist[lastIndex].duration = lastDuration || standardDuration;
            if (typeof onDurationUpdate === "function") {
                onDurationUpdate();
            }
        });
    }

    return playlist;
}

async function getStandardDuration(player, expectedUrl, durationCache) {
    const cached = durationCache.get(expectedUrl);
    if (cached !== undefined) {
        return cached;
    }

    const cachedDuration = Array.from(durationCache.values()).find((duration) => duration > 0);
    if (cachedDuration !== undefined) {
        durationCache.set(expectedUrl, cachedDuration);
        return cachedDuration;
    }

    if (Number.isFinite(player.duration) && player.duration > 0) {
        durationCache.set(expectedUrl, player.duration);
        return player.duration;
    }

    return getPlayerMetadataDuration(player, expectedUrl, durationCache);
}

function getPlayerMetadataDuration(player, expectedUrl, durationCache) {
    const cached = durationCache.get(expectedUrl);
    if (cached !== undefined) {
        return Promise.resolve(cached);
    }

    return new Promise((resolve) => {
        const finish = (duration) => {
            cleanup();
            const safeDuration = Number.isFinite(duration) ? duration : 0;
            durationCache.set(expectedUrl, safeDuration);
            resolve(safeDuration);
        };

        const onLoadedMetadata = () => {
            if (!player.currentSrc || !player.currentSrc.includes(expectedUrl)) {
                return;
            }
            finish(player.duration);
        };

        const onError = () => finish(0);
        const timeoutId = window.setTimeout(() => finish(player.duration), 4000);

        const cleanup = () => {
            window.clearTimeout(timeoutId);
            player.removeEventListener("loadedmetadata", onLoadedMetadata);
            player.removeEventListener("error", onError);
        };

        if (Number.isFinite(player.duration) && player.duration > 0) {
            finish(player.duration);
            return;
        }

        player.addEventListener("loadedmetadata", onLoadedMetadata);
        player.addEventListener("error", onError);
    });
}

function loadClipDuration(url, durationCache) {
    const cached = durationCache.get(url);
    if (cached !== undefined) {
        return Promise.resolve(cached);
    }

    return new Promise((resolve) => {
        const probe = document.createElement("video");
        probe.preload = "metadata";
        probe.src = url;
        const timeoutId = window.setTimeout(() => {
            cleanup();
            durationCache.set(url, 0);
            resolve(0);
        }, 4000);

        const cleanup = () => {
            window.clearTimeout(timeoutId);
            probe.removeAttribute("src");
            probe.load();
        };

        probe.addEventListener(
            "loadedmetadata",
            () => {
                const duration = Number.isFinite(probe.duration) ? probe.duration : 0;
                cleanup();
                durationCache.set(url, duration);
                resolve(duration);
            },
            { once: true }
        );

        probe.addEventListener(
            "error",
            () => {
                cleanup();
                durationCache.set(url, 0);
                resolve(0);
            },
            { once: true }
        );
    });
}

if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", initPage, { once: true });
} else {
    initPage();
}
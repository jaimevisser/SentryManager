export function createEventPlayerPlaybackController({
    windowObject,
    player,
    viewFrame,
    secondaryPlayers,
    preloadPlayers,
    allPlaylists,
    hasCameraPlaylist,
    getFirstAvailableCameraKey,
    getSecondaryCameraKeyMap,
    isCompositeView,
    syncTimelineUI,
    scheduleStageSafeZoneUpdate,
    maybeApplyPlaybackCameraMarker,
    maybeApplyCurrentPlaybackViewMarker,
    syncPlaybackMarkerCheckpoint,
    getPlaybackMarkerIdAtOrBefore,
    decodeTelemetryBuffer,
    populateClipDurations,
    clipHasTelemetry,
    getActiveLayout,
    setActiveLayout,
    getActiveCameraKey,
    setActiveCameraKey,
    getPlaylist,
    setPlaylist,
    getActiveIndex,
    setActiveIndex,
    getPendingEventTime,
    setPendingEventTime,
    isPlaylistReady,
    setPlaylistReady,
    durationCache,
    telemetryCache,
}) {
    let activeLoadToken = 0;

    function getClipStart(index) {
        return getPlaylist().slice(0, index).reduce((sum, clip) => sum + (clip.duration || 0), 0);
    }

    function getTotalDuration() {
        return getPlaylist().reduce((sum, clip) => sum + (clip.duration || 0), 0);
    }

    function getCurrentEventTime() {
        return getPendingEventTime() ?? (getClipStart(getActiveIndex()) + player.currentTime);
    }

    function getActualPlaybackEventTime() {
        return getClipStart(getActiveIndex()) + player.currentTime;
    }

    function findClipForEventTime(eventTime) {
        const playlist = getPlaylist();
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

    function seekToEventTime(eventTime, options = {}) {
        const totalDuration = getTotalDuration();
        if (totalDuration <= 0) {
            return;
        }

        const { autoplay = !player.paused } = options;
        const clampedTime = Math.min(Math.max(eventTime, 0), totalDuration);
        const target = findClipForEventTime(clampedTime);
        setPendingEventTime(clampedTime);
        loadClip(target.index, { autoplay, targetTime: target.offset, secondaryShouldPlay: autoplay });
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

    function findClipIndexBySegmentKey(cameraKey, segmentKey, fallbackIndex) {
        const cameraPlaylist = allPlaylists[cameraKey];
        if (!Array.isArray(cameraPlaylist) || cameraPlaylist.length === 0) {
            return -1;
        }

        const matchedIndex = cameraPlaylist.findIndex((clip) => clip.segmentKey === segmentKey);
        if (matchedIndex >= 0) {
            return matchedIndex;
        }

        if (fallbackIndex >= 0 && fallbackIndex < cameraPlaylist.length) {
            return fallbackIndex;
        }

        return 0;
    }

    function syncSecondaryPlayers(offset, shouldPlay) {
        const secondaryCameraKeys = getSecondaryCameraKeyMap();
        if (!isCompositeView()) {
            for (const secondaryPlayer of Object.values(secondaryPlayers)) {
                if (secondaryPlayer) {
                    secondaryPlayer.pause();
                    if (secondaryPlayer.parentElement) {
                        secondaryPlayer.parentElement.hidden = true;
                    }
                }
            }
            return;
        }

        const playlist = getPlaylist();
        const masterClip = playlist[getActiveIndex()];
        if (!masterClip) {
            return;
        }

        for (const [slotKey, secondaryPlayer] of Object.entries(secondaryPlayers)) {
            if (!secondaryPlayer) {
                continue;
            }

            const secondaryShell = secondaryPlayer.parentElement;
            const cameraKey = secondaryCameraKeys[slotKey];
            if (!cameraKey || !hasCameraPlaylist(cameraKey)) {
                secondaryPlayer.pause();
                if (secondaryShell) {
                    secondaryShell.hidden = true;
                }
                continue;
            }

            if (secondaryShell) {
                secondaryShell.hidden = false;
            }

            const targetClip = findClipBySegmentKey(cameraKey, masterClip.segmentKey, getActiveIndex());
            if (!targetClip) {
                secondaryPlayer.pause();
                if (secondaryShell) {
                    secondaryShell.hidden = true;
                }
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
            if (secondaryPlayer.parentElement) {
                secondaryPlayer.parentElement.hidden = false;
            }
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
        const playlist = getPlaylist();
        const masterClip = playlist[index];
        if (!masterClip) {
            return [];
        }

        const targets = [{ element: player, clip: masterClip }];
        const secondaryCameraKeys = getSecondaryCameraKeyMap();
        if (!isCompositeView()) {
            return targets;
        }

        for (const [slotKey, secondaryPlayer] of Object.entries(secondaryPlayers)) {
            if (!secondaryPlayer) {
                continue;
            }

            const cameraKey = secondaryCameraKeys[slotKey];
            if (!cameraKey || !hasCameraPlaylist(cameraKey)) {
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
            setPendingEventTime(null);
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
        setActiveIndex(index);
        syncTimelineUI();

        for (const { element, clip } of targets) {
            element.dataset.loadToken = String(loadToken);
            element.dataset.pendingTime = String(targetTime);
            element.dataset.shouldPlay = shouldPlay ? "true" : "false";
            ensureVideoReady(element, clip.url);
        }

        syncSecondaryPlayers(targetTime, shouldPlay);
        preloadNextSegment(index + 1);
    }

    function preloadNextSegment(nextIndex) {
        const playlist = getPlaylist();
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
        const playlist = getPlaylist();
        const clip = playlist[index];
        if (!clip) {
            return;
        }

        ensureTelemetryLoaded(clip).then(() => {
            syncTimelineUI();
        });
        loadViewAtIndex(index, targetTime, secondaryShouldPlay);
    }

    function populatePlaylistDurationsFor(playlistToPopulate) {
        return populateClipDurations(playlistToPopulate, player, durationCache, syncTimelineUI).catch(() => {
            playlistToPopulate.forEach((clip) => {
                clip.duration = Number.isFinite(clip.duration) ? clip.duration : 0;
            });
            return playlistToPopulate;
        });
    }

    function preloadTelemetryForPlaylist(playlistToPopulate) {
        playlistToPopulate.forEach((clip) => {
            ensureTelemetryLoaded(clip).then(() => {
                if (playlistToPopulate === getPlaylist()) {
                    syncTimelineUI();
                }
            });
        });
    }

    function ensureTelemetryLoaded(clip) {
        if (!clip?.telemetryUrl || !clipHasTelemetry(clip)) {
            if (clip) {
                clip.telemetry = null;
                clip.telemetryLoaded = true;
            }
            return Promise.resolve(null);
        }
        if (clip.telemetryLoaded) {
            return Promise.resolve(clip.telemetry);
        }
        if (clip.telemetryPromise) {
            return clip.telemetryPromise;
        }

        const cachedPromise = telemetryCache.get(clip.telemetryUrl);
        if (cachedPromise) {
            clip.telemetryPromise = cachedPromise.then((telemetry) => {
                clip.telemetry = telemetry;
                clip.telemetryLoaded = true;
                return telemetry;
            });
            return clip.telemetryPromise;
        }

        const telemetryPromise = fetch(clip.telemetryUrl)
            .then((response) => {
                if (!response.ok) {
                    throw new Error(`Failed to load telemetry: ${response.status}`);
                }
                return response.arrayBuffer();
            })
            .then(decodeTelemetryBuffer)
            .catch(() => null);

        telemetryCache.set(clip.telemetryUrl, telemetryPromise);
        clip.telemetryPromise = telemetryPromise.then((telemetry) => {
            clip.telemetry = telemetry;
            clip.telemetryLoaded = true;
            return telemetry;
        });
        return clip.telemetryPromise;
    }

    function applyViewSelection(nextLayout, nextCameraKey, options = {}) {
        const normalizedLayout = ["single", "double", "triple"].includes(nextLayout) ? nextLayout : getActiveLayout();
        const normalizedCameraKey = getFirstAvailableCameraKey(nextCameraKey);
        if (!normalizedCameraKey || !hasCameraPlaylist(normalizedCameraKey)) {
            return false;
        }

        const currentEventTime = typeof options.eventTime === "number" && Number.isFinite(options.eventTime)
            ? options.eventTime
            : getCurrentEventTime();
        const autoplay = typeof options.autoplay === "boolean" ? options.autoplay : !player.paused;
        const cameraChanged = normalizedCameraKey !== getActiveCameraKey();
        const layoutChanged = normalizedLayout !== getActiveLayout();
        if (!cameraChanged && !layoutChanged) {
            return false;
        }

        setActiveLayout(normalizedLayout);
        setActiveCameraKey(normalizedCameraKey);
        setPendingEventTime(currentEventTime);

        if (cameraChanged) {
            const nextPlaylist = allPlaylists[normalizedCameraKey];
            setPlaylist(nextPlaylist);
            setActiveIndex(0);
            setPlaylistReady(false);
            syncTimelineUI();

            populatePlaylistDurationsFor(nextPlaylist).then(() => {
                setPlaylistReady(true);
                preloadTelemetryForPlaylist(nextPlaylist);
                setPendingEventTime(currentEventTime);
                seekToEventTime(currentEventTime, { autoplay });
            });
            return true;
        }

        syncTimelineUI();
        if (!isPlaylistReady()) {
            return true;
        }
        seekToEventTime(currentEventTime, { autoplay });
        return true;
    }

    function switchCamera(nextCameraKey) {
        applyViewSelection(getActiveLayout(), nextCameraKey);
    }

    function switchLayout(nextLayout) {
        applyViewSelection(nextLayout, getActiveCameraKey());
    }

    function bindMediaEvents() {
        player.addEventListener("ended", () => {
            const playlist = getPlaylist();
            if (getActiveIndex() >= playlist.length - 1) {
                syncTimelineUI();
                return;
            }
            loadClip(getActiveIndex() + 1, { autoplay: true, targetTime: 0, secondaryShouldPlay: true });
        });

        player.addEventListener("loadedmetadata", () => {
            applyPendingPlayback(player);
            syncPlaybackMarkerCheckpoint(getCurrentEventTime());
            syncTimelineUI();
            scheduleStageSafeZoneUpdate();
        });

        player.addEventListener("timeupdate", () => {
            const eventTime = getCurrentEventTime();
            if (maybeApplyPlaybackCameraMarker(eventTime)) {
                return;
            }
            synchronizeSecondaryDrift();
            syncTimelineUI();
        });

        player.addEventListener("play", () => {
            const eventTime = getCurrentEventTime();
            if (maybeApplyCurrentPlaybackViewMarker(eventTime)) {
                return;
            }
            syncPlaybackMarkerCheckpoint(getCurrentEventTime());
            syncSecondaryPlayers(player.currentTime, true);
            syncTimelineUI();
        });

        player.addEventListener("pause", () => {
            syncPlaybackMarkerCheckpoint(getCurrentEventTime());
            syncSecondaryPlayers(player.currentTime, false);
            syncTimelineUI();
        });

        for (const secondaryPlayer of Object.values(secondaryPlayers)) {
            if (!secondaryPlayer) {
                continue;
            }

            secondaryPlayer.addEventListener("loadedmetadata", () => {
                applyPendingPlayback(secondaryPlayer);
                scheduleStageSafeZoneUpdate();
            });
        }

        if (typeof ResizeObserver === "function" && viewFrame) {
            const stageResizeObserver = new ResizeObserver(() => {
                scheduleStageSafeZoneUpdate();
            });
            stageResizeObserver.observe(viewFrame);
        } else {
            windowObject.addEventListener("resize", scheduleStageSafeZoneUpdate);
        }
    }

    return {
        getClipStart,
        getTotalDuration,
        getCurrentEventTime,
        getActualPlaybackEventTime,
        findClipForEventTime,
        seekToEventTime,
        findClipBySegmentKey,
        findClipIndexBySegmentKey,
        syncSecondaryPlayers,
        synchronizeSecondaryDrift,
        clearSecondaryPlayers,
        loadClip,
        populatePlaylistDurations: populatePlaylistDurationsFor,
        preloadTelemetryForPlaylist,
        ensureTelemetryLoaded,
        applyViewSelection,
        switchCamera,
        switchLayout,
        bindMediaEvents,
    };
}
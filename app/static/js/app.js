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

    let playlist;
    try {
        playlist = JSON.parse(playlistNode.textContent || "[]");
    } catch {
        return;
    }

    if (!Array.isArray(playlist) || playlist.length === 0) {
        return;
    }

    const clipLabel = document.querySelector("[data-player-clip-label]");
    const fileName = document.querySelector("[data-player-file-name]");
    const progress = document.querySelector("[data-player-progress]");
    const currentTimeNode = document.querySelector("[data-player-current-time]");
    const totalTimeNode = document.querySelector("[data-player-total-time]");
    const scrubber = document.querySelector("[data-player-scrub]");
    const toggleButton = document.querySelector("[data-player-toggle]");
    let activeIndex = 0;
    let pendingSeekTime = null;
    let pendingEventTime = null;
    let shouldResumeAfterSeek = false;
    let playlistReady = false;
    let isScrubbing = false;

    const durationsPromise = populateClipDurations(playlist, player).catch(() => {
        playlist.forEach((clip) => {
            clip.duration = Number.isFinite(clip.duration) ? clip.duration : 0;
        });
        return playlist;
    });

    function syncClipMeta(index) {
        const clip = playlist[index];
        if (!clip) {
            return;
        }
        if (clipLabel) {
            clipLabel.textContent = clip.segmentLabel;
        }
        if (fileName) {
            fileName.textContent = clip.fileName;
        }
        if (progress) {
            progress.textContent = `Clip ${index + 1} of ${playlist.length}`;
        }
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
        const clip = playlist[activeIndex];
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
        if (toggleButton) {
            toggleButton.textContent = player.paused ? "Play" : "Pause";
        }
        if (progress && clip) {
            progress.textContent = `Clip ${activeIndex + 1} of ${playlist.length} · ${clip.segmentLabel}`;
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

        if (target.index === activeIndex) {
            player.currentTime = target.offset;
            pendingEventTime = null;
            syncTimelineUI();
            return;
        }

        pendingSeekTime = target.offset;
        shouldResumeAfterSeek = wantsPlayback;
        loadClip(target.index, false);
    }

    function loadClip(index, autoplay = false) {
        const clip = playlist[index];
        if (!clip) {
            return;
        }

        activeIndex = index;
        syncClipMeta(index);
        if (player.currentSrc !== clip.url) {
            player.src = clip.url;
        }
        player.load();
        syncTimelineUI();

        if (autoplay) {
            const playPromise = player.play();
            if (playPromise && typeof playPromise.catch === "function") {
                playPromise.catch(() => {});
            }
        }
    }

    player.addEventListener("ended", () => {
        if (activeIndex >= playlist.length - 1) {
            syncTimelineUI();
            return;
        }
        loadClip(activeIndex + 1, true);
    });

    player.addEventListener("loadedmetadata", () => {
        if (pendingSeekTime !== null) {
            player.currentTime = pendingSeekTime;
            pendingSeekTime = null;
        }
        if (shouldResumeAfterSeek) {
            shouldResumeAfterSeek = false;
            const playPromise = player.play();
            if (playPromise && typeof playPromise.catch === "function") {
                playPromise.catch(() => {});
            }
        }
        pendingEventTime = null;
        syncTimelineUI();
    });

    player.addEventListener("timeupdate", syncTimelineUI);
    player.addEventListener("play", syncTimelineUI);
    player.addEventListener("pause", syncTimelineUI);

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
        scrubber.addEventListener("change", commitScrubTime);
        scrubber.addEventListener("pointerup", commitScrubTime);
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

    durationsPromise.then(() => {
        playlistReady = true;
        syncTimelineUI();
    });

    syncClipMeta(activeIndex);
    syncTimelineUI();
}

async function populateClipDurations(playlist, player) {
    if (playlist.length === 0) {
        return playlist;
    }

    const activeUrl = playlist[0].url;
    const standardDuration = activeUrl ? await getPlayerMetadataDuration(player, activeUrl) : 0;

    playlist.forEach((clip) => {
        clip.duration = standardDuration;
    });

    if (playlist.length > 1) {
        const lastIndex = playlist.length - 1;
        const lastDuration = await loadClipDuration(playlist[lastIndex].url);
        playlist[lastIndex].duration = lastDuration || standardDuration;
    }

    return playlist;
}

function getPlayerMetadataDuration(player, expectedUrl) {
    return new Promise((resolve) => {
        const finish = (duration) => {
            cleanup();
            resolve(Number.isFinite(duration) ? duration : 0);
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

function loadClipDuration(url) {
    return new Promise((resolve) => {
        const probe = document.createElement("video");
        probe.preload = "metadata";
        probe.src = url;
        const timeoutId = window.setTimeout(() => {
            cleanup();
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
                resolve(duration);
            },
            { once: true }
        );

        probe.addEventListener(
            "error",
            () => {
                cleanup();
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
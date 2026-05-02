export function createEventPlayerExportController({
    windowObject,
    playerEditsSaveUrl,
    playerRenderUrl,
    playerDownloadUrl,
    initialRenderJob,
    initialLatestRenderMetadata,
    normalizeExportFormat,
    isRenderJobActive,
    describeRenderJobStatus,
    renderStatusNode,
    renderActionButton,
    renderActionIcon,
    downloadActionButton,
    getCanRender,
    getPlayerEditsPayload,
    onPlayerEditsChanged,
}) {
    let activeExportFormat = "4k";
    let activeRenderJob = initialRenderJob;
    let renderPollTimer = null;
    let renderInFlight = isRenderJobActive(activeRenderJob);
    let latestRenderMetadata = initialLatestRenderMetadata;
    let renderStatusMessage = activeRenderJob
        ? getRenderJobStatusMessage(activeRenderJob)
        : (latestRenderMetadata ? "Ready" : "");
    let playerEditsSaveTimer = null;
    let playerEditsSaveInFlight = false;
    let pendingPlayerEditsSnapshot = null;
    let persistedPlayerEditsSignature = null;

    function getRenderJobStatusMessage(job) {
        return describeRenderJobStatus(job, Boolean(latestRenderMetadata));
    }

    function setRenderStatus(message) {
        renderStatusMessage = typeof message === "string" ? message : "";
        if (!renderStatusNode) {
            return;
        }
        if (!renderStatusMessage) {
            renderStatusNode.hidden = true;
            renderStatusNode.textContent = "";
            return;
        }
        renderStatusNode.hidden = false;
        renderStatusNode.textContent = renderStatusMessage;
    }

    function syncRenderUI() {
        if (renderActionButton) {
            renderActionButton.disabled = renderInFlight || !playerRenderUrl || !getCanRender();
            renderActionButton.setAttribute("aria-label", renderInFlight ? "Rendering video" : "Export video");
            renderActionButton.setAttribute("title", renderInFlight ? "Rendering video" : "Export video");
        }
        if (renderActionIcon && renderActionButton?.dataset.exportIcon && renderActionButton?.dataset.renderingIcon) {
            renderActionIcon.src = renderInFlight ? renderActionButton.dataset.renderingIcon : renderActionButton.dataset.exportIcon;
        }
        if (downloadActionButton) {
            downloadActionButton.disabled = renderInFlight || !playerDownloadUrl || !latestRenderMetadata;
        }
        setRenderStatus(renderStatusMessage);
    }

    function clearRenderPollTimer() {
        if (renderPollTimer === null) {
            return;
        }
        windowObject.clearTimeout(renderPollTimer);
        renderPollTimer = null;
    }

    function scheduleRenderJobPoll(delayMs = 1000) {
        clearRenderPollTimer();
        renderPollTimer = windowObject.setTimeout(() => {
            renderPollTimer = null;
            pollRenderJobStatus().catch(() => {});
        }, delayMs);
    }

    function updateRenderTracking(nextJob) {
        activeRenderJob = nextJob && typeof nextJob === "object" ? nextJob : null;
        renderInFlight = isRenderJobActive(activeRenderJob);
        if (activeRenderJob?.render && typeof activeRenderJob.render === "object") {
            latestRenderMetadata = activeRenderJob.render;
        }
        renderStatusMessage = getRenderJobStatusMessage(activeRenderJob);
        syncRenderUI();
    }

    async function pollRenderJobStatus() {
        if (!activeRenderJob || typeof activeRenderJob.statusUrl !== "string") {
            updateRenderTracking(null);
            return;
        }

        try {
            const response = await fetch(activeRenderJob.statusUrl, {
                cache: "no-store",
            });
            const responsePayload = await response.json().catch(() => null);
            if (!response.ok) {
                throw new Error(typeof responsePayload?.error === "string" ? responsePayload.error : "Could not fetch render status.");
            }

            const job = responsePayload?.job && typeof responsePayload.job === "object"
                ? responsePayload.job
                : null;
            if (!job) {
                throw new Error("Could not fetch render status.");
            }

            if (job.status === "succeeded") {
                if (job.render && typeof job.render === "object") {
                    latestRenderMetadata = job.render;
                }
                updateRenderTracking(null);
                setRenderStatus("Ready");
                syncRenderUI();
                const downloadUrl = typeof job.downloadUrl === "string" ? job.downloadUrl : playerDownloadUrl;
                if (downloadUrl) {
                    windowObject.location.assign(downloadUrl);
                }
                return;
            }

            if (job.status === "failed") {
                updateRenderTracking(null);
                setRenderStatus(getRenderJobStatusMessage(job));
                syncRenderUI();
                return;
            }

            updateRenderTracking(job);
            if (isRenderJobActive(job)) {
                scheduleRenderJobPoll();
            }
        } catch (error) {
            const message = error instanceof Error ? error.message : "Could not fetch render status.";
            setRenderStatus(message);
            syncRenderUI();
            if (isRenderJobActive(activeRenderJob)) {
                scheduleRenderJobPoll(1500);
            }
        }
    }

    async function handleRenderAction() {
        if (renderInFlight || !playerRenderUrl) {
            return;
        }

        clearRenderPollTimer();
        updateRenderTracking({
            status: "running",
            statusUrl: null,
            progressMessage: "Queueing...",
        });

        try {
            const response = await fetch(playerRenderUrl, {
                method: "POST",
                headers: {
                    "Content-Type": "application/json",
                },
                body: JSON.stringify({
                    outputProfile: activeExportFormat,
                    playerEdits: getPlayerEditsPayload(),
                }),
            });
            const responsePayload = await response.json().catch(() => null);
            if (!response.ok) {
                throw new Error(typeof responsePayload?.error === "string" ? responsePayload.error : "Could not render export.");
            }

            const job = responsePayload?.job && typeof responsePayload.job === "object"
                ? responsePayload.job
                : null;
            if (!job) {
                throw new Error("Could not queue render export.");
            }

            updateRenderTracking(job);
            if (isRenderJobActive(job)) {
                scheduleRenderJobPoll(250);
                return;
            }

            if (job.render && typeof job.render === "object") {
                latestRenderMetadata = job.render;
            }
            const downloadUrl = typeof job.downloadUrl === "string" ? job.downloadUrl : playerDownloadUrl;
            setRenderStatus("Ready");
            syncRenderUI();
            if (downloadUrl) {
                windowObject.location.assign(downloadUrl);
            }
        } catch (error) {
            updateRenderTracking(null);
            setRenderStatus(error instanceof Error ? error.message : "Could not render export.");
            syncRenderUI();
            console.error(error instanceof Error ? error.message : "Could not render export.");
        }
    }

    function handleDownloadAction() {
        if (!playerDownloadUrl || !latestRenderMetadata) {
            return;
        }
        windowObject.location.assign(playerDownloadUrl);
    }

    function getPlayerEditsSignature(payload) {
        return JSON.stringify(payload);
    }

    async function flushPlayerEditsPersistence() {
        if (!playerEditsSaveUrl || playerEditsSaveInFlight || !pendingPlayerEditsSnapshot) {
            return;
        }

        const snapshot = pendingPlayerEditsSnapshot;
        pendingPlayerEditsSnapshot = null;
        playerEditsSaveInFlight = true;

        try {
            const response = await fetch(playerEditsSaveUrl, {
                method: "POST",
                headers: {
                    "Content-Type": "application/json",
                },
                body: JSON.stringify(snapshot.payload),
            });
            const responsePayload = await response.json().catch(() => null);
            if (!response.ok) {
                throw new Error(typeof responsePayload?.error === "string" ? responsePayload.error : "Could not save player edits.");
            }
            persistedPlayerEditsSignature = snapshot.signature;
        } catch (error) {
            pendingPlayerEditsSnapshot = snapshot;
            console.error(error instanceof Error ? error.message : "Could not save player edits.");
        } finally {
            playerEditsSaveInFlight = false;
            if (pendingPlayerEditsSnapshot && pendingPlayerEditsSnapshot.signature !== snapshot.signature) {
                windowObject.setTimeout(() => {
                    flushPlayerEditsPersistence().catch(() => {});
                }, 0);
            }
        }
    }

    function schedulePlayerEditsPersistence() {
        if (!playerEditsSaveUrl) {
            return;
        }

        const payload = getPlayerEditsPayload();
        const signature = getPlayerEditsSignature(payload);
        if (signature === persistedPlayerEditsSignature && pendingPlayerEditsSnapshot === null && !playerEditsSaveInFlight) {
            return;
        }

        pendingPlayerEditsSnapshot = { payload, signature };
        if (playerEditsSaveTimer !== null) {
            windowObject.clearTimeout(playerEditsSaveTimer);
        }
        playerEditsSaveTimer = windowObject.setTimeout(() => {
            playerEditsSaveTimer = null;
            flushPlayerEditsPersistence().catch(() => {});
        }, 250);
    }

    function setExportFormat(nextFormat) {
        const normalizedFormat = normalizeExportFormat(nextFormat);
        if (normalizedFormat === activeExportFormat) {
            return false;
        }
        activeExportFormat = normalizedFormat;
        onPlayerEditsChanged();
        return true;
    }

    function toggleExportFormat() {
        return setExportFormat(activeExportFormat === "4k" ? "hd" : "4k");
    }

    function hydrateSavedExportFormat(rawSavedPlayerEdits) {
        if (typeof rawSavedPlayerEdits?.exportFormat === "string") {
            activeExportFormat = normalizeExportFormat(rawSavedPlayerEdits.exportFormat);
        }
    }

    function markCurrentPlayerEditsPersisted() {
        persistedPlayerEditsSignature = getPlayerEditsSignature(getPlayerEditsPayload());
    }

    function startRenderPollingIfNeeded() {
        if (isRenderJobActive(activeRenderJob)) {
            scheduleRenderJobPoll(250);
        }
    }

    return {
        getActiveExportFormat: () => activeExportFormat,
        setExportFormat,
        toggleExportFormat,
        syncRenderUI,
        handleRenderAction,
        handleDownloadAction,
        schedulePlayerEditsPersistence,
        hydrateSavedExportFormat,
        markCurrentPlayerEditsPersisted,
        startRenderPollingIfNeeded,
    };
}
export const CAMERA_LAYOUT_SEQUENCE = ["front", "right_pillar", "right_repeater", "back", "left_repeater", "left_pillar"];
export const SPEED_PRESENT_MASK = 1 << 3;
export const STEERING_ANGLE_PRESENT_MASK = 1 << 5;
export const BLINKER_LEFT_PRESENT_MASK = 1 << 6;
export const BLINKER_RIGHT_PRESENT_MASK = 1 << 7;
export const BRAKE_PRESENT_MASK = 1 << 8;
export const AUTOPILOT_PRESENT_MASK = 1 << 9;
export const LATITUDE_PRESENT_MASK = 1 << 10;
export const LONGITUDE_PRESENT_MASK = 1 << 11;
export const HEADING_PRESENT_MASK = 1 << 12;
export const AUTOPILOT_NONE_STATE = 0;
export const BLINKER_LEFT_FLAG_MASK = 0x01;
export const BLINKER_RIGHT_FLAG_MASK = 0x02;
export const BRAKE_FLAG_MASK = 0x04;

const TELEMETRY_MAGIC = "SEI1";
const TELEMETRY_FORMAT_VERSION = 1;
const TELEMETRY_HEADER_STRUCT_SIZE = 20;
const TELEMETRY_COLUMNS = [
    { key: "timeMs", ctor: Uint32Array },
    { key: "presenceBits", ctor: Uint16Array },
    { key: "messageVersion", ctor: Uint16Array },
    { key: "frameSeqNo", ctor: BigUint64Array },
    { key: "gearState", ctor: Uint8Array },
    { key: "autopilotState", ctor: Uint8Array },
    { key: "flags", ctor: Uint8Array },
    { key: "speedCmps", ctor: Uint16Array },
    { key: "acceleratorCenti", ctor: Uint16Array },
    { key: "steeringTenthsDeg", ctor: Int16Array },
    { key: "headingCdeg", ctor: Uint16Array },
    { key: "latitudeE7", ctor: Int32Array },
    { key: "longitudeE7", ctor: Int32Array },
    { key: "accelXMmps2", ctor: Int16Array },
    { key: "accelYMmps2", ctor: Int16Array },
    { key: "accelZMmps2", ctor: Int16Array },
];

export function decodeTelemetryBuffer(arrayBuffer) {
    const view = new DataView(arrayBuffer);
    const magic = String.fromCharCode(
        view.getUint8(0),
        view.getUint8(1),
        view.getUint8(2),
        view.getUint8(3)
    );
    const formatVersion = view.getUint16(4, true);
    const headerSize = view.getUint16(6, true);
    const sampleCount = view.getUint32(8, true);

    if (magic !== TELEMETRY_MAGIC || formatVersion !== TELEMETRY_FORMAT_VERSION) {
        throw new Error("Unsupported telemetry sidecar format");
    }

    const telemetry = { sampleCount };
    for (let index = 0; index < TELEMETRY_COLUMNS.length; index += 1) {
        const { key, ctor } = TELEMETRY_COLUMNS[index];
        const offset = view.getUint32(TELEMETRY_HEADER_STRUCT_SIZE + (index * 4), true);
        if (sampleCount === 0 || offset === 0) {
            telemetry[key] = new ctor(0);
            continue;
        }
        if (offset < headerSize || offset >= arrayBuffer.byteLength) {
            throw new Error(`Invalid telemetry offset for ${key}`);
        }
        telemetry[key] = new ctor(arrayBuffer, offset, sampleCount);
    }

    return telemetry;
}

export async function populateClipDurations(playlist, player, durationCache, onDurationUpdate) {
    if (playlist.length === 0) {
        return playlist;
    }

    const activeUrl = playlist[0].url;
    const durationLoads = playlist.map((clip, index) => {
        const durationPromise = index === 0 && activeUrl
            ? getStandardDuration(player, activeUrl, durationCache)
            : loadClipDuration(clip.url, durationCache);

        return durationPromise
            .then((duration) => {
                clip.duration = Number.isFinite(duration) && duration > 0 ? duration : 0;
                if (typeof onDurationUpdate === "function") {
                    onDurationUpdate();
                }
            })
            .catch(() => {
                clip.duration = 0;
                if (typeof onDurationUpdate === "function") {
                    onDurationUpdate();
                }
            });
    });

    await Promise.all(durationLoads);

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
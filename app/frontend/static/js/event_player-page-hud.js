import {
    AUTOPILOT_NONE_STATE,
    AUTOPILOT_PRESENT_MASK,
    BLINKER_LEFT_FLAG_MASK,
    BLINKER_LEFT_PRESENT_MASK,
    BLINKER_RIGHT_FLAG_MASK,
    BLINKER_RIGHT_PRESENT_MASK,
    BRAKE_FLAG_MASK,
    BRAKE_PRESENT_MASK,
    HEADING_PRESENT_MASK,
    LATITUDE_PRESENT_MASK,
    LONGITUDE_PRESENT_MASK,
    SPEED_PRESENT_MASK,
    STEERING_ANGLE_PRESENT_MASK,
} from "./event_player-media.js";
import {
    findTelemetrySampleIndex,
    formatDriverAssistDisplayText,
    formatSpeedText,
    getCompassDirectionLabel,
} from "./event_player-page-helpers.js";

export function createEventPlayerHudController({
    getPlaylist,
    getPendingEventTime,
    getActiveIndex,
    getPlayerCurrentTime,
    findClipForEventTime,
    eventHasAutopilotActivity,
    eventHasSteeringAngleData,
    eventDriverAssistDisplay,
    eventRouteSvgUrl,
    speedNode,
    blinkerLeftNode,
    headingIndicatorNode,
    headingNode,
    headingLabelNode,
    autopilotNode,
    brakeNode,
    blinkerRightNode,
    fsdPercentNode,
    routeMapNode,
}) {
    let activeRouteSvgUrl = null;
    let routeMapLoadPending = false;
    let routeMapSvgNode = null;
    let routeMapDotNode = null;

    function getTargetClipAtEventTime(eventTime) {
        const target = getPendingEventTime() !== null
            ? findClipForEventTime(eventTime)
            : { index: getActiveIndex(), offset: getPlayerCurrentTime() };
        const clip = getPlaylist()[target.index];
        return { target, clip };
    }

    function getTelemetrySampleAtEventTime(eventTime) {
        const { target, clip } = getTargetClipAtEventTime(eventTime);
        const telemetry = clip?.telemetry;
        if (!clip || !telemetry || telemetry.sampleCount === 0) {
            return null;
        }

        const sampleIndex = findTelemetrySampleIndex(Math.max(0, target.offset) * 1000, telemetry);
        if (sampleIndex < 0) {
            return null;
        }

        return {
            presenceBits: telemetry.presenceBits[sampleIndex],
            autopilotState: telemetry.autopilotState[sampleIndex],
            speedCmps: telemetry.speedCmps[sampleIndex],
            steeringTenthsDeg: telemetry.steeringTenthsDeg[sampleIndex],
            headingCdeg: telemetry.headingCdeg[sampleIndex],
            latitudeE7: telemetry.latitudeE7[sampleIndex],
            longitudeE7: telemetry.longitudeE7[sampleIndex],
            flags: telemetry.flags[sampleIndex],
        };
    }

    function ensureRouteMapDotNode(svgNode) {
        if (!svgNode) {
            routeMapDotNode = null;
            return;
        }

        const applyRouteDotStyles = (dotNode) => {
            dotNode.setAttribute("fill", "rgb(255, 51, 45)");
            dotNode.setAttribute("stroke", "rgba(0, 0, 0, 0.65)");
            dotNode.setAttribute("stroke-width", "1");
            dotNode.setAttribute("vector-effect", "non-scaling-stroke");
        };

        const namespace = "http://www.w3.org/2000/svg";
        const existingDot = svgNode.querySelector("circle[data-player-route-dot]");
        if (existingDot) {
            applyRouteDotStyles(existingDot);
            routeMapDotNode = existingDot;
            return;
        }

        const dotNode = document.createElementNS(namespace, "circle");
        dotNode.setAttribute("data-player-route-dot", "true");
        dotNode.setAttribute("r", "26");
        applyRouteDotStyles(dotNode);
        dotNode.setAttribute("visibility", "hidden");
        svgNode.appendChild(dotNode);
        routeMapDotNode = dotNode;
    }

    function hideRouteDot() {
        if (routeMapDotNode) {
            routeMapDotNode.setAttribute("visibility", "hidden");
        }
    }

    function loadRouteMapSvg(url) {
        if (!routeMapNode || !url || routeMapLoadPending) {
            return;
        }

        routeMapLoadPending = true;
        fetch(url)
            .then((response) => {
                if (!response.ok) {
                    throw new Error(`Route map request failed: ${response.status}`);
                }
                return response.text();
            })
            .then((svgText) => {
                if (!routeMapNode || activeRouteSvgUrl !== url) {
                    return;
                }
                routeMapNode.innerHTML = svgText;
                routeMapSvgNode = routeMapNode.querySelector("svg");
                ensureRouteMapDotNode(routeMapSvgNode);
            })
            .catch(() => {
                if (routeMapNode && activeRouteSvgUrl === url) {
                    routeMapNode.innerHTML = "";
                    routeMapSvgNode = null;
                    routeMapDotNode = null;
                }
            })
            .finally(() => {
                routeMapLoadPending = false;
            });
    }

    function projectTelemetrySampleToRouteMap(sample) {
        if (!sample || !routeMapSvgNode) {
            return null;
        }
        if ((sample.presenceBits & LATITUDE_PRESENT_MASK) === 0 || (sample.presenceBits & LONGITUDE_PRESENT_MASK) === 0) {
            return null;
        }

        const meanLat = Number.parseFloat(routeMapSvgNode.getAttribute("data-route-mean-lat") || "");
        const meanLon = Number.parseFloat(routeMapSvgNode.getAttribute("data-route-mean-lon") || "");
        const cosLat = Number.parseFloat(routeMapSvgNode.getAttribute("data-route-cos-lat") || "");
        const minX = Number.parseFloat(routeMapSvgNode.getAttribute("data-route-min-x") || "");
        const minY = Number.parseFloat(routeMapSvgNode.getAttribute("data-route-min-y") || "");
        const span = Number.parseFloat(routeMapSvgNode.getAttribute("data-route-span") || "");
        if (!Number.isFinite(meanLat) || !Number.isFinite(meanLon) || !Number.isFinite(cosLat)) {
            return null;
        }
        if (!Number.isFinite(minX) || !Number.isFinite(minY) || !Number.isFinite(span) || span <= 0) {
            return null;
        }

        const latitude = sample.latitudeE7 / 10_000_000;
        const longitude = sample.longitudeE7 / 10_000_000;
        const projectedX = (longitude - meanLon) * cosLat;
        const projectedY = latitude - meanLat;

        const canvasSize = 1000;
        const padding = 40;
        const drawable = canvasSize - (padding * 2);
        const normalizedX = padding + (((projectedX - minX) / span) * drawable);
        const normalizedY = padding + (((projectedY - minY) / span) * drawable);

        return {
            x: normalizedX,
            y: canvasSize - normalizedY,
        };
    }

    function getSpeedKphAtEventTime(eventTime) {
        const sample = getTelemetrySampleAtEventTime(eventTime);
        if (!sample || (sample.presenceBits & SPEED_PRESENT_MASK) === 0) {
            return null;
        }

        return sample.speedCmps * 0.036;
    }

    function syncHeadingUI(eventTime) {
        if (!headingNode || !headingIndicatorNode || !headingLabelNode) {
            return;
        }

        const sample = getTelemetrySampleAtEventTime(eventTime);
        if (!sample || (sample.presenceBits & HEADING_PRESENT_MASK) === 0) {
            headingIndicatorNode.hidden = true;
            headingNode.hidden = true;
            headingLabelNode.hidden = true;
            headingLabelNode.textContent = "";
            headingNode.style.transform = "rotate(0deg)";
            return;
        }

        const headingDeg = sample.headingCdeg / 100;
        headingIndicatorNode.hidden = false;
        headingNode.hidden = false;
        headingLabelNode.hidden = false;
        headingLabelNode.textContent = getCompassDirectionLabel(headingDeg);
        headingNode.style.transform = `rotate(${headingDeg}deg)`;
    }

    function syncAutopilotUI(eventTime) {
        if (!autopilotNode) {
            return;
        }

        if (!eventHasAutopilotActivity && !eventHasSteeringAngleData) {
            autopilotNode.hidden = true;
            autopilotNode.style.transform = "rotate(0deg)";
            return;
        }

        const sample = getTelemetrySampleAtEventTime(eventTime);
        if (!sample) {
            autopilotNode.hidden = true;
            autopilotNode.style.transform = "rotate(0deg)";
            return;
        }

        const isActive = Boolean((sample.presenceBits & AUTOPILOT_PRESENT_MASK) && sample.autopilotState !== AUTOPILOT_NONE_STATE);
        const steeringAngleDeg = (sample.presenceBits & STEERING_ANGLE_PRESENT_MASK)
            ? sample.steeringTenthsDeg / 10
            : 0;
        autopilotNode.hidden = false;
        autopilotNode.src = isActive ? autopilotNode.dataset.activeSrc : autopilotNode.dataset.inactiveSrc;
        autopilotNode.style.transform = `rotate(${steeringAngleDeg}deg)`;
    }

    function syncBlinkerUI(eventTime) {
        const sample = getTelemetrySampleAtEventTime(eventTime);
        const leftOn = Boolean(sample && (sample.presenceBits & BLINKER_LEFT_PRESENT_MASK) && (sample.flags & BLINKER_LEFT_FLAG_MASK));
        const rightOn = Boolean(sample && (sample.presenceBits & BLINKER_RIGHT_PRESENT_MASK) && (sample.flags & BLINKER_RIGHT_FLAG_MASK));

        if (blinkerLeftNode) {
            blinkerLeftNode.hidden = !leftOn;
        }
        if (blinkerRightNode) {
            blinkerRightNode.hidden = !rightOn;
        }
    }

    function syncBrakeUI(eventTime) {
        if (!brakeNode) {
            return;
        }

        const sample = getTelemetrySampleAtEventTime(eventTime);
        const brakeOn = Boolean(sample && (sample.presenceBits & BRAKE_PRESENT_MASK) && (sample.flags & BRAKE_FLAG_MASK));
        brakeNode.hidden = !brakeOn;
    }

    function syncSpeedUI(eventTime) {
        if (!speedNode) {
            return;
        }
        const speedKph = getSpeedKphAtEventTime(eventTime);
        if (speedKph === null) {
            speedNode.hidden = true;
            speedNode.textContent = "";
            return;
        }
        speedNode.hidden = false;
        speedNode.innerHTML = formatSpeedText(speedKph);
    }

    function syncFsdPercentUI() {
        if (!fsdPercentNode) {
            return;
        }

        if (eventDriverAssistDisplay === null) {
            fsdPercentNode.hidden = true;
            fsdPercentNode.textContent = "";
            return;
        }

        fsdPercentNode.hidden = false;
        fsdPercentNode.textContent = formatDriverAssistDisplayText(eventDriverAssistDisplay);
    }

    function syncRouteMapUI(eventTime) {
        try {
            if (!routeMapNode) {
                return;
            }

            const nextRouteSvgUrl = eventRouteSvgUrl;

            if (!nextRouteSvgUrl) {
                routeMapNode.hidden = true;
                if (activeRouteSvgUrl !== null) {
                    routeMapNode.innerHTML = "";
                    activeRouteSvgUrl = null;
                    routeMapSvgNode = null;
                    routeMapDotNode = null;
                }
                return;
            }

            if (nextRouteSvgUrl !== activeRouteSvgUrl) {
                activeRouteSvgUrl = nextRouteSvgUrl;
                routeMapNode.innerHTML = "";
                routeMapSvgNode = null;
                routeMapDotNode = null;
                loadRouteMapSvg(nextRouteSvgUrl);
            } else if (!routeMapSvgNode && !routeMapLoadPending) {
                loadRouteMapSvg(nextRouteSvgUrl);
            }

            const sample = getTelemetrySampleAtEventTime(eventTime);
            const projected = projectTelemetrySampleToRouteMap(sample);
            if (projected && routeMapDotNode) {
                routeMapDotNode.setAttribute("cx", String(projected.x));
                routeMapDotNode.setAttribute("cy", String(projected.y));
                routeMapDotNode.setAttribute("visibility", "visible");
            } else {
                hideRouteDot();
            }

            routeMapNode.hidden = false;
        } catch {
            if (routeMapNode) {
                routeMapNode.hidden = true;
            }
            hideRouteDot();
        }
    }

    return {
        syncHeadingUI,
        syncAutopilotUI,
        syncBlinkerUI,
        syncBrakeUI,
        syncSpeedUI,
        syncFsdPercentUI,
        syncRouteMapUI,
    };
}

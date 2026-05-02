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
    speedNode,
    blinkerLeftNode,
    headingIndicatorNode,
    headingNode,
    headingLabelNode,
    autopilotNode,
    brakeNode,
    blinkerRightNode,
    fsdPercentNode,
}) {
    function getTelemetrySampleAtEventTime(eventTime) {
        const target = getPendingEventTime() !== null
            ? findClipForEventTime(eventTime)
            : { index: getActiveIndex(), offset: getPlayerCurrentTime() };
        const clip = getPlaylist()[target.index];
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
            flags: telemetry.flags[sampleIndex],
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

        const isActive = Boolean(sample && (sample.presenceBits & AUTOPILOT_PRESENT_MASK) && sample.autopilotState !== AUTOPILOT_NONE_STATE);
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

    return {
        syncHeadingUI,
        syncAutopilotUI,
        syncBlinkerUI,
        syncBrakeUI,
        syncSpeedUI,
        syncFsdPercentUI,
    };
}
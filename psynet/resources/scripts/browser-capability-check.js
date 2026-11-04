export function activate({vars, psynet}) {
    const capabilities = vars["capabilities"] ?? [];
    let cancelled = false;
    let timer = null;
    // Checks may wait on a permission prompt, so they must not block page
    // activation. nextPage() requires pageReady, which the framework sets
    // after activate() returns and announces with timelinePageReady; the
    // setTimeout(0) lets it finish that activation before we navigate.
    const onReady = () => {
        timer = setTimeout(async () => {
            const result = await runChecks(capabilities);
            if (!cancelled) psynet.nextPage(result);
        }, 0);
    };
    window.addEventListener("timelinePageReady", onReady, {once: true});
    return () => {
        cancelled = true;
        clearTimeout(timer);
        window.removeEventListener("timelinePageReady", onReady);
    };
}

async function runChecks(capabilities) {
    for (const cap of capabilities) {
        const check = CAPABILITY_CHECKS[cap];
        if (!check) {
            console.warn(`browser-capability-check: no JS check for token "${cap}"; skipping`);
            continue;
        }
        let passed = false;
        try {
            passed = await check();
        } catch (error) {
            console.warn(`browser-capability-check: check for "${cap}" failed`, error);
        }
        if (!passed) {
            return {passed: false, missing: cap};
        }
    }
    return {passed: true};
}

const CAPABILITY_CHECKS = {
    screen_capture: async () =>
        typeof navigator.mediaDevices?.getDisplayMedia === "function",

    video_recording: async () => {
        if (typeof MediaRecorder === "undefined") return false;
        // Answer recordings are captured and uploaded as WebM only.
        return MediaRecorder.isTypeSupported("video/webm");
    },

    audio_playback: async () =>
        typeof AudioContext !== "undefined" || typeof webkitAudioContext !== "undefined",

    microphone: async () => checkMediaPermission("microphone", {audio: true}),

    camera: async () => checkMediaPermission("camera", {video: true}),
};

async function checkMediaPermission(permissionName, constraints) {
    if (navigator.permissions) {
        try {
            const status = await navigator.permissions.query({name: permissionName});
            if (status.state === "denied") return false;
        } catch (_) {
            // permissions.query not supported for this name (common on Safari)
        }
    }
    try {
        const stream = await navigator.mediaDevices.getUserMedia(constraints);
        stream.getTracks().forEach(t => t.stop());
        return true;
    } catch (_) {
        return false;
    }
}

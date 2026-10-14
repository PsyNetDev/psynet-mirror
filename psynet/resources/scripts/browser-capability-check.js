export async function activate({vars, psynet}) {
    const capabilities = vars["capabilities"] || [];
    const result = await runChecks(capabilities);
    // nextPage() requires pageReady=true, which is set by the framework after
    // activate() returns — so calling it directly or via setTimeout(0) fires too
    // early. timelinePageReady is dispatched when pageReady becomes true; the
    // nested setTimeout(0) gives the framework one more tick to finish before
    // we navigate.
    window.addEventListener("timelinePageReady", () => {
        setTimeout(() => psynet.nextPage(result), 0);
    }, {once: true});
}

async function runChecks(capabilities) {
    for (const cap of capabilities) {
        const check = CAPABILITY_CHECKS[cap];
        if (!check) {
            console.warn(`browser-capability-check: no JS check for token "${cap}"; skipping`);
            continue;
        }
        const passed = await check();
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
        const formats = [
            "video/webm;codecs=vp8",
            "video/webm;codecs=vp9",
            "video/webm",
            "video/mp4",
        ];
        return formats.some(f => MediaRecorder.isTypeSupported(f));
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

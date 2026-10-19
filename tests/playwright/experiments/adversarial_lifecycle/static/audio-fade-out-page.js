function writeAscii(view, offset, text) {
    for (let i = 0; i < text.length; i++) {
        view.setUint8(offset + i, text.charCodeAt(i));
    }
}

function makeSilentWavBuffer(durationSeconds) {
    const sampleRate = 8000;
    const samples = Math.floor(sampleRate * durationSeconds);
    const dataSize = samples * 2;
    const buffer = new ArrayBuffer(44 + dataSize);
    const view = new DataView(buffer);
    writeAscii(view, 0, "RIFF");
    view.setUint32(4, 36 + dataSize, true);
    writeAscii(view, 8, "WAVE");
    writeAscii(view, 12, "fmt ");
    view.setUint32(16, 16, true);
    view.setUint16(20, 1, true);
    view.setUint16(22, 1, true);
    view.setUint32(24, sampleRate, true);
    view.setUint32(28, sampleRate * 2, true);
    view.setUint16(32, 2, true);
    view.setUint16(34, 16, true);
    writeAscii(view, 36, "data");
    view.setUint32(40, dataSize, true);
    return buffer;
}

export async function activate({psynet, trial}) {
    window.__audioFadeOutLifecycle = {ready: false};

    trial.onEvent("trialConstruct", async function () {
        await psynet.media.addExtraAudioStimulus(
            makeSilentWavBuffer(0.8),
            "fadeout_stale_audio"
        );
        psynet.audio.fadeout_stale_audio.play({
            fadeOut: 0.3,
            gain: 0.001,
        });
        window.__audioFadeOutLifecycle.ready = true;
    });
}

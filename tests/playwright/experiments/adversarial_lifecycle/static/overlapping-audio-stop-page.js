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

function assertRegressionResult(actual, expected) {
    for (const [key, value] of Object.entries(expected)) {
        if (actual[key] !== value) {
            throw new Error(
                `Expected ${key} to equal ${JSON.stringify(value)}, ` +
                    `got ${JSON.stringify(actual[key])}.`
            );
        }
    }
}

export async function activate({psynet, trial}) {
    window.__overlappingAudioStopLifecycle = {ready: false};

    trial.onEvent("trialConstruct", async function () {
        await psynet.media.addExtraAudioStimulus(
            makeSilentWavBuffer(0.4),
            "overlapping_manual_stop"
        );
        window.__overlappingAudioStopLifecycle.ready = true;
    });

    window.__runOverlappingAudioStopRegression = async function () {
        const countActiveSounds = () =>
            psynet.media.sounds.filter(
                (activeSound) =>
                    activeSound.stimulusId === "overlapping_manual_stop"
            ).length;

        const sound = psynet.audio.overlapping_manual_stop.play({
            loop: true,
            gain: 0.001,
        });
        const automaticStop = sound.stop({
            fadeOut: 0.2,
            manual: false,
        });
        const manualStop = sound.stop({
            fadeOut: 0,
            manual: true,
        });
        const stimulusStop = psynet.audio.overlapping_manual_stop.stop({
            fadeOut: 0,
            manual: true,
        });
        const stimulusStopIsPromise = typeof stimulusStop?.then === "function";
        await Promise.all([automaticStop, manualStop, stimulusStop]);
        await new Promise((resolve) => setTimeout(resolve, 100));

        const delayedSound = psynet.audio.overlapping_manual_stop.play({
            loop: true,
            gain: 0.001,
        });
        const delayedStop = psynet.audio.overlapping_manual_stop.stop({
            fadeOut: 0.05,
            manual: true,
        });
        const delayedStopIsPromise = typeof delayedStop?.then === "function";
        const activeBeforeDelayedAwait = countActiveSounds();
        await delayedStop;

        const result = {
            manuallyStopped: sound.manuallyStopped,
            sameStopPromise: automaticStop === manualStop,
            stimulusStopIsPromise,
            activeCopiesAfterOverlap: countActiveSounds(),
            delayedManuallyStopped: delayedSound.manuallyStopped,
            delayedStopIsPromise,
            activeBeforeDelayedAwait,
            activeCopiesAfterDelayedAwait: countActiveSounds(),
        };
        assertRegressionResult(result, {
            manuallyStopped: true,
            sameStopPromise: true,
            stimulusStopIsPromise: true,
            activeCopiesAfterOverlap: 0,
            delayedManuallyStopped: true,
            delayedStopIsPromise: true,
            activeBeforeDelayedAwait: 1,
            activeCopiesAfterDelayedAwait: 0,
        });
        return true;
    };

    return function cleanup() {
        delete window.__runOverlappingAudioStopRegression;
    };
}

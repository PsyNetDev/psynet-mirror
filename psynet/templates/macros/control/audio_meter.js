/*
The MIT License (MIT)

Copyright (c) 2014 Chris Wilson, modified 2020 by Peter Harrison

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
*/

const audioMeterControl = (psynet.page.control.audioMeter = {});

audioMeterControl.init = function(json) {
    let config = JSON.parse(json);

    this.displayRange = config.display_range;
    this.decay = config.decay;
    this.threshold = config.threshold;
    this.grace = config.grace
    this.warnOnClip = config.warn_on_clip
    this.msgDuration = config.msg_duration;

    this.audioContext = null;
    this.audioMeter = null;
    this.audioMeterText = document.getElementById("audio-meter-text");
    this.audioMeterDeviceName = document.getElementById("audio-meter-device-name");
    this.track = document.getElementById("audio-meter");
    this.fill = this.track
        ? this.track.querySelector(".audio-meter__fill")
        : null;
    this.mediaStream = null;
    this.mediaStreamSource = null;
    this.rafID = null;

    this.timeLastTooLow = -1e20;
    this.timeLastTooHigh = -1e20;
    this.timeUntilTooLow = 1.5; // ms
    this.timeUntilTooHigh = 0.0; // ms

    this.timeLastNotTooLow = -1e20;
    this.timeLastNotTooHigh = -1e20;

    this.messageTimer = null;

    var audioMeterControl = this;
    psynet.trial.onEvent("trialConstruct",function() {
        audioMeterControl.track = document.getElementById("audio-meter");
        audioMeterControl.fill = audioMeterControl.track
            ? audioMeterControl.track.querySelector(".audio-meter__fill")
            : null;
        audioMeterControl.audioContext = psynet.media.audioContext;
        psynet.trial.setTimer(function() {
            audioMeterControl.audioMeterText.style.display = "block";
        }, 1000);
        return new Promise((resolve) => {
            navigator.mediaDevices.getUserMedia({ audio: {
            echoCancellation: false,
            autoGainControl: false,
            noiseSuppression: false,
            latency: 0
          }, video: false })
            .then(function(stream) {
                audioMeterControl.onMicrophoneGranted(stream);
                psynet.addPageCleanupCallback(function() {
                    audioMeterControl.dispose();
                });
                resolve();
            });
        });
    });
    psynet.trial.onEvent("trialStop", function() {
        audioMeterControl.destroy();
    });
}

audioMeterControl.onMicrophoneDenied = function() {
    alert('Microphone permission denied. You may refresh the page to try again.');
    psynet.submit.disable();
}

audioMeterControl.checkMicrophone = function(stream) {
    var microphoneMetadata = psynet.media.getMicrophoneMetadataFromAudioStream(stream);

    if (microphoneMetadata.muted) {
        alert('Your microphone is muted. Unmute your microphone in your system settings and try again.')
        psynet.submit.disable();
    }
    return microphoneMetadata;
}

audioMeterControl.onMicrophoneGranted = async function(stream) {
    this.showMessage("Starting audio meter...", "blue");

    // Show device name
    if (this.audioMeterDeviceName) {
        try {
            const devices = await navigator.mediaDevices.enumerateDevices();
            const audioInput = devices.find(device => device.kind === 'audioinput' && device.deviceId === stream.getAudioTracks()[0].getSettings().deviceId);
            if (audioInput && audioInput.label) {
                this.audioMeterDeviceName.textContent = `Microphone: ${audioInput.label}`;
            } else {
                this.audioMeterDeviceName.textContent = "Microphone: (device name unavailable)";
            }
        } catch (e) {
            this.audioMeterDeviceName.textContent = "Microphone: (error retrieving device name)";
        }
    }

    let microphoneMetadata = this.checkMicrophone(stream);
    Object.assign(psynet.response.staged.metadata, microphoneMetadata);

    // Create an AudioNode from the stream.
    this.mediaStream = stream;
    this.mediaStreamSource = this.audioContext.createMediaStreamSource(stream);

    // Create a new volume meter and connect it.
    this.audioMeter = this.createAudioMeter(this.audioContext);
    this.mediaStreamSource.connect(this.audioMeter);

    // kick off the visual updating
    var audioMeterControl = this;
    this.rafID = window.requestAnimationFrame(function(time) {
        audioMeterControl.onLevelChange(time);
    });
}

audioMeterControl.stopLevelChangeLoop = function() {
    if (this.rafID !== null) {
        cancelAnimationFrame(this.rafID);
        this.rafID = null;
    }
}

audioMeterControl.destroy = function() {
    this.stopLevelChangeLoop();
    if (this.audioMeter && typeof this.audioMeter.shutdown === "function") {
        this.audioMeter.shutdown();
    }
    this.audioMeter = null;
    if (this.messageTimer !== null) {
        clearTimeout(this.messageTimer);
        this.messageTimer = null;
    }
}

audioMeterControl.dispose = function() {
    this.destroy();
    if (this.mediaStreamSource && typeof this.mediaStreamSource.disconnect === "function") {
        this.mediaStreamSource.disconnect();
    }
    this.mediaStreamSource = null;
    psynet.media.stopStream(this.mediaStream);
    this.mediaStream = null;
}

audioMeterControl.applyColor = function(color) {
    let resolved = psynet.theme
        ? psynet.theme.resolveColor(color)
        : color;
    if (this.audioMeterText) {
        this.audioMeterText.style.color = resolved;
    }
    if (this.track) {
        this.track.style.setProperty("--audio-meter-fill", resolved);
    }
}

audioMeterControl.setLevel = function(proportion) {
    let pct = Math.max(0, Math.min(1, proportion)) * 100;
    if (this.fill) {
        this.fill.style.width = pct + "%";
    }
    if (this.track) {
        this.track.setAttribute("aria-valuenow", String(Math.round(pct)));
    }
}

audioMeterControl.showMessage = function(message, color) {
    this.audioMeterText.innerHTML = message;
    this.applyColor(color);

    clearTimeout(this.messageTimer);

    var self = this;
    this.messageTimer = psynet.trial.setTimer(function() {
        self.resetMessage();
    }, self.msgDuration * 2000);
}

audioMeterControl.resetMessage = function() {
    this.audioMeterText.innerHTML = "Just right.";
    this.applyColor("green");
}

audioMeterControl.onLevelChange = function(time) {
    if (!this.audioMeter) {
        return;
    }

    if (this.audioMeter.volume.high >= this.threshold.high) {
        this.timeLastTooHigh = time;
    } else {
        this.timeLastNotTooHigh = time;
    }

    if (this.audioMeter.volume.low <= this.threshold.low) {
        this.timeLastTooLow = time;
    } else {
        this.timeLastNotTooLow = time;
    }

    if (
        this.audioMeter.checkClipping() ||
        time - this.timeLastNotTooHigh > this.timeUntilTooHigh * 1000.0
    ) {
        this.showMessage("Too loud!", "red")
    } else if (time - this.timeLastNotTooLow > this.timeUntilTooLow * 1000.0) {
        this.showMessage("Too quiet!", "red")
    }

    var proportion;
    if (this.audioMeter.volume.display <= this.displayRange.min) {
        proportion = 0.0;
    } else if (this.audioMeter.volume.display >= this.displayRange.max) {
        proportion = 1.0;
    } else {
        proportion = (this.audioMeter.volume.display - this.displayRange.min) / (this.displayRange.max - this.displayRange.min);
    }

    this.setLevel(proportion);

    var audioMeterControl = this;
    this.rafID = window.requestAnimationFrame(function(time) {
        audioMeterControl.onLevelChange(time);
    });
}

/*
    Usage:
    audioNode = createAudioMeter(audioContext,clipLevel,averaging,clipLag);
    audioContext: the AudioContext you're using.
    clipLevel: the level (0 to 1) that you would consider "clipping".
    Defaults to 0.98.
    averaging: how "smoothed" you would like the meter to be over time.
    Should be between 0 and less than 1.  Defaults to 0.95.
    clipLag: how long you would like the "clipping" indicator to show
    after clipping has occured, in milliseconds.  Defaults to 750ms.
    Access the clipping through node.checkClipping(); use node.shutdown to get rid of it.
    */

audioMeterControl.createAudioMeter = function(audioContext, clipLevel, averaging, clipLag) {
    var audioMeterControl = this;
    var processor = this.audioContext.createScriptProcessor(512);
    processor.onaudioprocess = function(event) {
        audioMeterControl.volumeAudioProcess(event);
    }
    processor.clipping = false;
    processor.lastClip = 0;
    processor.volume = {
        display: 0.0,
        high: 0.0,
        low: 0.0
    }
    processor.clipLevel = clipLevel || 0.98;
    processor.averaging = averaging || 0.95;
    processor.clipLag = clipLag || 750;

    // this will have no effect, since we don't copy the input to the output,
    // but works around a current Chrome bug.
    processor.connect(audioContext.destination);

    processor.checkClipping =
        function(){
            if (!this.clipping)
                return false;
            if ((this.lastClip + this.clipLag) < window.performance.now())
                this.clipping = false;
            return this.clipping;
        };

    processor.shutdown =
        function(){
            this.disconnect();
            this.onaudioprocess = null;
        };

    return processor;
}

audioMeterControl.volumeAudioProcess = function(event) {
    var buf = event.inputBuffer.getChannelData(0);
    var bufLength = buf.length;
    var sum = 0;
    var x;

    // Do a root-mean-square on the samples: sum up the squares...
    for (var i = 0; i < bufLength; i++) {
        x = buf[i];
        if (Math.abs(x) >= this.clipLevel) {
            this.clipping = true;
            this.lastClip = window.performance.now();
        }
        sum += x * x;
    }

    // ... then take the square root of the sum.
    var rms =  Math.sqrt(sum / bufLength);

    var bufferDuration = bufLength / event.inputBuffer.sampleRate;


    // Now smooth this out with the averaging factor applied
    // to the previous sample - take the max here because we
    // want "fast attack, slow release."
    var self = this;
    ["display", "high", "low"].forEach(function(x) {
        // Exponential smmoothing, see https://en.wikipedia.org/wiki/Exponential_smoothing
        var alpha = 1 - Math.exp(- bufferDuration / self.decay[x]);
        self.audioMeter.volume[x] = (1 - alpha) * self.audioMeter.volume[x] + alpha * self.rmsToDb(rms);
    })

    // this.volume = Math.max(rms, this.volume*this.averaging);
}

audioMeterControl.rmsToDb = function(rms) {
    return Math.max(-100, 20 * Math.log10(rms));
}

audioMeterControl.updateFromSliders = function() {
    this.decay = {
        display: $("#decay-display").get(0).value,
        high: $("#decay-high").get(0).value,
        low: $("#decay-low").get(0).value
    }

    this.threshold = {
        high: $("#threshold-high").get(0).value,
        low: $("#threshold-low").get(0).value,
    }

    this.grace = {
        high: $("#grace-high").get(0).value,
        low: $("#grace-low").get(0).value,
    }

    this.warnOnClip = Boolean($("#warn-on-clip").get(0).value)

    this.msgDuration = {
        high: $("#msg-duration-high").get(0).value,
        low: $("#msg-duration-low").get(0).value,
    }
}

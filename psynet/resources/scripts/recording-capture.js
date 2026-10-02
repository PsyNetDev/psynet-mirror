/** Shared camera/screen ownership and bounded per-page WebM capture.
 * Streams belong to the document, while recorder instances belong to a clip.
 * Both answer controls and background capture must use this module so page
 * cleanup discards a clip without revoking an otherwise reusable permission.
 */
export class RecordingDevices {
  constructor() {
    this.streams = new Map();
  }

  reusable(source, audio) {
    const stream = this.streams.get(source);
    return stream && stream.getVideoTracks().some(track => track.readyState === "live") &&
      (!audio || (stream._psynetAudio === JSON.stringify(audio) &&
        (source === "screen" || stream.getAudioTracks().some(track => track.readyState === "live"))));
  }

  async acquire(source, {audio = false, lowResolution = false} = {}) {
    let stream = this.streams.get(source);
    if (!this.reusable(source, audio)) {
      const keepVideo = source === "camera" && this.reusable(source, false);
      // No awaited work before acquisition: callers can invoke this directly
      // from a permission button and retain screen capture's user activation.
      if (keepVideo) {
        const microphone = await navigator.mediaDevices.getUserMedia({video:false, audio});
        stream.getAudioTracks().forEach(track => { stream.removeTrack(track); track.stop(); });
        microphone.getAudioTracks().forEach(track => stream.addTrack(track));
      } else {
        this.release(source);
        stream = await (source === "camera"
          ? navigator.mediaDevices.getUserMedia({video:true, audio})
          : navigator.mediaDevices.getDisplayMedia({video:true, audio}));
      }
      stream._psynetAudio = JSON.stringify(audio);
      this.streams.set(source, stream);
    }
    try {
      const constraints = lowResolution
        ? {width:{ideal:640,max:640},height:{ideal:480,max:480},frameRate:{ideal:15,max:15}}
        : {};
      await Promise.all(stream.getVideoTracks().map(track => track.applyConstraints(constraints)));
    } catch (error) {
      console.warn("Could not apply recording resolution", source, error);
      this.release(source);
      throw error;
    }
    // Never include a cached microphone track in a clip that requested no audio.
    return audio ? stream : new MediaStream(stream.getVideoTracks());
  }

  release(source) {
    this.streams.get(source)?.getTracks().forEach(track => track.stop());
    this.streams.delete(source);
  }

  async acquireAnswer(source, audio = false, labels) {
    if (source === "camera" || this.reusable(source, audio)) {
      return this.acquire(source, {audio});
    }
    // Screen permission must be requested by a click in the owning document.
    return new Promise((resolve, reject) => {
      const dialog = document.createElement("dialog");
      dialog.id = "answer-recording-permission";
      const message = document.createElement("p");
      message.textContent = labels.answer;
      const button = document.createElement("button");
      button.type = "button";
      button.textContent = labels.screen;
      let finished = false;
      const finish = () => {
        if (finished) return false;
        finished = true;
        dialog.close(); dialog.remove();
        return true;
      };
      button.onclick = () => {
        button.disabled = true;
        this.acquire(source, {audio}).then(stream => {
          if (!finish()) { this.release(source); return; }
          resolve(stream);
        }, error => { if (finish()) reject(error); });
      };
      dialog.addEventListener("cancel", event => {
        event.preventDefault();
        if (finish()) reject(new Error("Screen recording declined."));
      });
      const skip = document.createElement("button");
      skip.type = "button";
      skip.textContent = labels.skip;
      skip.onclick = () => {
        if (finish()) reject(new Error("Screen recording declined."));
      };
      dialog.append(message, button, skip);
      document.body.append(dialog);
      dialog.showModal();
    });
  }
}

export class RecordingClip {
  constructor(stream, {maxBytes = 128 * 1024 * 1024, maxDuration = null,
    lowBitrate = false, onChange = () => {}} = {}) {
    this.stream = stream;
    this.maxBytes = maxBytes;
    this.maxDuration = maxDuration;
    this.lowBitrate = lowBitrate;
    this.onChange = onChange;
    this.reset();
  }

  startRecording() {
    if (this.recorder?.state === "recording") return;
    this.reset();
    if (!this.stream) { this.error = "missing_recording"; return; }
    try {
      this.recorder = new MediaRecorder(this.stream, {
        mimeType:"video/webm",
        ...(this.lowBitrate ? {videoBitsPerSecond:256000,audioBitsPerSecond:32000} : {}),
      });
      this.done = new Promise(resolve => { this.resolve = resolve; });
      this.recorder.ondataavailable = event => {
        if (this.error) return;
        if (this.size + event.data.size > this.maxBytes) {
          this.error = "size_limit";
          this.chunks = [];
          this.stop();
        } else { this.chunks.push(event.data); this.size += event.data.size; }
        this.onChange(this);
      };
      this.recorder.onstop = () => { this.detach(); this.resolve(); this.onChange(this); };
      this.recorder.onerror = () => { this.error = "capture_error"; this.chunks = []; this.stop(); };
      this.ended = () => { this.outcome = "source_ended"; this.stop(); this.onChange(this); };
      this.stream.getVideoTracks().forEach(track => track.addEventListener("ended", this.ended));
      this.recorder.start(1000);
      if (this.maxDuration !== null) {
        this.timer = setTimeout(() => { this.outcome = "duration_limit"; this.stop(); this.onChange(this); }, this.maxDuration * 1000);
      }
    } catch (error) {
      console.warn("Could not start recording", error);
      this.error = "capture_error";
      this.detach();
      this.resolve?.();
    }
  }

  detach() {
    clearTimeout(this.timer);
    if (this.ended) this.stream?.getVideoTracks().forEach(track => track.removeEventListener("ended", this.ended));
  }

  stop() {
    clearTimeout(this.timer);
    try {
      if (this.recorder && this.recorder.state !== "inactive") this.recorder.stop();
    } catch (error) {
      console.warn("Could not stop recording", error);
      this.error = "capture_error";
      this.resolve?.();
    }
  }

  async stopRecording() {
    this.stop();
    let timer;
    try {
      await Promise.race([this.done, new Promise(resolve => {
        timer = setTimeout(() => { this.error = "capture_error"; resolve(); }, 3000);
      })]);
    } finally { clearTimeout(timer); }
  }

  getBlob() {
    return this.error ? new Blob([]) : new Blob(this.chunks, {type:"video/webm"});
  }

  getState() { return this.recorder?.state || "inactive"; }

  reset() {
    this.stop();
    this.detach();
    if (this.recorder) {
      this.recorder.ondataavailable = null;
      this.recorder.onstop = null;
      this.recorder.onerror = null;
    }
    this.resolve?.();
    this.recorder = null;
    this.chunks = [];
    this.size = 0;
    this.error = null;
    this.outcome = null;
    this.done = Promise.resolve();
  }
}

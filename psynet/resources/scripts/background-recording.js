/** Document-owned optional capture. Tracks survive ordinary SPA page cleanup;
 * each page owns its recorder/chunks. Uploads use the existing media queue.
 */
export class BackgroundRecorder {
  constructor(queue) {
    this.queue = queue;
    this.streams = new Map();
    this.decisions = new Map();
    this.clips = {};
  }

  async begin(config) {
    await this.discard();
    this.config = config;
    this.unavailable = {};
    this.outcomes = {};
    this.result = null;
    if (!window.MediaRecorder || !MediaRecorder.isTypeSupported("video/webm")) {
      for (const source of config.sources) this.unavailable[source] = "unsupported";
      return;
    }
    if (this.queue.availableBytes <= 0 || this.queue.availableSlots <= 0) {
      for (const source of config.sources) this.unavailable[source] = "queue_full";
      return;
    }
    const needed = config.sources.filter(source => {
      const stream = this.streams.get(source);
      if (stream && stream.getVideoTracks().some(track => track.readyState === "live") && stream._psynetAudio === config.audio) return false;
      if (stream) {
        stream.getTracks().forEach(track => track.stop());
        this.streams.delete(source);
      }
      return !this.decisions.has(source);
    });
    if (needed.length) await this.askPermission(needed);
    this.indicator = document.createElement("div");
    this.indicator.id = "background-recording-status";
    this.indicator.setAttribute("role", "status");
    this.indicator.style.cssText = "position:fixed;bottom:12px;right:12px;padding:8px;background:#fff;border:1px solid #777;z-index:1000";
    document.body.append(this.indicator);
    // Divide remaining queue space across sources before recording starts. This
    // bounds capture in addition to retained uploads; chunks arrive each second.
    let remaining = this.queue.availableBytes;
    let slots = this.queue.availableSlots;
    let sourcesLeft = config.sources.length;
    for (const source of config.sources) {
      const stream = this.streams.get(source);
      if (!stream || !stream.getVideoTracks().some(track => track.readyState === "live")) {
        this.unavailable[source] = this.decisions.get(source) || "source_ended";
        continue;
      }
      const limit = Math.min(config.max_bytes, Math.floor(remaining / sourcesLeft--));
      if (limit <= 0 || slots <= 0) { this.unavailable[source] = "queue_full"; continue; }
      remaining -= limit;
      slots -= 1;
      try {
        const recorder = new MediaRecorder(stream, {mimeType:"video/webm", videoBitsPerSecond:256000, audioBitsPerSecond:32000});
        const clip = {recorder, chunks:[], size:0, limit};
        this.clips[source] = clip;
        clip.done = new Promise(resolve => { clip.resolve = resolve; });
        recorder.ondataavailable = event => {
          if (this.unavailable[source]) return;
          if (clip.size + event.data.size > limit) {
            this.unavailable[source] = "size_limit";
            clip.chunks = [];
            this.stopClip(source);
          } else {
            clip.chunks.push(event.data);
            clip.size += event.data.size;
            this.indicator.dataset.bytes = String(Object.values(this.clips).reduce((sum, item) => sum + item.size, 0));
          }
        };
        recorder.onstop = () => { clearTimeout(clip.timer); clip.resolve(); this.updateIndicator(); };
        recorder.onerror = () => { this.unavailable[source] = "capture_error"; clip.chunks = []; this.stopClip(source); };
        clip.ended = () => { this.outcomes[source] = "source_ended"; this.decisions.set(source,"source_ended"); this.stopClip(source); };
        stream.getVideoTracks().forEach(track => track.addEventListener("ended",clip.ended));
        recorder.start(1000);
        clip.timer = setTimeout(() => { this.outcomes[source] = "duration_limit"; this.stopClip(source); }, config.max_duration * 1000);
      } catch (error) {
        console.warn("Could not start background recording", source, error);
        this.unavailable[source] = "capture_error";
      }
    }
    this.updateIndicator();
  }

  askPermission(sources) {
    return new Promise(resolve => {
      const dialog = document.createElement("dialog");
      dialog.id = "background-recording-permission";
      const text = document.createElement("p");
      text.textContent = "This page can record optional camera or screen video. You may continue without recording.";
      dialog.append(text);
      let finished = false;
      const finish = () => {
        if (finished) return;
        finished = true;
        for (const source of sources) if (!this.streams.has(source) && !this.decisions.has(source)) this.decisions.set(source,"skipped");
        dialog.close(); dialog.remove(); resolve();
      };
      dialog.addEventListener("cancel", event => { event.preventDefault(); finish(); });
      for (const source of sources) {
        const button = document.createElement("button");
        button.type = "button";
        button.textContent = source === "camera" ? "Enable camera" : "Share screen";
        button.onclick = async () => {
          button.disabled = true;
          try {
            // Acquisition is called directly from this click: screen sharing
            // must retain the browser's user activation.
            const stream = await (source === "camera"
              ? navigator.mediaDevices.getUserMedia({video:{width:{ideal:640},height:{ideal:480},frameRate:{ideal:15,max:15}},audio:this.config.audio})
              : navigator.mediaDevices.getDisplayMedia({video:{frameRate:{ideal:15,max:15}},audio:this.config.audio}));
            if (finished) { stream.getTracks().forEach(track => track.stop()); return; }
            stream._psynetAudio = this.config.audio;
            this.streams.set(source,stream);
            this.decisions.delete(source);
          } catch (error) {
            if (!finished) this.decisions.set(source,"permission_denied");
            console.warn("Background capture permission unavailable",source,error.name);
          }
          if (sources.every(item => this.streams.has(item) || this.decisions.has(item))) finish();
        };
        dialog.append(button);
      }
      const skip = document.createElement("button");
      skip.type = "button"; skip.textContent = "Continue without recording";
      skip.onclick = finish; dialog.append(skip);
      document.body.append(dialog); dialog.showModal();
    });
  }

  updateIndicator() {
    if (this.indicator) this.indicator.textContent = Object.values(this.clips).some(clip => clip.recorder.state === "recording") ? "Recording" : "Recording stopped";
  }

  stopClip(source) {
    const clip = this.clips[source];
    if (!clip) return;
    clearTimeout(clip.timer);
    try {
      if (clip.recorder.state !== "inactive") clip.recorder.stop();
    } catch (error) {
      console.warn("Could not stop background recording",source,error);
      this.unavailable[source] = "capture_error";
      clip.resolve();
    }
  }

  async finish() {
    if (this.result) return this.result;
    const recordings = {};
    for (const [source, clip] of Object.entries(this.clips)) {
      this.stopClip(source);
      let timer;
      try {
        await Promise.race([clip.done, new Promise(resolve => { timer = setTimeout(() => { this.unavailable[source] = "capture_error"; resolve(); }, 3000); })]);
      } finally { clearTimeout(timer); }
      recordings[source] = this.unavailable[source] ? new Blob([]) : new Blob(clip.chunks,{type:"video/webm"});
      clip.chunks = [];
    }
    const sizes = Object.fromEntries(this.config.sources.map(source => [source,recordings[source]?.size || 0]));
    const prepared = this.queue.prepare(recordings,this.config.max_bytes);
    // More specific capture outcomes take precedence over an empty-blob result.
    this.result = {recordings:prepared.recordings,sizes,unavailable:{...prepared.unavailable,...this.unavailable},outcomes:this.outcomes};
    return this.result;
  }

  async discard() {
    for (const [source,clip] of Object.entries(this.clips)) {
      this.stopClip(source);
      this.streams.get(source)?.getVideoTracks().forEach(track => track.removeEventListener("ended",clip.ended));
      clip.recorder.ondataavailable = null;
      clip.chunks = [];
    }
    this.clips = {};
    this.result = null;
    this.indicator?.remove();
  }
}

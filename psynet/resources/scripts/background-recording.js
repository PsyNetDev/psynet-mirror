import {RecordingDevices, RecordingClip} from "./recording-capture.js";

/** Document-owned optional capture. Tracks survive ordinary SPA page cleanup;
 * each page owns its recorder/chunks. Uploads use the existing media queue.
 */
export class BackgroundRecorder {
  constructor(queue, devices = new RecordingDevices()) {
    this.queue = queue;
    this.devices = devices;
    this.streams = devices.streams;
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
      if (this.devices.reusable(source, config.audio)) return false;
      this.devices.release(source);
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
        await this.devices.acquire(source, {audio:config.audio, lowResolution:true});
        const clip = new RecordingClip(stream, {
          maxBytes:limit, maxDuration:config.max_duration, lowBitrate:true,
          onChange: current => {
            if (current.error) this.unavailable[source] = current.error;
            if (current.outcome) this.outcomes[source] = current.outcome;
            if (current.outcome === "source_ended") this.decisions.set(source, "source_ended");
            this.indicator.dataset.bytes = String(Object.values(this.clips).reduce((sum, item) => sum + item.size, 0));
            this.updateIndicator();
          },
        });
        this.clips[source] = clip;
        clip.startRecording();
        if (clip.error) this.unavailable[source] = clip.error;
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
      text.textContent = this.config.required
        ? "This trial needs camera or screen video. If you continue without recording, your answer is saved but the trial cannot be completed successfully."
        : "This page can record optional camera or screen video. You may continue without recording.";
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
            await this.devices.acquire(source, {audio:this.config.audio, lowResolution:true});
            if (finished) { this.devices.release(source); return; }
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
    if (this.indicator) this.indicator.textContent = Object.values(this.clips).some(clip => clip.getState() === "recording") ? "Recording" : "Recording stopped";
  }

  async finish() {
    if (this.result) return this.result;
    const recordings = {};
    for (const [source, clip] of Object.entries(this.clips)) {
      await clip.stopRecording();
      if (clip.error) this.unavailable[source] = clip.error;
      if (clip.outcome) this.outcomes[source] = clip.outcome;
      recordings[source] = this.unavailable[source] ? new Blob([]) : clip.getBlob();
      clip.chunks = [];
    }
    const sizes = Object.fromEntries(this.config.sources.map(source => [source,recordings[source]?.size || 0]));
    const prepared = this.queue.prepare(recordings,this.config.max_bytes);
    // More specific capture outcomes take precedence over an empty-blob result.
    this.result = {recordings:prepared.recordings,sizes,unavailable:{...prepared.unavailable,...this.unavailable},outcomes:this.outcomes};
    return this.result;
  }

  async discard() {
    for (const clip of Object.values(this.clips)) clip.reset();
    this.clips = {};
    this.result = null;
    this.indicator?.remove();
  }
}

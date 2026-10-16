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
    this.granted = new Set();
    this.clips = {};
  }

  async begin(config) {
    await this.discard();
    this.config = config;
    this.unavailable = {};
    this.outcomes = {};
    this.limits = {};
    this.stoppedForSnapshot = new Set();
    this.indicator = null;
    if (!window.MediaRecorder || !MediaRecorder.isTypeSupported("video/webm")) {
      for (const source of config.sources) this.unavailable[source] = "unsupported";
      return;
    }
    if (this.queue.availableBytes <= 0 || this.queue.availableSlots <= 0) {
      for (const source of config.sources) this.unavailable[source] = "queue_full";
      return;
    }
    const needed = [];
    for (const source of config.sources) {
      if (this.devices.reusable(source, config.audio)) continue;
      if (!this.devices.reusable(source, false)) this.devices.release(source);
      if (config.required) this.decisions.delete(source);
      if (this.decisions.has(source)) continue;
      // Streams are released after pages that do not record. Camera access needs
      // no click once granted, so reacquire it silently; screen sharing always
      // needs the dialog.
      if (source === "camera" && this.granted.has(source)) {
        try {
          await this.devices.acquire(source, {audio:config.audio, lowResolution:true});
          continue;
        } catch (error) {
          console.warn("Could not reacquire the camera", error);
        }
      }
      needed.push(source);
    }
    if (needed.length) await this.askPermission(needed);
    // Divide remaining queue space across sources before recording starts. This
    // bounds capture in addition to retained uploads; chunks arrive each second.
    let remaining = this.queue.availableBytes;
    let slots = this.queue.availableSlots;
    let sourcesLeft = config.sources.length;
    for (const source of config.sources) {
      if (!this.devices.reusable(source, config.audio)) {
        this.unavailable[source] = this.decisions.get(source) || "source_ended";
        continue;
      }
      const limit = Math.min(config.max_bytes, Math.floor(remaining / sourcesLeft--));
      if (limit <= 0 || slots <= 0) { this.unavailable[source] = "queue_full"; continue; }
      remaining -= limit;
      slots -= 1;
      this.limits[source] = limit;
      await this.startClip(source);
    }
    // Show the status chip only when something is actually being recorded.
    if (Object.values(this.clips).some(clip => clip.getState() === "recording")) {
      this.indicator = document.createElement("div");
      this.indicator.id = "background-recording-status";
      this.indicator.setAttribute("role", "status");
      this.indicator.style.cssText = "position:fixed;bottom:12px;right:12px;padding:8px;background:#fff;border:1px solid #777;z-index:1000";
      document.body.append(this.indicator);
    }
    this.updateIndicator();
  }

  async startClip(source) {
    try {
      const captureStream = await this.devices.acquire(source, {audio:this.config.audio, lowResolution:true});
      const clip = new RecordingClip(captureStream, {
        maxBytes:this.limits[source], maxDuration:this.config.max_duration, lowBitrate:true,
        onChange: current => {
          if (this.clips[source] !== clip) return;
          if (current.error) this.unavailable[source] = current.error;
          if (current.outcome) this.outcomes[source] = current.outcome;
          if (current.outcome === "source_ended") this.decisions.set(source, "source_ended");
          if (this.indicator) this.indicator.dataset.bytes = String(Object.values(this.clips).reduce((sum, item) => sum + item.size, 0));
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

  askPermission(sources) {
    return new Promise(resolve => {
      const dialog = document.createElement("dialog");
      dialog.id = "background-recording-permission";
      const text = document.createElement("p");
      text.textContent = this.config.required
        ? this.config.labels.required : this.config.labels.optional;
      dialog.append(text);
      let finished = false;
      const remaining = new Set(sources);
      const finish = () => {
        if (finished) return;
        finished = true;
        for (const source of remaining) this.decisions.set(source,"skipped");
        dialog.close(); dialog.remove(); resolve();
      };
      dialog.addEventListener("cancel", event => { event.preventDefault(); finish(); });
      for (const source of sources) {
        const button = document.createElement("button");
        button.type = "button";
        button.textContent = this.config.labels[source];
        button.onclick = async () => {
          button.disabled = true;
          try {
            // Acquisition is called directly from this click: screen sharing
            // must retain the browser's user activation.
            await this.devices.acquire(source, {audio:this.config.audio, lowResolution:true});
            if (finished) { this.devices.release(source); return; }
            this.decisions.delete(source);
            this.granted.add(source);
          } catch (error) {
            if (!finished) this.decisions.set(source,"permission_denied");
            console.warn("Background capture permission unavailable",source,error.name);
          }
          remaining.delete(source);
          if (!remaining.size) finish();
        };
        dialog.append(button);
      }
      const skip = document.createElement("button");
      skip.type = "button"; skip.textContent = this.config.labels.skip;
      skip.onclick = finish; dialog.append(skip);
      document.body.append(dialog); dialog.showModal();
    });
  }

  updateIndicator() {
    if (this.indicator) this.indicator.textContent = Object.values(this.clips).some(clip => clip.getState() === "recording") ? this.config.labels.recording : this.config.labels.stopped;
  }

  /** Snapshot every clip for a submission without stopping the recording.
   *
   * If the submission is rejected, recording continues and the next submission
   * takes a fresh, longer snapshot (see resume() for a clip that had to stop).
   * A submission whose reply was lost is resent with its original snapshot
   * instead (see psynet.js). The page's clips stop when the next page discards
   * them.
   */
  async finish() {
    const recordings = {};
    for (const [source, clip] of Object.entries(this.clips)) {
      await clip.flush();
      // A recorder that has not produced data yet (an answer within its first
      // moments) only delivers it on stopping.
      if (!clip.size && clip.getState() === "recording") {
        await clip.stopRecording();
        this.stoppedForSnapshot.add(source);
      }
      if (clip.error) this.unavailable[source] = clip.error;
      if (clip.outcome) this.outcomes[source] = clip.outcome;
      recordings[source] = this.unavailable[source] ? new Blob([]) : clip.getBlob();
    }
    const sizes = Object.fromEntries(this.config.sources.map(source => [source,recordings[source]?.size || 0]));
    const prepared = this.queue.prepare(recordings,this.config.max_bytes);
    // More specific capture outcomes take precedence over an empty-blob result.
    return {
      recordings:prepared.recordings,
      sizes,
      unavailable:{...prepared.unavailable,...this.unavailable},
      outcomes:{...this.outcomes},
    };
  }

  /** Restart clips that a rejected submission's snapshot had to stop.
   *
   * The next submission then still records the rest of the page; the moments
   * captured before the rejected snapshot are not kept.
   */
  async resume() {
    for (const source of this.stoppedForSnapshot) {
      if (!this.devices.reusable(source, this.config.audio)) continue;
      this.clips[source].reset();
      delete this.outcomes[source];
      delete this.unavailable[source];
      await this.startClip(source);
    }
    this.stoppedForSnapshot.clear();
    this.updateIndicator();
  }

  async discard() {
    for (const clip of Object.values(this.clips)) clip.reset();
    this.clips = {};
    this.indicator?.remove();
    this.indicator = null;
  }
}

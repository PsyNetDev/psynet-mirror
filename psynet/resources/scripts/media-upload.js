/**
 * Internal transport for accepted recording reservations.
 *
 * The document owns this queue, not a trial or its DOM fragment. Enqueue only
 * after response acceptance and before page cleanup, using the original blob
 * and the server-issued write capability. The caller translates the remaining
 * server deadline to performance.now(); queueing and retries never extend it.
 * Server-side expiry remains authoritative, including after document loss.
 *
 * Failed deliveries are retried until the reservation deadline, never against a
 * fixed attempt count: brief connection losses are common on mobile networks.
 * Network errors and server errors back off exponentially; a 429 means another
 * delivery of the same recording is still being received, so it waits for the
 * server's Retry-After without counting as a failure.
 *
 * A "received" result means complete server receipt, not deposit.
 * Failures are returned to the caller; this module neither fails trials nor
 * recaptures media. Pending jobs warn on manual unload; document navigation
 * initiated by PsyNet drains the queue within the original upload deadlines.
 */
export class MediaUploadQueue {
  constructor({
    concurrency = 2,
    maxBytes = 256 * 1024 * 1024,
    maxPending = 32,
    retryDelay = 500,
    maxRetryDelay = 10000
  } = {}) {
    for (const value of [concurrency, maxBytes, maxPending, retryDelay, maxRetryDelay]) {
      if (!Number.isSafeInteger(value) || value <= 0) {
        throw new TypeError("Upload queue limits must be positive integers.");
      }
    }
    this._limits = { concurrency, maxBytes, maxPending, retryDelay, maxRetryDelay };
    this._jobs = new Map();
    this._active = 0;
    this._pendingBytes = 0;
    this._drains = [];
    this._beforeUnload = event => { event.preventDefault(); event.returnValue = ""; };
  }

  /** Wait for receipt or terminal failure of all outstanding uploads. */
  drain() {
    return this._jobs.size ? new Promise(resolve => this._drains.push(resolve)) : Promise.resolve();
  }

  /** Permit a deliberate early-exit/error redirect without an unload warning. */
  allowUnload() {
    window.removeEventListener("beforeunload", this._beforeUnload);
  }

  get pendingBytes() {
    return this._pendingBytes;
  }

  get availableBytes() {
    return Math.max(0, this._limits.maxBytes - this._pendingBytes);
  }

  get availableSlots() {
    return Math.max(0, this._limits.maxPending - this._jobs.size);
  }

  /** Select files within the shared budget before the single in-flight answer.
   * nextPagePending prevents another submission from adding work until acceptance;
   * existing jobs may only free capacity meanwhile. This does not send any bytes.
   */
  prepare(recordings, maxRecordingBytes) {
    let bytes = this._pendingBytes;
    let count = this._jobs.size;
    const selected = {};
    const unavailable = {};
    for (const [source, blob] of Object.entries(recordings)) {
      if (!(blob instanceof Blob) || blob.size === 0) {
        unavailable[source] = "missing_recording";
      } else if (blob.size > maxRecordingBytes) {
        unavailable[source] = "size_limit";
      } else if (bytes + blob.size > this._limits.maxBytes || count >= this._limits.maxPending) {
        unavailable[source] = "queue_full";
      } else {
        selected[source] = blob;
        bytes += blob.size;
        count += 1;
      }
    }
    return { recordings: selected, unavailable };
  }

  /** Retain a captured file and return its eventual transport outcome. */
  enqueue({ id, url, token, deadline, blob }) {
    const target = new URL(url, window.location.href);
    if (target.origin !== window.location.origin || target.username || target.password) {
      throw new TypeError("Media uploads must use the same origin without URL credentials.");
    }
    if (typeof id !== "string" || !id || typeof token !== "string" || !token ||
        !(blob instanceof Blob) || blob.size === 0 || !Number.isFinite(deadline)) {
      throw new TypeError("An upload needs an ID, capability, nonempty Blob, and finite deadline.");
    }
    if (this._jobs.has(id)) {
      throw new Error("A recording with this ID is already queued.");
    }
    const remaining = deadline - performance.now();
    if (remaining <= 0) {
      return Promise.resolve({ status: "failed", reason: "deadline" });
    }
    if (remaining > 2147483647) {
      throw new RangeError("Upload deadline exceeds the browser timer limit.");
    }
    if (this._pendingBytes + blob.size > this._limits.maxBytes ||
        this._jobs.size >= this._limits.maxPending) {
      return Promise.resolve({ status: "failed", reason: "queue_full" });
    }
    const job = { id, url: target.href, token, deadline, blob, attempts: 0, failures: 0, active: false, done: false };
    const result = new Promise((resolve) => { job.resolve = resolve; });
    this._jobs.set(id, job);
    window.addEventListener("beforeunload", this._beforeUnload);
    this._pendingBytes += blob.size;
    job.deadlineTimer = setTimeout(() => {
      this._finish(job, { status: "failed", reason: "deadline" });
    }, remaining);
    this._pump();
    return result;
  }

  /** Start ready jobs without tying their lifetime to page navigation. */
  _pump() {
    for (const job of this._jobs.values()) {
      if (this._active >= this._limits.concurrency) return;
      if (job.active || job.retryTimer) continue;
      if (performance.now() >= job.deadline) {
        this._finish(job, { status: "failed", reason: "deadline" });
        continue;
      }
      job.active = true;
      this._active += 1;
      void this._send(job);
    }
  }

  /** Retry delivery of these same bytes; never request another recording. */
  async _send(job) {
    job.attempts += 1;
    job.controller = new AbortController();
    try {
      const response = await fetch(job.url, {
        method: "POST",
        headers: { Authorization: `Bearer ${job.token}` },
        body: job.blob,
        signal: job.controller.signal,
        credentials: "same-origin",
        redirect: "error"
      });
      if (job.done) return;
      if (performance.now() >= job.deadline) {
        this._finish(job, { status: "failed", reason: "deadline" });
      } else if (response.ok) {
        this._finish(job, { status: "received" });
      } else if (response.status === 429) {
        this._retry(job, retryAfterMilliseconds(response.headers.get("Retry-After")));
      } else if ([408, 500, 502, 503, 504].includes(response.status)) {
        this._retry(job);
      } else {
        this._finish(job, { status: "failed", reason: "http_error", httpStatus: response.status });
      }
    } catch (error) {
      if (!job.done) {
        // The reservation deadline, rather than a short per-attempt timer,
        // bounds slow transfers. Retry only when delivery actually fails.
        if (error instanceof TypeError || error.name === "AbortError") {
          this._retry(job);
        } else {
          console.warn("Unexpected media upload failure", error);
          this._finish(job, { status: "failed", reason: "request_error" });
        }
      }
    } finally {
      job.controller.abort();
      job.controller = null;
      job.active = false;
      this._active -= 1;
      this._pump();
    }
  }

  /** Wait before resending, bounded by the reservation deadline.
   *
   * A server-provided wait (429 Retry-After) is honoured as given and does not
   * count as a failure; other failures double the delay up to maxRetryDelay.
   */
  _retry(job, serverDelay = null) {
    const remaining = job.deadline - performance.now();
    if (remaining <= 0) {
      this._finish(job, { status: "failed", reason: "deadline" });
      return;
    }
    let delay = serverDelay;
    if (delay === null) {
      job.failures += 1;
      delay = Math.min(this._limits.maxRetryDelay, this._limits.retryDelay * 2 ** (job.failures - 1));
    }
    job.retryTimer = setTimeout(() => {
      job.retryTimer = null;
      this._pump();
    }, Math.min(delay, remaining));
  }

  /** Resolve once and release retained bytes and credentials on every outcome. */
  _finish(job, result) {
    if (job.done) return;
    job.done = true;
    clearTimeout(job.deadlineTimer);
    clearTimeout(job.retryTimer);
    job.controller?.abort();
    this._jobs.delete(job.id);
    this._pendingBytes -= job.blob.size;
    job.blob = null;
    job.token = null;
    job.resolve(result);
    if (!this._jobs.size) {
      window.removeEventListener("beforeunload", this._beforeUnload);
      this._drains.splice(0).forEach(resolve => resolve());
    }
  }
}

/** Convert a Retry-After header (seconds or HTTP date) to milliseconds, or null. */
function retryAfterMilliseconds(header) {
  if (!header) return null;
  const seconds = Number(header);
  if (Number.isFinite(seconds)) return Math.max(0, seconds * 1000);
  const date = Date.parse(header);
  return Number.isFinite(date) ? Math.max(0, date - Date.now()) : null;
}

/**
 * Internal transport for accepted recording reservations.
 *
 * The document owns this queue, not a trial or its DOM fragment. Enqueue only
 * after response acceptance and before page cleanup, using the original blob
 * and the server-issued write capability. The caller translates the server's
 * lifetime cap to performance.now(); the queue never holds bytes beyond it.
 *
 * The server expires a pending recording once its lease lapses, so while jobs
 * remain the queue sends heartbeats that renew their leases: a slow upload is
 * not failed while this document is open. Server-side expiry remains
 * authoritative, including after document loss.
 *
 * Failed deliveries are retried until the server reports the recording expired
 * or the lifetime cap passes, never against a fixed attempt count: brief
 * connection losses are common on mobile networks.
 * Network errors and server errors back off exponentially; a 429 means another
 * delivery of the same recording is still being received, so it waits for the
 * server's Retry-After without counting as a failure.
 *
 * A "received" result means complete server receipt, not deposit.
 * Failures are returned to the caller; this module neither fails trials nor
 * recaptures media. Pending jobs warn on manual unload; document navigation
 * initiated by PsyNet drains the queue.
 */
// Consecutive internal server errors after which an upload is given up.
const MAX_SERVER_ERRORS = 5;

export class MediaUploadQueue {
  constructor({
    concurrency = 2,
    maxBytes = 256 * 1024 * 1024,
    maxPending = 32,
    retryDelay = 500,
    maxRetryDelay = 10000,
    heartbeatInterval = 30000,
    heartbeatUrl = "/media-upload/heartbeat"
  } = {}) {
    for (const value of [concurrency, maxBytes, maxPending, retryDelay, maxRetryDelay, heartbeatInterval]) {
      if (!Number.isSafeInteger(value) || value <= 0) {
        throw new TypeError("Upload queue limits must be positive integers.");
      }
    }
    this._limits = { concurrency, maxBytes, maxPending, retryDelay, maxRetryDelay, heartbeatInterval };
    this._heartbeatUrl = heartbeatUrl;
    this._heartbeatTimer = null;
    this._heartbeatEvery = null;
    this._jobs = new Map();
    this._active = 0;
    this._pendingBytes = 0;
    this._drains = [];
    this._groupWaiters = [];
    this._beforeUnload = event => { event.preventDefault(); event.returnValue = ""; };
  }

  /** Wait for receipt or terminal failure of all outstanding uploads. */
  drain() {
    return this._jobs.size ? new Promise(resolve => this._drains.push(resolve)) : Promise.resolve();
  }

  /** Number of distinct pages (groups) whose uploads are still outstanding. */
  get pendingGroups() {
    return new Set(Array.from(this._jobs.values(), job => job.group)).size;
  }

  /** Whether another page's recordings may be submitted now: at most one
   * earlier page still has uploads outstanding, and these recordings fit.
   */
  hasRoom(recordings, maxRecordingBytes) {
    const groups = this.pendingGroups;
    return groups === 0 || (groups === 1 &&
      !Object.values(this.prepare(recordings, maxRecordingBytes).unavailable).includes("queue_full"));
  }

  /** Wait, as earlier pages' uploads finish, until hasRoom() holds. */
  async waitForRoom(recordings, maxRecordingBytes) {
    while (!this.hasRoom(recordings, maxRecordingBytes)) {
      const maxGroups = this.pendingGroups - 1;
      await new Promise(resolve => this._groupWaiters.push({ maxGroups, resolve }));
    }
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
   * Only one submission is in flight at a time, so existing jobs can only free
   * capacity before its recordings are enqueued. This does not send any bytes.
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

  /** Retain a captured file and return its eventual transport outcome.
   *
   * ``group`` identifies the submitted page, for hasRoom() and waitForRoom().
   * ``renewInterval`` (ms) must be well within the server's lease timeout.
   */
  enqueue({ id, url, token, deadline, blob, group = id, renewInterval = this._limits.heartbeatInterval }) {
    const target = new URL(url, window.location.href);
    if (target.origin !== window.location.origin || target.username || target.password) {
      throw new TypeError("Media uploads must use the same origin without URL credentials.");
    }
    if (typeof id !== "string" || !id || typeof token !== "string" || !token ||
        !(blob instanceof Blob) || blob.size === 0 || !Number.isFinite(deadline) ||
        !Number.isSafeInteger(renewInterval) || renewInterval <= 0) {
      throw new TypeError("An upload needs an ID, capability, nonempty Blob, finite deadline, and renewal interval.");
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
    const job = { id, url: target.href, token, deadline, blob, group, attempts: 0, failures: 0, serverErrors: 0, active: false, done: false };
    const result = new Promise((resolve) => { job.resolve = resolve; });
    this._jobs.set(id, job);
    window.addEventListener("beforeunload", this._beforeUnload);
    this._pendingBytes += blob.size;
    job.deadlineTimer = setTimeout(() => {
      this._finish(job, { status: "failed", reason: "deadline" });
    }, remaining);
    if (this._heartbeatTimer === null || renewInterval < this._heartbeatEvery) {
      clearInterval(this._heartbeatTimer);
      this._heartbeatEvery = renewInterval;
      this._heartbeatTimer = setInterval(() => void this._heartbeat(), renewInterval);
    }
    this._pump();
    return result;
  }

  /** Renew the server leases of outstanding jobs; release ones it has expired. */
  async _heartbeat() {
    const uploads = Array.from(this._jobs.values(), job => ({ id: job.id, token: job.token }));
    if (!uploads.length) return;
    try {
      const response = await fetch(this._heartbeatUrl, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ uploads }),
        credentials: "same-origin",
        redirect: "error"
      });
      if (!response.ok) return;
      const { unavailable = [] } = await response.json();
      for (const id of unavailable) {
        const job = this._jobs.get(id);
        if (job) this._finish(job, { status: "failed", reason: "expired" });
      }
    } catch (error) {
      // A missed heartbeat is retried at the next interval; the server lease
      // outlasts several intervals.
      console.debug("Media upload heartbeat failed", error);
    }
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
      } else if (response.status === 500 && ++job.serverErrors >= MAX_SERVER_ERRORS) {
        // Heartbeats keep the lease alive, so a persistent receiver fault
        // would otherwise hold the participant until the lifetime cap.
        this._finish(job, { status: "failed", reason: "http_error", httpStatus: 500 });
      } else if ([408, 500, 502, 503, 504].includes(response.status)) {
        if (response.status !== 500) job.serverErrors = 0;
        this._retry(job);
      } else {
        this._finish(job, { status: "failed", reason: "http_error", httpStatus: response.status });
      }
    } catch (error) {
      if (!job.done) {
        // The server stops a stalled transfer, so no per-attempt timer is
        // needed here. Retry only when delivery actually fails.
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

  /** Wait before resending, bounded by the lifetime cap.
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
    const groups = this.pendingGroups;
    this._groupWaiters = this._groupWaiters.filter(waiter => {
      if (groups > waiter.maxGroups) return true;
      waiter.resolve();
      return false;
    });
    if (!this._jobs.size) {
      clearInterval(this._heartbeatTimer);
      this._heartbeatTimer = null;
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

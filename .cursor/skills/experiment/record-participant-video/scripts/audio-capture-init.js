// In-page audio capture for headless Playwright participant recordings.
//
// Installed by audio-capture.cjs with context.addInitScript, so it runs before
// any page script. Headless Chromium plays audio to no device, so this script
// records what the page *would* play:
//
// - Every AudioNode connected to an AudioContext destination is also connected
//   to a MediaStreamAudioDestinationNode for that context.
// - <audio>/<video> playback is tapped with HTMLMediaElement.captureStream(),
//   unless the page already routes the element into Web Audio with
//   createMediaElementSource (then the destination tap hears it).
// - All taps are bridged into one always-running mixing AudioContext per
//   document. Its clock keeps silent gaps in the recording; recording each
//   source separately drops the gaps and misaligns the sources.
// - One MediaRecorder (Opus/WebM, 100 ms chunks) per document streams chunks to
//   Node through the exposed binding. It starts when the page first creates an
//   AudioContext or plays media, so silent pages produce no audio. A full page
//   load starts a new segment.
//
// Only the top-level document is captured; audio in iframes is not recorded.
(() => {
  const BINDING = "__psynetAudioCaptureChunk";
  if (window.top !== window || window.__psynetAudioCapture) return;
  const NativeContext = window.AudioContext || window.webkitAudioContext;
  if (!NativeContext || !window.MediaRecorder || !window[BINDING]) return;

  const nativeConnect = AudioNode.prototype.connect;
  const nativeDisconnect = AudioNode.prototype.disconnect;
  const documentId = Math.random().toString(36).slice(2);
  const taps = new WeakMap(); // page AudioContext -> MediaStreamAudioDestinationNode
  const mediaSources = new Map(); // HTMLMediaElement -> source nodes in mixContext
  const webAudioElements = new WeakSet();
  const pendingSends = new Set();
  let mixContext = null;
  let mix = null;
  let recorder = null;
  let segment = null;

  function send(message) {
    const sent = Promise.resolve()
      .then(() => window[BINDING]({ url: location.href, segment, ...message }))
      .catch((error) => console.warn("[psynet audio capture] could not send audio chunk", error));
    pendingSends.add(sent);
    sent.finally(() => pendingSends.delete(sent));
    return sent;
  }

  function toBase64(buffer) {
    const bytes = new Uint8Array(buffer);
    let text = "";
    for (let i = 0; i < bytes.length; i += 0x8000) {
      text += String.fromCharCode.apply(null, bytes.subarray(i, i + 0x8000));
    }
    return btoa(text);
  }

  function startRecorder() {
    if (recorder) return;
    segment = `${documentId}-mix`;
    recorder = new MediaRecorder(mix.stream, {
      mimeType: "audio/webm;codecs=opus",
      audioBitsPerSecond: 128000,
    });
    let sequence = 0;
    recorder.onstart = () =>
      send({ kind: "start", wallMs: performance.timeOrigin + performance.now() });
    recorder.ondataavailable = (event) => {
      if (!event.data.size) return;
      const n = sequence++;
      const sent = event.data.arrayBuffer().then((buffer) =>
        send({ kind: "chunk", seq: n, data: toBase64(buffer) }),
      );
      pendingSends.add(sent);
      sent.finally(() => pendingSends.delete(sent));
    };
    recorder.start(100);
  }

  function ensureMix() {
    if (mixContext) return;
    mixContext = new NativeContext();
    mix = mixContext.createMediaStreamDestination();
    if (mixContext.state === "running") {
      startRecorder();
      return;
    }
    // Without --autoplay-policy=no-user-gesture-required, a context created
    // outside a user gesture starts suspended; retry on the next gesture.
    const resume = () =>
      mixContext.resume().then(() => {
        if (mixContext.state !== "running") return;
        removeEventListener("pointerdown", resume, true);
        removeEventListener("keydown", resume, true);
        startRecorder();
      });
    addEventListener("pointerdown", resume, true);
    addEventListener("keydown", resume, true);
    resume();
  }

  // Start the recorder when the page creates an AudioContext, not at the first
  // connect(): MediaRecorder takes tens of ms to start, which would clip the
  // first sound on each page.
  function patchContextConstructor(name) {
    const Native = window[name];
    if (!Native) return;
    const Patched = class extends Native {
      constructor(...args) {
        super(...args);
        ensureMix();
      }
    };
    Object.defineProperty(Patched, "name", { value: Native.name });
    window[name] = Patched;
  }
  patchContextConstructor("AudioContext");
  patchContextConstructor("webkitAudioContext");

  function tapFor(context) {
    // OfflineAudioContext renders to a buffer, not to speakers.
    if (context === mixContext || typeof context.createMediaStreamDestination !== "function") {
      return null;
    }
    let tap = taps.get(context);
    if (!tap) {
      tap = context.createMediaStreamDestination();
      taps.set(context, tap);
      ensureMix();
      mixContext.createMediaStreamSource(tap.stream).connect(mix);
    }
    return tap;
  }

  AudioNode.prototype.connect = function (destination, output) {
    const result = nativeConnect.apply(this, arguments);
    if (destination instanceof AudioDestinationNode) {
      const tap = tapFor(destination.context);
      if (tap) nativeConnect.call(this, tap, output || 0);
    }
    return result;
  };

  AudioNode.prototype.disconnect = function (destination) {
    const result = nativeDisconnect.apply(this, arguments);
    const tap = taps.get(this.context);
    const args = Array.from(arguments);
    const tapArgs =
      args.length === 0
        ? [tap]
        : typeof destination === "number"
          ? [tap, ...args]
          : destination instanceof AudioDestinationNode
            ? [tap, ...args.slice(1)]
            : null;
    if (tap && tapArgs) {
      try {
        nativeDisconnect.apply(this, tapArgs);
      } catch (error) {
        // The node was never connected to the tap (e.g. connected before capture started).
      }
    }
    return result;
  };

  function patchCreateMediaElementSource(Context) {
    const native = Context && Context.prototype.createMediaElementSource;
    if (!native) return;
    Context.prototype.createMediaElementSource = function (element) {
      webAudioElements.add(element);
      (mediaSources.get(element) || []).forEach((source) => source.disconnect());
      mediaSources.delete(element);
      return native.apply(this, arguments);
    };
  }
  patchCreateMediaElementSource(NativeContext);

  const tappedElements = new WeakSet();
  function tapMediaElement(element) {
    if (!(element instanceof HTMLMediaElement) || !element.captureStream) return;
    if (tappedElements.has(element) || webAudioElements.has(element)) return;
    tappedElements.add(element);
    const stream = element.captureStream();
    const trackIds = new Set();
    // Tracks already present can also fire "addtrack"; mixing one twice doubles its level.
    const addTrack = (track) => {
      if (track.kind !== "audio" || trackIds.has(track.id) || webAudioElements.has(element)) return;
      trackIds.add(track.id);
      ensureMix();
      const source = mixContext.createMediaStreamSource(new MediaStream([track]));
      source.connect(mix);
      mediaSources.set(element, [...(mediaSources.get(element) || []), source]);
    };
    stream.getAudioTracks().forEach(addTrack);
    stream.addEventListener("addtrack", (event) => addTrack(event.track));
  }

  const nativePlay = HTMLMediaElement.prototype.play;
  HTMLMediaElement.prototype.play = function () {
    tapMediaElement(this);
    return nativePlay.apply(this, arguments);
  };
  document.addEventListener("play", (event) => tapMediaElement(event.target), true);

  async function flush() {
    if (recorder && recorder.state !== "inactive") {
      const stopped = new Promise((resolve) => (recorder.onstop = resolve));
      recorder.stop();
      await stopped;
    }
    while (pendingSends.size) await Promise.all([...pendingSends]);
  }

  addEventListener("pagehide", () => {
    if (recorder && recorder.state !== "inactive") recorder.stop();
  });

  window.__psynetAudioCapture = { documentId, flush };
})();

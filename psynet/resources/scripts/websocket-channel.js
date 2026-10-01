(function () {
  "use strict";

  const channels = new Map();
  const LISTENING_PROBE_TYPE = "psynet_listening_probe";

  function buildUrl(channel) {
    const scheme = location.protocol === "https:" ? "wss://" : "ws://";
    return (
      scheme +
      location.host +
      "/chat?channel=" +
      encodeURIComponent(channel) +
      "&worker_id=" +
      encodeURIComponent(dallinger.identity.workerId) +
      "&participant_id=" +
      encodeURIComponent(dallinger.identity.participantId)
    );
  }

  function markListening(entry, event) {
    entry.listening = true;
    entry.subscribers.forEach((subscriber) => subscriber.onOpen?.(event));
  }

  // Dallinger subscribes the server to Redis after the socket opens, so
  // messages published in between are dropped. Our own probe echoing back
  // proves the subscription is live.
  function sendListeningProbe(entry, event) {
    entry.probeId = Math.random().toString(36).slice(2);
    entry.probeEvent = event;
    entry.socket.send(
      entry.channel +
        ":" +
        JSON.stringify({ type: LISTENING_PROBE_TYPE, probe_id: entry.probeId }),
    );
  }

  function createChannel(channel, confirmListening) {
    const subscribers = new Set();
    const socket = new ReconnectingWebSocket(buildUrl(channel));
    const entry = {
      channel,
      confirmListening,
      keepAlive: false,
      listening: false,
      probeEvent: null,
      probeId: null,
      socket,
      subscribers,
    };

    socket.onopen = function (event) {
      entry.listening = false;
      if (entry.confirmListening) {
        sendListeningProbe(entry, event);
      } else {
        markListening(entry, event);
      }
    };
    socket.onmessage = function (event) {
      if (event.data.indexOf(channel + ":") !== 0) {
        return;
      }
      let message;
      try {
        message = JSON.parse(event.data.slice(channel.length + 1));
      } catch (error) {
        console.warn(`Ignored malformed JSON on WebSocket channel "${channel}".`);
        return;
      }
      if (message?.type === LISTENING_PROBE_TYPE) {
        if (!entry.listening && message.probe_id === entry.probeId) {
          markListening(entry, entry.probeEvent);
        }
        return;
      }
      subscribers.forEach((subscriber) => subscriber.onMessage?.(message));
    };
    socket.onclose = function (event) {
      entry.listening = false;
      subscribers.forEach((subscriber) => subscriber.onClose?.(event));
    };

    channels.set(channel, entry);
    return entry;
  }

  function closeChannel(entry) {
    channels.delete(entry.channel);
    entry.socket.onopen = function () {
      entry.socket.close();
    };
    entry.socket.onmessage = function () {};
    entry.socket.onclose = function () {};
    entry.socket.close();
  }

  /**
   * Subscribe to a WebSocket channel, sharing one socket per channel name.
   *
   * With ``confirmListening``, ``onOpen`` and ``isOpen()`` wait until the
   * server is relaying the channel, so a state check in ``onOpen`` cannot miss
   * a message published during connection. The first ``connect`` for a
   * channel decides this. Probes are published on the channel itself, so only
   * use it on channels without server-side message handlers.
   */
  function connect({
    channel,
    keepAlive = false,
    confirmListening = false,
    onOpen,
    onMessage,
    onClose,
  }) {
    if (!channel) {
      throw new Error("A WebSocket channel name is required.");
    }

    const entry =
      channels.get(channel) || createChannel(channel, confirmListening);
    entry.keepAlive ||= keepAlive;
    let closed = false;
    let subscriber;
    const connection = {
      close() {
        if (closed) return;
        closed = true;
        entry.subscribers.delete(subscriber);
        if (entry.subscribers.size === 0 && !entry.keepAlive) {
          closeChannel(entry);
        }
      },
      isOpen() {
        return (
          !closed &&
          entry.listening &&
          entry.socket.readyState === WebSocket.OPEN
        );
      },
      send(message) {
        if (closed) {
          throw new Error(`WebSocket channel "${channel}" is closed.`);
        }
        if (entry.socket.readyState !== WebSocket.OPEN) {
          throw new Error(`WebSocket channel "${channel}" is not open.`);
        }
        entry.socket.send(channel + ":" + JSON.stringify(message));
      },
    };
    subscriber = {
      onOpen: (event) => {
        if (!closed && onOpen) onOpen(event, connection);
      },
      onMessage: (message) => {
        if (!closed && onMessage) onMessage(message, connection);
      },
      onClose: (event) => {
        if (!closed && onClose) onClose(event, connection);
      },
    };
    entry.subscribers.add(subscriber);
    if (entry.listening && entry.socket.readyState === WebSocket.OPEN) {
      setTimeout(() => subscriber.onOpen({ isReconnect: false }), 0);
    }

    return connection;
  }

  window.PsyNetWebSocketChannel = { connect };
})();

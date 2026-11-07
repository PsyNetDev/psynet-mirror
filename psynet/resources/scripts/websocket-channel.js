(function () {
  "use strict";

  const channels = new Map();
  const LISTENING_PROBE_TYPE = "psynet_listening_probe";
  const LISTENING_PROBE_RETRY_MS = 1000;
  const DIRECT_PREFIX = "dallinger_direct:";

  function buildUrl(channel) {
    const scheme = location.protocol === "https:" ? "wss://" : "ws://";
    return (
      scheme +
      location.host +
      "/chat?channel=" +
      encodeURIComponent(channel) +
      "&participant_id=" +
      encodeURIComponent(dallinger.identity.participantId) +
      "&scope=" +
      encodeURIComponent(psynetTemplateData.websocketScope)
    );
  }

  function stopListeningProbe(entry) {
    clearInterval(entry.probeTimer);
    entry.probeTimer = null;
  }

  function markListening(entry, event) {
    stopListeningProbe(entry);
    entry.listening = true;
    entry.subscribers.forEach((subscriber) => subscriber.onOpen?.(event));
  }

  // Dallinger subscribes the server to Redis after the socket opens, so
  // messages published in between are dropped. Our own probe echoing back
  // proves the subscription is live. A probe published before the
  // subscription is dropped too, so it is repeated until one echoes.
  function sendListeningProbe(entry, event) {
    stopListeningProbe(entry);
    entry.probeId = Math.random().toString(36).slice(2);
    entry.probeEvent = event;
    const payload =
      entry.channel +
      ":" +
      JSON.stringify({ type: LISTENING_PROBE_TYPE, probe_id: entry.probeId });
    entry.socket.send(payload);
    entry.probeTimer = setInterval(() => {
      if (entry.socket.readyState === WebSocket.OPEN) {
        entry.socket.send(payload);
      }
    }, LISTENING_PROBE_RETRY_MS);
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
      probeTimer: null,
      socket,
      subscribers,
    };

    dallinger.stopReconnectingIfRefused(socket, (code, reason) => {
      console.warn(
        `The server refused WebSocket channel "${channel}" (code ${code}: ${reason}); not reconnecting.`,
      );
    });
    socket.onopen = function (event) {
      entry.listening = false;
      if (entry.confirmListening) {
        sendListeningProbe(entry, event);
      } else {
        markListening(entry, event);
      }
    };
    socket.onmessage = function (event) {
      let direct = event.data.indexOf(DIRECT_PREFIX) === 0;
      if (!direct && event.data.indexOf(channel + ":") !== 0) {
        return;
      }
      let message;
      try {
        message = JSON.parse(
          event.data.slice(direct ? DIRECT_PREFIX.length : channel.length + 1),
        );
      } catch (error) {
        console.warn(`Ignored malformed JSON on WebSocket channel "${channel}".`);
        return;
      }
      if (direct) {
        subscribers.forEach((subscriber) => subscriber.onDirect?.(message));
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
      stopListeningProbe(entry);
      entry.listening = false;
      subscribers.forEach((subscriber) => subscriber.onClose?.(event));
    };

    channels.set(channel, entry);
    return entry;
  }

  function closeChannel(entry) {
    channels.delete(entry.channel);
    stopListeningProbe(entry);
    entry.socket.onopen = function () {
      entry.socket.close();
    };
    entry.socket.onmessage = function () {};
    entry.socket.onclose = function () {};
    // ReconnectingWebSocket has no way to cancel a scheduled reconnect, which
    // calls open() when it fires.
    entry.socket.open = function () {};
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
   *
   * ``onMessage`` receives what any page publishes on the channel, so never
   * trust it. ``onDirect`` receives what the server sends this participant
   * with ``publish_to_participants``; PsyNet accepts the socket only with the
   * participant's token, so only they get it. Directed frames can arrive
   * before ``onOpen`` runs. Dallinger registers a socket
   * for directed sends before it reads the socket's frames, so a probe echo
   * normally means directed sends reach it too; if Dallinger's listener is
   * slow to confirm, it proceeds anyway, and the hold's safety poll covers a
   * missed wake.
   *
   * If the server refuses the socket (close code 1008), the channel logs a
   * warning and stops reconnecting. Other close codes reconnect as before.
   */
  function connect({
    channel,
    keepAlive = false,
    confirmListening = false,
    onOpen,
    onMessage,
    onDirect,
    onClose,
  }) {
    if (!channel) {
      throw new Error("A WebSocket channel name is required.");
    }
    if (confirmListening && channel.includes(":")) {
      // Dallinger takes everything before the first colon of a browser
      // message as the channel, so the probe would never echo back.
      throw new Error(
        `confirmListening needs a channel name without ":" (got "${channel}").`,
      );
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
      onDirect: (message) => {
        if (!closed && onDirect) onDirect(message, connection);
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

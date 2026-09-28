(function () {
  "use strict";

  const channels = new Map();

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

  function createChannel(channel) {
    const subscribers = new Set();
    const socket = new ReconnectingWebSocket(buildUrl(channel));
    const entry = { channel, keepAlive: false, socket, subscribers };

    socket.onopen = function (event) {
      subscribers.forEach((subscriber) => subscriber.onOpen?.(event));
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
      subscribers.forEach((subscriber) => subscriber.onMessage?.(message));
    };
    socket.onclose = function (event) {
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

  function connect({ channel, keepAlive = false, onOpen, onMessage, onClose }) {
    if (!channel) {
      throw new Error("A WebSocket channel name is required.");
    }

    const entry = channels.get(channel) || createChannel(channel);
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
        return !closed && entry.socket.readyState === WebSocket.OPEN;
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
    if (entry.socket.readyState === WebSocket.OPEN) {
      setTimeout(() => subscriber.onOpen({ isReconnect: false }), 0);
    }

    return connection;
  }

  window.PsyNetWebSocketChannel = { connect };
})();

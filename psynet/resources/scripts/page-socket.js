(function () {
  "use strict";

  /**
   * The channel ``psynet.websocket`` sends on, which the experiment's
   * ``handle_websocket_message`` gets as its ``channel_name``.
   */
  const CHANNEL = "psynet";

  /**
   * Create the page's connection to the experiment, on Dallinger's
   * ``/experiment-socket`` route, which ``psynet.js`` makes available as
   * ``psynet.websocket``.
   *
   * The connection opens when the page first sends a message or registers a
   * handler, and gives the page's token as its scope. Dallinger reconnects
   * it whenever it drops, and holds messages sent in the meantime. A
   * connection the server refuses stays closed, and sends on it are dropped.
   *
   * Handlers, ``onConnect`` callbacks and the message context belong to the
   * page that registered them. When the page's token changes, they are
   * discarded with the earlier page's connection.
   *
   * Each message is a JSON object with a ``type``, and a ``message`` unless
   * there is nothing to send. ``handle`` passes each message the experiment
   * sends the participant to the callbacks for its ``type``.
   *
   * @param {function} pageToken - Returns the current page's token
   */
  function createPageSocket(pageToken) {
    let page = null;

    function dispatch(state, data) {
      if (data === null || typeof data !== "object") return;
      let message = Object.prototype.hasOwnProperty.call(data, "message")
        ? data.message
        : data;
      (state.handlers.get(data.type) || []).slice().forEach((callback) => {
        try {
          callback(message, data);
        } catch (error) {
          console.error(error);
        }
      });
    }

    function currentPage() {
      let token = pageToken();
      if (!token) {
        throw new Error(
          "This page has no page token, so it can't open a websocket. " +
            "The server needs a FLASK_SECRET_KEY.",
        );
      }
      if (page === null || page.token !== token) {
        close();
        page = {
          token: token,
          socket: null,
          openEvent: null,
          handlers: new Map(),
          connectHandlers: [],
          context: {},
        };
      }
      return page;
    }

    function connect() {
      let state = currentPage();
      if (state.socket === null) {
        state.socket = dallinger.openExperimentSocket({ scope: state.token });
        state.socket.onDirect((data) => dispatch(state, data));
        state.socket.onOpen(function (event) {
          state.openEvent = event;
          state.connectHandlers.slice().forEach((callback) => callback(event));
        });
      }
      return state.socket;
    }

    function send(type, message) {
      let context = currentPage().context;
      if (
        message &&
        typeof message === "object" &&
        !Array.isArray(message) &&
        Object.keys(context).length > 0
      ) {
        message = Object.assign({}, context, message);
      }
      let data = { type: type };
      if (message !== undefined) {
        data.message = message;
      }
      connect().send(CHANNEL, data);
    }

    function handle(type, callback) {
      connect();
      let handlers = page.handlers;
      if (!handlers.has(type)) handlers.set(type, []);
      handlers.get(type).push(callback);
      return function () {
        handlers.set(
          type,
          (handlers.get(type) || []).filter((x) => x !== callback),
        );
      };
    }

    function onConnect(callback) {
      let socket = connect();
      let state = page;
      state.connectHandlers.push(callback);
      if (socket.raw.readyState === WebSocket.OPEN) {
        setTimeout(function () {
          if (state.connectHandlers.includes(callback)) callback(state.openEvent);
        }, 0);
      }
      return function () {
        state.connectHandlers = state.connectHandlers.filter((x) => x !== callback);
      };
    }

    function setMessageContext(context) {
      let state = currentPage();
      state.context = Object.assign({}, state.context, context || {});
    }

    function close() {
      if (page !== null && page.socket !== null) {
        let closing = page.socket;
        page.socket = null;
        page.openEvent = null;
        closing.close();
      }
    }

    function resetPageState() {
      close();
      page = null;
    }

    return {
      connect: connect,
      close: close,
      handle: handle,
      onConnect: onConnect,
      resetPageState: resetPageState,
      send: send,
      setMessageContext: setMessageContext,
    };
  }

  window.PsyNetPageSocket = { CHANNEL: CHANNEL, create: createPageSocket };
})();

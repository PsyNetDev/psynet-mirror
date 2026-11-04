(function () {
  "use strict";

  /**
   * The channel ``psynet.websocket`` sends on. The experiment's
   * ``handle_websocket_message`` gets it as its ``channel_name``.
   */
  const CHANNEL = "psynet";

  /**
   * The ``type`` of the message PsyNet sends a page once the participant has
   * moved on from it, for example the same page left open in another tab.
   * The page's connection closes for good when it arrives, and no handler
   * sees it, so don't give your own messages this type.
   */
  const PAGE_ENDED = "psynet_page_ended";

  /**
   * Keeps the current page's state and its Dallinger socket, which opens
   * when first asked for. When the page token changes, or ``reset`` runs,
   * the old page's socket closes and the next call starts the new page
   * afresh. ``psynet.websocket`` and ``psynet.liveSession`` are built on it.
   *
   * @param {function} pageToken - Returns the current page's token
   * @param {Object} options
   * @param {string} options.noTokenError - The error's message when the
   *   page has no token
   * @param {function} [options.newPage] - Returns the fields a new page's
   *   state starts with, besides its ``token`` and ``socket``
   * @param {function} options.open - Opens the socket for the page's state
   * @returns {{current: function, socket: function, close: function,
   *   reset: function}} ``current`` returns the page's state, ``socket`` its
   *   socket, ``close`` closes the socket, so that the next ``socket`` call
   *   opens another, and ``reset`` also forgets the page
   */
  function createPageScopedSocket(pageToken, options) {
    let page = null;

    function current() {
      let token = pageToken();
      if (!token) {
        throw new Error(options.noTokenError);
      }
      if (page === null || page.token !== token) {
        close();
        page = Object.assign(
          { token: token, socket: null },
          options.newPage ? options.newPage() : {},
        );
      }
      return page;
    }

    function socket() {
      let state = current();
      if (state.socket === null) {
        state.socket = options.open(state);
      }
      return state.socket;
    }

    function close() {
      if (page !== null && page.socket !== null) {
        let closing = page.socket;
        page.socket = null;
        closing.close();
      }
    }

    function reset() {
      close();
      page = null;
    }

    return { current: current, socket: socket, close: close, reset: reset };
  }

  /**
   * ``psynet.websocket`` lets a page and the experiment send each other
   * messages while the page is open, without the participant submitting it.
   * A page sends with ``send`` and receives with ``handle``. Each message has
   * a ``type``, a name the page and the experiment agree on, and usually a
   * ``message``, the data that goes with it.
   *
   * The connection opens when the page first sends a message or registers a
   * handler. If it drops, it reconnects by itself, and messages sent in the
   * meantime go once it's back. Only the page the participant is on can
   * connect. Once the participant moves on, the earlier page's connection
   * closes and stops sending, and so does the same page left open in another
   * tab. Handlers and ``onConnect`` callbacks belong to the page that
   * registered them, and go with it.
   *
   * ``psynet.js`` creates ``psynet.websocket`` with this function. The
   * connection is Dallinger's ``/experiment-socket``, with the page's token
   * as its scope, which the experiment's ``accept_websocket_connection``
   * checks.
   *
   * @param {function} pageToken - Returns the current page's token
   */
  function createPageSocket(pageToken) {
    let pages = createPageScopedSocket(pageToken, {
      noTokenError:
        "This page has no page token, so it can't open a websocket. " +
        "The server needs a FLASK_SECRET_KEY.",
      newPage: () => ({
        openEvent: null,
        handlers: new Map(),
        connectHandlers: [],
      }),
      open: openSocket,
    });

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

    function openSocket(state) {
      let socket = dallinger.openExperimentSocket({ scope: state.token });
      socket.onDirect((data) => {
        if (data !== null && typeof data === "object" && data.type === PAGE_ENDED) {
          // Kept as the page's socket, so later sends and handlers don't
          // open another one.
          socket.close();
        } else {
          dispatch(state, data);
        }
      });
      socket.onOpen(function (event) {
        state.openEvent = event;
        state.connectHandlers.slice().forEach((callback) => callback(event));
      });
      return socket;
    }

    /**
     * Send the experiment a message. The experiment's
     * ``handle_websocket_message`` receives it with ``channel_name``
     * ``"psynet"``, as the JSON text of an object with the ``type`` and, if
     * given, the ``message``.
     *
     * @example
     * psynet.websocket.send("choice", { option: "left" });
     *
     * @param {string} type - What kind of message this is
     * @param {*} [message] - The data that goes with it, anything
     *   ``JSON.stringify`` accepts
     */
    function send(type, message) {
      let data = { type: type };
      if (message !== undefined) {
        data.message = message;
      }
      pages.socket().send(CHANNEL, data);
    }

    /**
     * Run ``callback`` for each message of ``type`` the experiment sends this
     * participant. The callback gets the message's ``message`` (the whole
     * message if it has none), and the whole message as its second argument.
     *
     * The experiment sends a page a message with
     * ``publish_to_participants({"type": type, "message": message},
     * [participant.id])``.
     *
     * @example
     * psynet.websocket.handle("partner_choice", (message) => {
     *   root.querySelector("#partner").textContent = message.option;
     * });
     *
     * @param {string} type - The kind of message to handle
     * @param {function} callback - Called with each message's data
     * @returns {function} Call it to stop handling these messages
     */
    function handle(type, callback) {
      pages.socket();
      let handlers = pages.current().handlers;
      if (!handlers.has(type)) handlers.set(type, []);
      handlers.get(type).push(callback);
      return function () {
        handlers.set(
          type,
          (handlers.get(type) || []).filter((x) => x !== callback),
        );
      };
    }

    /**
     * Run ``callback`` each time the page connects, including after it
     * reconnects, for example to ask the experiment for anything the page
     * may have missed while it was disconnected. If the page is already
     * connected, the callback also runs straight away.
     *
     * @param {function} callback - Called with the connection's open event
     * @returns {function} Call it to stop running the callback
     */
    function onConnect(callback) {
      let socket = pages.socket();
      let state = pages.current();
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

    return {
      connect: pages.socket,
      /** Close the page's connection. Sending or handling opens a new one. */
      close: pages.close,
      handle: handle,
      onConnect: onConnect,
      resetPageState: pages.reset,
      send: send,
    };
  }

  window.PsyNetPageSocket = {
    CHANNEL: CHANNEL,
    create: createPageSocket,
    createPageScopedSocket: createPageScopedSocket,
  };
})();

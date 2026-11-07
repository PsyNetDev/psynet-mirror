(function () {
  "use strict";

  // The type of PsyNet's Ready message.
  const READY = "psynet_ready";

  /**
   * ``psynet.liveSession`` lets a page with a ``LiveSessionControl`` play
   * the live session its group started: send the game messages, and show
   * the views the game sends back.
   *
   * The page joins the session when it first uses ``psynet.liveSession``,
   * and leaves it when the participant moves on. Once it has checked the
   * server's time, it tells the game the player is ready, and the game
   * starts when every player is. Unless the control's
   * ``auto_advance`` is ``False``, the page moves on by itself once the
   * session's result is saved, or if the server refuses its connection.
   * If the connection drops,
   * it reconnects by itself and rejoins. The same page left open in another
   * tab can go on playing until its connection drops, or the session ends:
   * then it can't connect again.
   *
   * ``psynet.js`` creates ``psynet.liveSession`` with this function. The
   * connection is Dallinger's ``/experiment-socket``, joined to the session,
   * with the page's token, a ``.`` and ``dallinger.pageScope`` as its
   * scope, which the experiment's ``accept_websocket_connection`` checks.
   *
   * @param {function} liveSession - Returns the page's ``liveSession``
   *   variable: the control's ``initializerId`` and ``autoAdvance``, and the
   *   session's ``sessionId`` and ``gameChannel``, which are ``null``
   *   without a session, or nothing on a page without a
   *   ``LiveSessionControl``
   * @param {function} pageToken - Returns the current page's token
   * @param {Object} page - ``ready()`` says whether the page is ready to
   *   submit, and ``nextPage()`` submits it
   */
  function createLiveSession(liveSession, pageToken, page) {
    let api = null;

    function session() {
      let current = liveSession();
      if (!current) {
        throw new Error(
          "This page has no live session to play: its control isn't a " +
            "LiveSessionControl.",
        );
      }
      if (current.sessionId == null) {
        throw new Error(
          "The participant's group hasn't started a live session at the " +
            "initializer " +
            JSON.stringify(current.initializerId) +
            ". Check the LiveSessionControl's initializer id, and that the " +
            "page comes after that initializer. A participant removed from " +
            "their group there has no session, which the page can check " +
            "with psynet.liveSession.hasSession.",
        );
      }
      return current;
    }

    let pages = window.PsyNetPageSocket.createPageScopedSocket(pageToken, {
      noTokenError:
        "This page has no page token, so it can't join its live session. " +
        "The server needs a FLASK_SECRET_KEY.",
      newPage: () => ({ session: session(), startedView: null, startedCallbacks: [] }),
      open: openSocket,
    });

    // The result can arrive before the page is ready, as when the page
    // reloads after the session ended, and nextPage alerts the participant
    // then.
    function moveOn(state) {
      if (page.ready()) {
        page.nextPage();
      } else {
        window.addEventListener(
          "timelinePageReady",
          () => {
            if (pageToken() === state.token) {
              page.nextPage();
            }
          },
          { once: true },
        );
      }
    }

    function openSocket(state) {
      let socket = dallinger.openExperimentSocket({
        session: state.session.sessionId,
        gameChannel: state.session.gameChannel,
        scope: state.token + "." + dallinger.pageScope,
      });
      // Sent again after each reconnect, in case the connection dropped
      // before the game read it. The game ignores a repeat.
      let readyDue = false;
      socket.onOpen(() => {
        readyDue = true;
      });
      socket.onClock(() => {
        if (readyDue) {
          readyDue = false;
          socket.send(socket.gameChannel, { type: READY, message: {} });
        }
      });
      if (state.session.autoAdvance) {
        socket.onResultSaved(() => moveOn(state));
        socket.onRefused(() => moveOn(state));
      }
      socket.onView((view) => {
        // A failed session's final view can be null.
        if (state.startedView === null && view !== null && view.live_session.started_at !== null) {
          state.startedView = view;
          state.startedCallbacks.splice(0).forEach((callback) => {
            try {
              callback(view);
            } catch (error) {
              console.error(error);
            }
          });
        }
      });
      return socket;
    }

    /**
     * Call ``callback`` once the session has started, with the first view
     * after the start, or at once if it already has. Until then the game
     * rejects the page's messages.
     *
     * @param {function} callback - Called with the view
     * @returns {Object} ``psynet.liveSession``
     */
    function onStarted(callback) {
      pages.socket();
      let state = pages.current();
      if (state.startedView !== null) {
        callback(state.startedView);
      } else {
        state.startedCallbacks.push(callback);
      }
      return api;
    }

    /**
     * Disable each of ``elements`` until the session starts, so the
     * participant can't play before then.
     *
     * @example
     * psynet.liveSession.disableUntilStarted(...root.querySelectorAll("button"));
     *
     * @param {...HTMLElement} elements - Elements with a ``disabled``
     *   property, such as buttons and inputs
     * @returns {Object} ``psynet.liveSession``
     */
    function disableUntilStarted(...elements) {
      elements.forEach((element) => (element.disabled = true));
      return onStarted(() => {
        elements.forEach((element) => (element.disabled = false));
      });
    }

    /**
     * Send the game a message, which it reads as the ``LiveMessage`` with
     * this ``type``. If the game rejects it, ``onRejected``'s callback gets
     * its number and the reason. The game ignores messages sent after the
     * session ends, which still get a number.
     *
     * @example
     * psynet.liveSession.send("choose", { action: "rock" });
     *
     * @param {string} type - The message's ``type``
     * @param {Object} [message] - Its fields
     * @returns {number|undefined} The message's number, or ``undefined``
     *   once the connection is closed or refused
     */
    function send(type, message) {
      let gameSocket = pages.socket();
      return gameSocket.send(gameSocket.gameChannel, { type: type, message: message });
    }

    function passOn(name) {
      return function (callback) {
        pages.socket()[name](callback);
        return api;
      };
    }

    api = {
      /**
       * Whether the participant's group started a session at the page's
       * initializer. A participant removed from their group there has none,
       * and then the other methods throw. Reading it doesn't join the
       * session.
       *
       * @member {boolean} hasSession
       */
      get hasSession() {
        let current = liveSession();
        return Boolean(current && current.sessionId != null);
      },
      /**
       * Whether the page has had a view from after the session started.
       * ``onView``'s callbacks see it already updated for the view they
       * get. Reading it doesn't join the session.
       *
       * @member {boolean} started
       */
      get started() {
        return pages.current().startedView !== null;
      },
      send: send,
      onStarted: onStarted,
      disableUntilStarted: disableUntilStarted,
      /**
       * Call ``callback`` with each new view of the game, what the game's
       * ``view`` returns for this player, starting when the page joins. Its
       * ``live_session`` says who is ready and when the session started.
       * Dallinger's ``Socket.onView`` describes the view's details.
       *
       * @function onView
       * @param {function} callback - Called with each view
       * @returns {Object} ``psynet.liveSession``
       */
      onView: passOn("onView"),
      /**
       * Call ``callback`` with the number of each message the game rejected
       * and the reason, such as a field of the wrong type.
       *
       * @function onRejected
       * @param {function} callback - Called with the number and the reason
       * @returns {Object} ``psynet.liveSession``
       */
      onRejected: passOn("onRejected"),
      /**
       * Call ``callback`` once, when the page learns the session has ended,
       * with why it ended and this player's final view. Dallinger's
       * ``Socket.onEnded`` lists the reasons.
       *
       * @function onEnded
       * @param {function} callback - Called with the reason and the view
       * @returns {Object} ``psynet.liveSession``
       */
      onEnded: passOn("onEnded"),
      /**
       * Call ``callback`` once the session's result has been saved, after
       * it ends. The page then moves on by itself, unless the control's
       * ``auto_advance`` is ``False``.
       *
       * @function onResultSaved
       * @param {function} callback - Called once the result is saved
       * @returns {Object} ``psynet.liveSession``
       */
      onResultSaved: passOn("onResultSaved"),
      /**
       * Call ``callback`` with the close code and reason if the server
       * refuses the page's connection, as it does long after the session
       * ended. The page then gets no ``onEnded`` or ``onResultSaved``. It
       * moves on by itself unless the control's ``auto_advance`` is
       * ``False``, in which case move on here too.
       *
       * @function onRefused
       * @param {function} callback - Called with the code and the reason
       * @returns {Object} ``psynet.liveSession``
       */
      onRefused: passOn("onRefused"),
    };
    /**
     * The page's Dallinger socket for the session, for anything else, such
     * as ``serverTime`` or ``predictedView``.
     *
     * @member {dallinger.Socket} socket
     */
    // Not enumerable, since reading it joins the session.
    Object.defineProperty(api, "socket", { get: pages.socket });
    // For psynet.resetPageState, not for pages.
    Object.defineProperty(api, "resetPageState", { value: pages.reset });
    return api;
  }

  window.PsyNetLiveSession = { create: createLiveSession };
})();

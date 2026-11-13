(function () {
  "use strict";

  // The type of PsyNet's PlayerReady message.
  const READY = "psynet_ready";

  // How long a player must have been away before onPlayersAway reports them,
  // so that a player whose page reloads isn't reported.
  const AWAY_DELAY_MS = 5000;
  const DISCONNECTED_DELAY_MS = 10000;

  const AWAY_NOTICE = "psynet-player-away-notice";
  const NO_SESSION_NOTICE = "psynet-no-session-notice";

  // Calls report with the players who have been away for AWAY_DELAY_MS,
  // each time that list changes.
  function awayTracker(report) {
    let since = new Map();
    let reported = [];
    let timer = null;
    let lastAway = "[]";

    function check() {
      clearTimeout(timer);
      timer = null;
      let now = Date.now();
      let due = [];
      let next = Infinity;
      since.forEach((time, player) => {
        if (now - time >= AWAY_DELAY_MS) {
          due.push(player);
        } else {
          next = Math.min(next, time + AWAY_DELAY_MS);
        }
      });
      if (next !== Infinity) {
        timer = setTimeout(check, next - now);
      }
      if (due.length !== reported.length || due.some((player, i) => player !== reported[i])) {
        reported = due;
        report(due.slice());
      }
    }

    return {
      update(away) {
        // Most views don't change who is away.
        let key = JSON.stringify(away);
        if (key === lastAway) {
          return;
        }
        lastAway = key;
        let now = Date.now();
        away.forEach((player) => {
          if (!since.has(player)) {
            since.set(player, now);
          }
        });
        Array.from(since.keys()).forEach((player) => {
          if (!away.includes(player)) {
            since.delete(player);
          }
        });
        check();
      },
      // Stops without reporting, for a page that has gone.
      stop() {
        clearTimeout(timer);
        timer = null;
      },
      reported: () => reported.slice(),
    };
  }

  /**
   * ``psynet.liveSession`` lets a page with a ``LiveSessionControl`` play
   * the live session its group started: send the game messages, and show
   * the views the game sends back.
   *
   * The page joins the session when it first uses ``psynet.liveSession``,
   * and leaves it when the participant moves on. Once it has checked the
   * server's time, it tells the game the player is ready, and the game
   * starts when every player is. Unless the control's ``auto_advance`` is
   * ``False``, the page hides its Next button and moves on by itself once
   * the session's result is saved, or if the server refuses its connection.
   * If the connection drops, it reconnects by itself and rejoins. The same
   * page open in another tab plays as the same player.
   *
   * ``PsyNetLiveSession.activatePage``, the page code of a
   * ``LiveSessionControl``, creates ``psynet.liveSession`` with this
   * function. The connection is Dallinger's ``/experiment-socket``, joined
   * to the session. Its scope is
   * the participant's ``websocketScope``, which the experiment's
   * ``accept_websocket_connection`` checks, then a ``.`` and a name for this
   * page's connection: ``dallinger.pageScope``, which tells the
   * participant's tabs apart, and a count of the connections the tab has
   * opened, since the game pages it shows one after another each open one.
   *
   * @param {function} liveSession - Returns the page's ``liveSession``
   *   variable: the control's ``barrierId``, ``autoAdvance``,
   *   ``showResultFor``, ``playerLeftMessage`` and ``noSessionMessage``, and the session's
   *   ``sessionId`` and ``gameChannel``, which are ``null`` without a
   *   session, or nothing on a page without a ``LiveSessionControl``
   * @param {Object} page - ``websocketScope()`` returns the participant's
   *   websocket scope, ``ready()`` says whether the page
   *   is ready to submit, ``nextPage()`` submits it,
   *   ``setNextButtonHidden(hidden)`` hides or shows its Next button, and
   *   ``showNotice(id, text)`` shows ``text`` in a notice at the top of the
   *   page, or removes the notice if ``text`` is null
   */
  function createLiveSession(liveSession, page) {
    let api = null;
    let connections = 0;

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
            "PlayLiveGame " +
            JSON.stringify(current.barrierId) +
            ", because the participant was removed from their group " +
            "there. Check psynet.liveSession.hasSession before the page " +
            "plays.",
        );
      }
      return current;
    }

    // The current page's state, from its first use of psynet.liveSession
    // until the participant leaves the page.
    let currentPage = null;

    function pageState() {
      if (currentPage === null) {
        currentPage = newPage();
      }
      return currentPage;
    }

    // The page's Dallinger socket, which opens when first asked for.
    function pageSocket() {
      let state = pageState();
      if (state.socket === null) {
        state.socket = openSocket(state);
      }
      return state.socket;
    }

    // Run as each page with a LiveSessionControl activates. Returns the
    // page's cleanup, which leaves the session.
    function activatePage() {
      let control = liveSession();
      if (control.sessionId == null && control.noSessionMessage) {
        page.showNotice(NO_SESSION_NOTICE, control.noSessionMessage);
      }
      return () => {
        page.showNotice(NO_SESSION_NOTICE, null);
        let state = currentPage;
        currentPage = null;
        if (state !== null) {
          state.left = true;
          state.socket?.close();
          state.away.stop();
          clearTimeout(state.connectionTimer);
          clearTimeout(state.moveOnTimer);
          page.showNotice(AWAY_NOTICE, null);
        }
      };
    }

    function newPage() {
      let state = {
        session: session(),
        socket: null,
        left: false,
        startedView: null,
        startedCallbacks: [],
        ended: false,
        predict: null,
        interpolate: null,
        viewCallbacks: [],
        awayCallbacks: [],
        connectionTimer: null,
        moveOnTimer: null,
      };
      state.away = awayTracker((players) => {
        let message = state.session.playerLeftMessage;
        if (message) {
          page.showNotice(AWAY_NOTICE, players.length > 0 ? message : null);
        }
        callEach(state.awayCallbacks, players);
      });
      return state;
    }

    function callEach(callbacks, ...args) {
      callbacks.slice().forEach((callback) => {
        try {
          callback(...args);
        } catch (error) {
          console.error(error);
        }
      });
    }

    // Passes on a view, and, once the session has ended, nothing after it.
    function receive(state, view, details) {
      // A failed session's final view can be null. A page that opens after
      // the end gets no onStarted, which would turn its controls back on.
      if (
        !state.ended &&
        state.startedView === null &&
        view !== null &&
        view.live_session.started_at !== null
      ) {
        state.startedView = view;
        callEach(state.startedCallbacks.splice(0), view);
      }
      callEach(state.viewCallbacks, view, details);
      if (state.ended) {
        state.away.update([]);
      } else if (view !== null) {
        state.away.update(view.live_session.away);
      }
    }

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
            if (!state.left) {
              page.nextPage();
            }
          },
          { once: true },
        );
      }
    }

    // Hides the Next button while the page is connected. Only the connection
    // moves the page on, so the button comes back once it has been down for
    // DISCONNECTED_DELAY_MS, and the server then holds the participant's
    // response until the result is saved.
    function hideNextButtonWhileConnected(state, socket) {
      function down() {
        if (state.connectionTimer === null && !state.left) {
          state.connectionTimer = setTimeout(
            () => page.setNextButtonHidden(false),
            DISCONNECTED_DELAY_MS,
          );
        }
      }
      page.setNextButtonHidden(true);
      down();
      socket.raw.addEventListener("open", () => {
        clearTimeout(state.connectionTimer);
        state.connectionTimer = null;
        page.setNextButtonHidden(true);
      });
      socket.raw.addEventListener("close", down);
    }

    function openSocket(state) {
      let socket = dallinger.openExperimentSocket({
        session: state.session.sessionId,
        gameChannel: state.session.gameChannel,
        scope: [page.websocketScope(), dallinger.pageScope, ++connections].join("."),
        // Set at open, so it hands each message to the page's predict
        // callback, whenever the page sets one.
        predict: (view, payload, sentAt) => {
          if (state.predict === null || payload.type === READY) {
            return view;
          }
          return state.predict(view, payload.type, payload.message, sentAt);
        },
        interpolate: (a, b, fraction) =>
          state.interpolate === null ? b : state.interpolate(a, b, fraction),
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
        hideNextButtonWhileConnected(state, socket);
        socket.onResultSaved(() => {
          let seconds = state.session.showResultFor || 0;
          if (seconds > 0) {
            state.moveOnTimer = setTimeout(() => {
              if (!state.left) {
                moveOn(state);
              }
            }, seconds * 1000);
          } else {
            moveOn(state);
          }
        });
        socket.onRefused(() => moveOn(state));
      }
      socket.onView((view, details) => {
        if (state.ended) {
          return;
        }
        state.ended = details.ended !== null;
        receive(state, view, details);
      });
      // The ending carries the final view, which can arrive before the view
      // itself, and is all a page that joins after the end gets.
      socket.onEnded((reason, view) => {
        if (!state.ended) {
          state.ended = true;
          receive(state, view, null);
        }
      });
      return socket;
    }

    /**
     * Call ``callback`` once the session has started, with the first view
     * after the start, or at once if it already has. Until then the game
     * rejects the page's messages. Once the session has ended, it doesn't
     * run, so a page that opens after the end keeps its controls disabled.
     *
     * @param {function} callback - Called with the view
     * @returns {Object} ``psynet.liveSession``
     */
    function onStarted(callback) {
      pageSocket();
      let state = pageState();
      if (state.ended) {
        return api;
      }
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
      let gameSocket = pageSocket();
      return gameSocket.send(gameSocket.gameChannel, { type: type, message: message });
    }

    /**
     * Call ``callback`` with each new view of the game, what the game's
     * ``view`` returns for this player, starting when the page joins and
     * ending with the final view. Once the session has ended, ``ended`` is
     * ``true``, and no more views come. A page that opens after the session
     * has ended gets just the final view. Its ``live_session`` says who is
     * ready, when the session started and who has left.
     *
     * If the session failed, the final view can be ``null``, so check
     * ``ended`` before reading the view.
     *
     * The callback's second argument is the view's details, which
     * Dallinger's ``Socket.onView`` describes. It is ``null`` for a final
     * view that came with the ending, so check ``ended`` and not
     * ``details.ended``.
     *
     * @param {function} callback - Called with each view, which can be
     *   ``null`` at the end, and its details, which can be ``null`` too
     * @returns {Object} ``psynet.liveSession``
     */
    function onView(callback) {
      pageSocket();
      pageState().viewCallbacks.push(callback);
      return api;
    }

    /**
     * Call ``callback`` with the player ids of the other players who have
     * left the game page and not come back, each time that list changes,
     * including to an empty list when they're all back or the session ends.
     * A player counts once they've been away for a few seconds, so a reload
     * doesn't. A player who hasn't opened the game page yet hasn't left. A
     * callback added while players are away gets them at once.
     *
     * PsyNet shows the control's ``player_left_message`` in a notice while
     * anyone is away, so use this for a display of your own, with
     * ``player_left_message=None``.
     *
     * @param {function} callback - Called with a list of player ids
     * @returns {Object} ``psynet.liveSession``
     */
    function onPlayersAway(callback) {
      pageSocket();
      let state = pageState();
      state.awayCallbacks.push(callback);
      let away = state.away.reported();
      if (away.length > 0) {
        callEach([callback], away);
      }
      return api;
    }

    /**
     * Say how the game changes this player's view when it applies one of the
     * page's messages, so that ``predictedView`` can show the page's
     * messages as soon as they're sent, before the game's view arrives.
     *
     * ``callback(view, type, message, sentAt)`` gets a copy of a view, and a
     * message as it was passed to ``send``, and returns the view as it will
     * be once the game has applied the message. It can change the view it's
     * given and return nothing. Set it before the page sends anything.
     * ``sentAt`` is the session time when the page sent the message, or
     * ``null`` if it wasn't known yet. The callback runs again for each new
     * view until the game applies the message, and ``sentAt`` stays the same,
     * so use it rather than the time now to predict when something happens.
     *
     * @example
     * psynet.liveSession.predict((view, type, message) => {
     *   if (type === "choose" && message.round === view.round) {
     *     view.chosen = true;
     *   }
     * });
     *
     * @param {function} callback - Called with a view, the message's
     *   ``type``, its fields and the session time it was sent
     * @returns {Object} ``psynet.liveSession``
     */
    function predict(callback) {
      pageSocket();
      pageState().predict = callback;
      return api;
    }

    /**
     * Return the newest view, with the page's messages that the game hasn't
     * applied yet applied by ``predict``'s callback, in the order they were
     * sent. Draw from it in ``onView``, and again after ``send``, so the
     * player sees their own moves at once. A message the game rejects is
     * undone by the next view. Before the first view it's ``null``, and once
     * the session has ended it's the final view. Don't change the view it
     * returns.
     *
     * @returns {Object|null} The predicted view
     */
    function predictedView() {
      return pageSocket().predictedView();
    }

    /**
     * Say how to draw the game between two of its tick views, so that
     * ``interpolatedView`` can show other players moving smoothly instead
     * of jumping from one tick to the next. It needs a game whose
     * ``tick_rate`` is above 0.
     *
     * ``callback(a, b, fraction)`` gets two tick views and how far between
     * them to draw, from 0 to 1, and returns a new view in between. Unlike
     * ``predict``'s callback, it must leave ``a`` and ``b`` unchanged, since
     * they're the tick views the page keeps.
     *
     * @example
     * psynet.liveSession.interpolate((a, b, fraction) => ({
     *   ...b,
     *   x: a.x + (b.x - a.x) * fraction,
     * }));
     *
     * @param {function} callback - Called with two views and a fraction
     * @returns {Object} ``psynet.liveSession``
     */
    function interpolate(callback) {
      pageSocket();
      pageState().interpolate = callback;
      return api;
    }

    /**
     * Return the view to draw other players from: the game two tick
     * intervals in the past, made by ``interpolate``'s callback from the
     * tick views either side of that time. Call it each time the page
     * draws, and draw the player's own piece from ``predictedView``. Before
     * the first tick view it's ``null``, and once the session has ended it's
     * the final view. Don't change the view it returns.
     *
     * @returns {Object|null} The interpolated view
     */
    function interpolatedView() {
      let socket = pageSocket();
      if (pageState().interpolate === null) {
        throw new Error(
          "Set psynet.liveSession.interpolate's callback before calling interpolatedView."
        );
      }
      return socket.interpolatedView();
    }

    // The started view's ready step, if the game has a duration.
    function startedTimes() {
      let view = pageState().startedView;
      return view === null || view.live_session.ends_at == null ? null : view.live_session;
    }

    /**
     * Return the seconds left until the game's time is up, for a countdown:
     * 0 once the session has ended, and ``null`` while ``duration`` is
     * ``null`` or before the page knows the session clock.
     *
     * @returns {number|null} The seconds left
     */
    function secondsLeft() {
      let times = startedTimes();
      if (times === null || pageState().ended) {
        return times === null ? null : 0;
      }
      let now = pageSocket().sessionTime();
      return now === null ? null : Math.max(0, times.ends_at - now);
    }

    function passOn(name) {
      return function (callback) {
        pageSocket()[name](callback);
        return api;
      };
    }

    api = {
      /**
       * Whether the participant's group started a session at the page's
       * PlayLiveGame. A participant removed from their group there has none.
       * PsyNet then shows the control's ``no_session_message`` in a notice,
       * and the other methods throw. Reading it doesn't join the session.
       *
       * @member {boolean} hasSession
       */
      get hasSession() {
        let current = liveSession();
        return Boolean(current && current.sessionId != null);
      },
      /**
       * Whether the page has had a view from after the session started
       * and before it ended, so it stays ``false`` on a page that opens
       * after the end. Check ``ended`` first. ``onView``'s callbacks see it
       * already updated for the view they get. Reading it doesn't join the
       * session.
       *
       * @member {boolean} started
       */
      get started() {
        return pageState().startedView !== null;
      },
      /**
       * Whether the session has ended. ``onView``'s callbacks see it already
       * updated for the final view. Reading it doesn't join the session.
       *
       * @member {boolean} ended
       */
      get ended() {
        return pageState().ended;
      },
      /**
       * Seconds the page shows the session's result for once it's saved,
       * before moving on by itself: the control's ``show_result_for``, or 0.
       * Use it for a countdown. Reading it doesn't join the session.
       *
       * @member {number} showResultFor
       */
      get showResultFor() {
        let current = liveSession();
        return (current && current.showResultFor) || 0;
      },
      /**
       * The game's ``duration`` in seconds, once the page has had a view
       * from after the start, or ``null``, as for a game without one. Use it
       * with ``secondsLeft()`` for a time bar. Reading it doesn't join the
       * session.
       *
       * @member {number|null} duration
       */
      get duration() {
        let times = startedTimes();
        return times === null ? null : times.ends_at - times.started_at;
      },
      secondsLeft: secondsLeft,
      send: send,
      onStarted: onStarted,
      disableUntilStarted: disableUntilStarted,
      onView: onView,
      onPlayersAway: onPlayersAway,
      predict: predict,
      predictedView: predictedView,
      interpolate: interpolate,
      interpolatedView: interpolatedView,
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
       * it ends. The page then moves on by itself, after the control's
       * ``show_result_for`` seconds, unless its ``auto_advance`` is
       * ``False``.
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
     * as ``serverTime`` or ``sessionTime``.
     *
     * @member {dallinger.Socket} socket
     */
    // Not enumerable, since reading it joins the session.
    Object.defineProperty(api, "socket", { get: pageSocket });
    // For PsyNetLiveSession.activatePage, not for pages.
    Object.defineProperty(api, "activatePage", { value: activatePage });
    return api;
  }

  // The page code of a LiveSessionControl. Creates ``psynet.liveSession``
  // for the first such page the document shows, and returns the page's
  // cleanup. This script can load before psynet.js, so it can't create
  // ``psynet.liveSession`` as it loads.
  function activatePage(psynet) {
    if (!psynet.liveSession) {
      psynet.liveSession = createLiveSession(() => psynet.var.liveSession, {
        websocketScope: () => window.psynetTemplateData.websocketScope,
        ready: () => psynet.pageReady,
        nextPage: () => psynet.nextPage(),
        setNextButtonHidden: (hidden) => {
          let button = document.getElementById("next-button");
          if (button) {
            button.style.display = hidden ? "none" : "";
          }
        },
        showNotice: (id, text) => psynet.showStatusNotice(id, text),
      });
    }
    return psynet.liveSession.activatePage();
  }

  window.PsyNetLiveSession = {
    create: createLiveSession,
    activatePage: activatePage,
  };
})();

(function () {
  "use strict";

  // The type of PsyNet's PlayerReady message.
  const READY = "psynet_ready";

  // How long a player must have been away before onPlayersAway reports them,
  // so that a player whose page reloads isn't reported.
  const AWAY_DELAY_MS = 5000;
  const DISCONNECTED_DELAY_MS = 10000;
  const TIME_LEFT_INTERVAL_MS = 250;

  const AWAY_NOTICE = "psynet-player-away-notice";
  const NO_GAME_NOTICE = "psynet-no-game-notice";

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
   * Create ``psynet.liveGame``, which lets a ``LiveGamePage`` play the live
   * game its group started. The live games reference
   * (``docs/code/multiplayer/live_games.rst``) describes how it behaves.
   *
   * The connection is Dallinger's ``/experiment-socket``, joined to the
   * game, with the scope ``websocketScope.pageScope.n``: the participant's
   * scope, which ``accept_websocket_connection`` checks, then
   * ``dallinger.pageScope``, which tells the participant's tabs apart, then
   * a count of the connections the tab has opened, since the game pages it
   * shows one after another each open one.
   *
   * @param {function} liveGame - Returns the page's ``liveGame`` variable,
   *   from ``LiveGameControl.get_participant_js_vars``, or nothing on a page
   *   that isn't a ``LiveGamePage``
   * @param {Object} page - The page's hooks: ``websocketScope()``,
   *   ``ready()``, ``nextPage()``, ``setNextButtonHidden(hidden)``,
   *   ``showNotice(id, text)``, which removes the notice for a ``null``
   *   text, ``hideGame()`` and ``fetchPlayers(playId)``
   */
  function createLiveGame(liveGame, page) {
    let api = null;
    let connections = 0;

    // Whether the page is a game page whose group started no game. A page
    // that isn't a LiveGamePage isn't, so using psynet.liveGame there
    // raises session()'s error.
    function noGame() {
      let current = liveGame();
      return Boolean(current) && current.liveGameId == null;
    }

    function session() {
      let current = liveGame();
      if (!current) {
        throw new Error(
          "This page has no live game to play: it isn't a LiveGamePage.",
        );
      }
      if (current.liveGameId == null) {
        throw new Error(
          "The participant's group hasn't started a live game at the " +
            "PlayLiveGame " +
            JSON.stringify(current.playId) +
            ", because the participant was removed from their group " +
            "there. Check psynet.liveGame.hasGame before the page " +
            "plays.",
        );
      }
      return current;
    }

    // The current page's state, from its first use of psynet.liveGame
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

    // Run as each LiveGamePage activates. Returns the
    // page's cleanup, which leaves the game.
    function activatePage() {
      let control = liveGame();
      if (control.liveGameId == null) {
        if (control.noGameMessage) {
          page.showNotice(NO_GAME_NOTICE, control.noGameMessage);
        }
        page.hideGame();
      }
      return () => {
        page.showNotice(NO_GAME_NOTICE, null);
        let state = currentPage;
        currentPage = null;
        if (state !== null) {
          state.left = true;
          state.socket?.close();
          state.away.stop();
          clearTimeout(state.connectionTimer);
          clearTimeout(state.moveOnTimer);
          clearTimeout(state.playersTimer);
          state.intervals.forEach(clearInterval);
          page.showNotice(AWAY_NOTICE, null);
        }
      };
    }

    function newPage() {
      let current = session();
      let state = {
        session: current,
        // How the page shows each player, by player number, as the page
        // gave it, and then as GET /live_game/players does once the views
        // show players the page doesn't know, such as newcomers.
        players: (current.players || []).slice(),
        fetchingPlayers: false,
        playersFetchedAt: -Infinity,
        playersTimer: null,
        socket: null,
        left: false,
        startedView: null,
        // The latest view, which a failed game's pages keep at the end.
        lastView: null,
        player: null,
        startedCallbacks: [],
        playingElements: [],
        ended: false,
        predict: null,
        interpolate: null,
        receiveCallbacks: [],
        changeCallbacks: [],
        awayCallbacks: [],
        connectionTimer: null,
        moveOnTimer: null,
        // onTimeLeft's countdowns, run again with each view.
        timeLeftTicks: [],
        intervals: [],
        rejectionElements: [],
        statusCallbacks: [],
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

    // Passes on a view, and, once the game has ended, nothing after it.
    function receive(state, view, details) {
      // A failed game's final view is null, so its pages keep the view
      // they had.
      if (view === null) {
        view = state.lastView;
      }
      if (view !== null) {
        state.lastView = view;
        fetchPlayers(state);
        // A page that opens after the end gets no onStarted, which would
        // turn its controls back on.
        if (
          !state.ended &&
          state.startedView === null &&
          view.psynet.started_at !== null
        ) {
          state.startedView = view;
          callEach(state.startedCallbacks.splice(0), view);
        }
        state.player = view.psynet.you;
        callEach(state.receiveCallbacks, view, details);
        notifyChange(state);
      } else if (!state.ended) {
        // A page that opened after its game failed has no view to show.
        return;
      }
      callEach(state.statusCallbacks);
      // So a countdown shows the time left as soon as the page knows it.
      if (view !== null && !state.left) {
        callEach(state.timeLeftTicks);
      }
      if (state.ended) {
        state.playingElements.forEach((element) => (element.disabled = true));
        state.away.update([]);
      } else {
        state.away.update(view.psynet.away);
      }
    }

    // Calls onChange's callbacks with the game as the page shows it now.
    function notifyChange(state) {
      if (state.lastView !== null && state.changeCallbacks.length > 0) {
        callEach(state.changeCallbacks, shownView(state, state.lastView));
      }
    }

    // The result can arrive before the page is ready, as when the page
    // reloads after the game ended, and nextPage alerts the participant
    // then.
    function moveOn(state) {
      if (state.left) return;
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
          state.connectionTimer = setTimeout(() => {
            state.connectionTimer = null;
            page.setNextButtonHidden(false);
          }, DISCONNECTED_DELAY_MS);
        }
      }
      page.setNextButtonHidden(true);
      down();
      socket.raw.addEventListener("open", () => {
        clearTimeout(state.connectionTimer);
        state.connectionTimer = null;
        if (state.left) return;
        page.setNextButtonHidden(true);
      });
      socket.raw.addEventListener("close", down);
    }

    function openSocket(state) {
      let socket = dallinger.openExperimentSocket({
        session: state.session.liveGameId,
        gameChannel: state.session.gameChannel,
        scope: [page.websocketScope(), dallinger.pageScope, ++connections].join("."),
        // Set at open, so it hands each message to the page's predict
        // callback, whenever the page sets one.
        predict: (view, payload, sentAt) => {
          if (state.predict === null || payload.type === READY) {
            return view;
          }
          return state.predict(
            view,
            payload.type,
            payload.message,
            gameTimeOf(view, sentAt),
          );
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
            state.moveOnTimer = setTimeout(() => moveOn(state), seconds * 1000);
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
     * Call ``callback`` with the first view after the game starts, or at
     * once if it already has. It never runs once the game has ended.
     *
     * @param {function} callback - Called with the view
     * @returns {Object} ``psynet.liveGame``
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
     * Enable each of ``elements`` only while the game is being played.
     *
     * @param {...HTMLElement} elements - Elements with a ``disabled``
     *   property, such as buttons and inputs
     * @returns {Object} ``psynet.liveGame``
     */
    function enableWhilePlaying(...elements) {
      pageSocket();
      let state = pageState();
      elements.forEach((element) => (element.disabled = true));
      state.playingElements.push(...elements);
      return onStarted(() => {
        elements.forEach((element) => (element.disabled = false));
      });
    }

    /**
     * Send the game a message, which it reads as the ``LiveMessage`` with
     * this ``type``.
     *
     * @param {string} type - The message's ``type``
     * @param {Object} [message] - Its fields
     * @returns {number|undefined} The message's number, or ``undefined``
     *   once the connection is closed or refused
     */
    function send(type, message) {
      let gameSocket = pageSocket();
      let number = gameSocket.send(gameSocket.gameChannel, {
        type: type,
        message: message,
      });
      let state = pageState();
      if (number !== undefined) {
        state.rejectionElements.forEach((element) => (element.textContent = ""));
        // The game as the page sees it now includes the message.
        if (state.predict !== null) {
          notifyChange(state);
        }
        callEach(state.statusCallbacks);
      }
      return number;
    }

    // Asks the server how to show the game's players, while the latest view
    // shows more than the page knows, and updates the page with them. The
    // server learns of a newcomer a few seconds after the game does, so the
    // page asks again at most once a second until then, with or without
    // new views, while the game lasts.
    function fetchPlayers(state) {
      const view = state.lastView;
      if (
        state.left ||
        state.ended ||
        state.fetchingPlayers ||
        !page.fetchPlayers ||
        view === null ||
        (view.psynet.away_since || []).length <= state.players.length
      ) {
        return;
      }
      const now = Date.now();
      const wait = state.playersFetchedAt + 1000 - now;
      if (wait > 0) {
        if (state.playersTimer === null) {
          state.playersTimer = setTimeout(() => {
            state.playersTimer = null;
            fetchPlayers(state);
          }, wait);
        }
        return;
      }
      state.fetchingPlayers = true;
      state.playersFetchedAt = now;
      Promise.resolve(page.fetchPlayers(state.session.playId))
        .then((players) => {
          if (state.left || !Array.isArray(players)) {
            return;
          }
          if (players.length > state.players.length) {
            state.players = players;
            notifyChange(state);
          }
        })
        .catch((error) => console.error(error))
        .finally(() => {
          state.fetchingPlayers = false;
          fetchPlayers(state);
        });
    }

    // The view onChange's callbacks get: with a predict callback, the
    // predicted view, so a page shows the player's own messages at once.
    function shownView(state, view) {
      if (state.predict === null) {
        return view;
      }
      return pageSocket().predictedView() ?? view;
    }

    /**
     * Show the reason the game rejected the page's latest message in
     * ``element``, until the page sends its next message.
     *
     * @param {HTMLElement} element - Where to show the reason
     * @returns {Object} ``psynet.liveGame``
     */
    function showRejections(element) {
      pageState().rejectionElements.push(element);
      pageSocket().onRejected((number, reason) => {
        element.textContent = reason;
      });
      return api;
    }

    /**
     * Keep ``element`` showing the game's status, as "The status line" in
     * the live games reference describes.
     *
     * @param {HTMLElement} element - Where to show the status
     * @param {function|null} playing - Returns the status for a view while
     *   the game is played
     * @param {Object} [texts] - ``waiting`` and ``ended`` texts, to replace
     *   the page's; ``ended`` can be a function of the final view
     * @returns {Object} ``psynet.liveGame``
     */
    function showStatus(element, playing, texts = {}) {
      let state = pageState();
      let waiting = texts.waiting ?? state.session.waitingStatus;
      let ended = texts.ended ?? state.session.endedStatus;
      function show() {
        let text;
        if (state.ended) {
          // A failed game's page may have no view to pass.
          text =
            typeof ended !== "function"
              ? ended
              : state.lastView === null
                ? state.session.endedStatus
                : ended(state.lastView);
        } else if (state.lastView === null) {
          // Until the first view, the page doesn't know whether the game
          // has started, as it has for a player who rejoins.
          text = "";
        } else if (state.startedView === null) {
          text = waiting;
        } else if (playing === null) {
          text = "";
        } else {
          text = playing(shownView(state, state.lastView));
        }
        if (element.textContent !== text) {
          element.textContent = text;
        }
      }
      pageSocket();
      state.statusCallbacks.push(show);
      show();
      return api;
    }

    /**
     * Call ``callback`` once, when this player's game has ended, with
     * Dallinger's reason (see ``Socket.onEnded``) and the final view, which
     * for a failed game is the last view the page had.
     *
     * @param {function} callback - Called with the reason and the view
     * @returns {Object} ``psynet.liveGame``
     */
    function onEnded(callback) {
      let state = pageState();
      pageSocket().onEnded((reason, view) => {
        callback(reason, view === null ? state.lastView : view);
      });
      return api;
    }

    /**
     * Call ``callback`` with ``secondsLeft()``, with each view and a few
     * times a second, until the participant leaves the page. It never runs
     * for a game without a ``duration``.
     *
     * @param {function} callback - Called with the seconds left
     * @returns {Object} ``psynet.liveGame``
     */
    function onTimeLeft(callback) {
      pageSocket();
      let state = pageState();
      state.timeLeftTicks.push(countdown(state, secondsLeft, callback));
      return api;
    }

    // Calls callback with seconds(), unless it's null, now and every
    // TIME_LEFT_INTERVAL_MS until the page leaves, and returns the call.
    function countdown(state, seconds, callback) {
      let tick = () => {
        let left = seconds();
        if (left !== null) {
          callEach([callback], left);
        }
      };
      state.intervals.push(setInterval(tick, TIME_LEFT_INTERVAL_MS));
      tick();
      return tick;
    }

    /**
     * Call ``callback`` with the seconds left of the page's
     * ``show_result_for``, a few times a second, from when this player's
     * result is saved. Without ``show_result_for``, it never runs.
     *
     * @param {function} callback - Called with the seconds left
     * @returns {Object} ``psynet.liveGame``
     */
    function onResultTimeLeft(callback) {
      let socket = pageSocket();
      let state = pageState();
      let seconds = state.session.showResultFor || 0;
      if (seconds > 0) {
        socket.onResultSaved(() => {
          if (state.left) {
            return;
          }
          let until = Date.now() + seconds * 1000;
          countdown(state, () => Math.max(0, (until - Date.now()) / 1000), callback);
        });
      }
      return api;
    }

    /**
     * Call ``callback`` with the game as this player sees it, whenever that
     * changes, ending with the final view: with each new view, and, with a
     * ``predict`` callback, after each ``send``. A page that opens after its
     * game failed has no view, so it never runs there.
     *
     * @param {function} callback - Called with the view
     * @returns {Object} ``psynet.liveGame``
     */
    function onChange(callback) {
      pageSocket();
      pageState().changeCallbacks.push(callback);
      return api;
    }

    /**
     * Call ``callback`` with each view as the game sends it, without the
     * page's predictions, and Dallinger's details of it (see
     * ``Socket.onView``). The details are ``null`` for a final view that
     * came with the ending, so check ``ended`` rather than ``details.ended``.
     *
     * @param {function} callback - Called with each view, and its details,
     *   which can be ``null``
     * @returns {Object} ``psynet.liveGame``
     */
    function onReceive(callback) {
      pageSocket();
      pageState().receiveCallbacks.push(callback);
      return api;
    }

    /**
     * Call ``callback`` with the numbers of the other players who have been
     * away from the game page for a few seconds, each time that list
     * changes, including to an empty list. A callback added while players
     * are away gets them at once.
     *
     * @param {function} callback - Called with a list of player numbers
     * @returns {Object} ``psynet.liveGame``
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
     * page's messages, so that ``onChange`` and ``predictedView`` show the
     * page's messages as soon as they're sent. Set it before the page sends
     * anything.
     *
     * ``callback(view, type, message, sentAt)`` can change the copy of the
     * view it gets and return nothing. It runs again for each new view until
     * the game applies the message, with the same ``sentAt``.
     *
     * @param {function} callback - Called with a view, the message's
     *   ``type``, its fields and the game time it was sent
     * @returns {Object} ``psynet.liveGame``
     */
    function predict(callback) {
      pageSocket();
      pageState().predict = callback;
      return api;
    }

    /**
     * Return the newest view with ``predict``'s callback applied to the
     * page's messages that the game hasn't applied yet, or ``null`` before
     * the first view. Don't change the view it returns.
     *
     * @returns {Object|null} The predicted view
     */
    function predictedView() {
      return pageSocket().predictedView();
    }

    /**
     * Say how to draw the game between two of its tick views, for
     * ``interpolatedView``, in a game whose ``tick_rate`` is above 0.
     * ``callback(a, b, fraction)`` returns a new view, and must leave ``a``
     * and ``b`` unchanged, since they're the tick views the page keeps.
     *
     * @param {function} callback - Called with two views and a fraction
     * @returns {Object} ``psynet.liveGame``
     */
    function interpolate(callback) {
      pageSocket();
      pageState().interpolate = callback;
      return api;
    }

    /**
     * Return the game two tick intervals in the past, made by
     * ``interpolate``'s callback, to draw the other players from, or
     * ``null`` before the first tick view. Don't change the view it returns.
     *
     * @returns {Object|null} The interpolated view
     */
    function interpolatedView() {
      let socket = pageSocket();
      if (pageState().interpolate === null) {
        throw new Error(
          "Set psynet.liveGame.interpolate's callback before calling interpolatedView."
        );
      }
      return socket.interpolatedView();
    }

    // A session time, from Dallinger, as the seconds since the game
    // started, or null before the game starts.
    function gameTimeOf(view, sessionTime) {
      let started = view === null ? null : view.psynet.started_at;
      if (started == null || sessionTime == null) {
        return null;
      }
      return sessionTime - started;
    }

    // The started view's PsyNet entry, if the game has a duration. A page
    // that opened after the end has no started view, so it uses the final
    // view.
    function startedTimes() {
      let state = pageState();
      let view = state.startedView ?? (state.ended ? state.lastView : null);
      return view === null || view.psynet.duration == null ? null : view.psynet;
    }

    /**
     * Return the seconds left until the game's time is up: 0 once the game
     * has ended, and ``null`` without a ``duration`` or before the page
     * knows the time.
     *
     * @returns {number|null} The seconds left
     */
    function secondsLeft() {
      let times = startedTimes();
      if (times === null) {
        return null;
      }
      if (pageState().ended) {
        return 0;
      }
      let now = pageSocket().sessionTime();
      return now === null ? null : Math.max(0, times.ends_at - now);
    }

    /**
     * Return the seconds since the game started, the clock of ``now`` in the
     * game's methods, or ``null`` before the game starts or before the page
     * knows the time.
     *
     * @returns {number|null} The game time
     */
    function gameTime() {
      return gameTimeOf(pageState().startedView, pageSocket().sessionTime());
    }

    function passOn(name) {
      return function (callback) {
        pageSocket()[name](callback);
        return api;
      };
    }

    api = {
      /**
       * This player's number in the game, from 0, or ``null`` until the
       * page's first view.
       *
       * @member {number|null} player
       */
      get player() {
        return noGame() ? null : pageState().player;
      },
      /**
       * How to show each player, by player number, as "Who's who" in the
       * live games reference describes. Empty without a game.
       *
       * @member {Object[]} players
       */
      get players() {
        return noGame() ? [] : pageState().players;
      },
      /**
       * Whether the participant's group started a game at the page's
       * PlayLiveGame. Without one, the other methods do nothing. Reading it
       * doesn't join the game.
       *
       * @member {boolean} hasGame
       */
      get hasGame() {
        let current = liveGame();
        return Boolean(current && current.liveGameId != null);
      },
      /**
       * Whether the page has had a view from after the game started and
       * before it ended, so it stays ``false`` on a page that opens after
       * the end. Reading it doesn't join the game.
       *
       * @member {boolean} started
       */
      get started() {
        return !noGame() && pageState().startedView !== null;
      },
      /**
       * Whether this player's game has ended, at the game's end or when its
       * ``is_done`` says so. Reading it doesn't join the game.
       *
       * @member {boolean} ended
       */
      get ended() {
        return !noGame() && pageState().ended;
      },
      /**
       * Whether the game has started and this player's game hasn't ended.
       * Reading it doesn't join the game.
       *
       * @member {boolean} playing
       */
      get playing() {
        return !noGame() && pageState().startedView !== null && !pageState().ended;
      },
      /**
       * The game's ``duration`` in seconds, or ``null`` for a game without
       * one and until the page has a view from after the start. Reading it
       * doesn't join the game.
       *
       * @member {number|null} duration
       */
      get duration() {
        if (noGame()) {
          return null;
        }
        let times = startedTimes();
        return times === null ? null : times.duration;
      },
      secondsLeft: secondsLeft,
      gameTime: gameTime,
      send: send,
      showRejections: showRejections,
      showStatus: showStatus,
      onTimeLeft: onTimeLeft,
      onResultTimeLeft: onResultTimeLeft,
      onStarted: onStarted,
      enableWhilePlaying: enableWhilePlaying,
      onChange: onChange,
      onReceive: onReceive,
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
       * @returns {Object} ``psynet.liveGame``
       */
      onRejected: passOn("onRejected"),
      onEnded: onEnded,
      /**
       * Call ``callback`` once this player's result, their answer and
       * reward, has been saved, after their game ends.
       *
       * @function onResultSaved
       * @param {function} callback - Called once the result is saved
       * @returns {Object} ``psynet.liveGame``
       */
      onResultSaved: passOn("onResultSaved"),
      /**
       * Call ``callback`` with the close code and reason if the server
       * refuses the page's connection, as it does long after the game
       * ended. A page with ``auto_advance=False`` moves on here too.
       *
       * @function onRefused
       * @param {function} callback - Called with the code and the reason
       * @returns {Object} ``psynet.liveGame``
       */
      onRefused: passOn("onRefused"),
    };
    /**
     * The page's Dallinger socket for the session, for anything else, such
     * as ``serverTime`` or ``sessionTime``, or ``null`` without a game.
     *
     * @member {dallinger.Socket|null} socket
     */
    // Without a game, each method does nothing, so a page needn't check
    // hasGame first. What a method returns then, if not psynet.liveGame.
    const WITHOUT_GAME = {
      send: undefined,
      predictedView: null,
      interpolatedView: null,
      secondsLeft: null,
      gameTime: null,
    };
    // Through the descriptors, since reading a getter joins the game.
    for (let [name, descriptor] of Object.entries(Object.getOwnPropertyDescriptors(api))) {
      let method = descriptor.value;
      if (typeof method !== "function") {
        continue;
      }
      api[name] = function (...args) {
        if (!noGame()) {
          return method(...args);
        }
        if (name === "enableWhilePlaying") {
          // There's nothing to play.
          args.forEach((element) => (element.disabled = true));
        }
        return name in WITHOUT_GAME ? WITHOUT_GAME[name] : api;
      };
    }
    // Not enumerable, since reading it joins the game.
    Object.defineProperty(api, "socket", {
      get: () => (noGame() ? null : pageSocket()),
    });
    // For PsyNetLiveGame.activatePage, not for pages.
    Object.defineProperty(api, "activatePage", { value: activatePage });
    return api;
  }

  // The page code of a LiveGamePage's control. Creates ``psynet.liveGame``
  // for the first such page the document shows, and returns the page's
  // cleanup. This script can load before psynet.js, so it can't create
  // ``psynet.liveGame`` as it loads.
  function activatePage(psynet) {
    if (!psynet.liveGame) {
      psynet.liveGame = createLiveGame(() => psynet.var.liveGame, {
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
        hideGame: () => {
          document.querySelectorAll("[data-live-game]").forEach((element) => {
            element.hidden = true;
          });
        },
        fetchPlayers: async (playId) => {
          let params = new URLSearchParams({ uniqueId: psynet.uniqueId, playId });
          let response = await fetch(`/live_game/players?${params}`, {
            cache: "no-store",
          });
          return response.ok ? (await response.json()).players : null;
        },
      });
    }
    return psynet.liveGame.activatePage();
  }

  window.PsyNetLiveGame = {
    create: createLiveGame,
    activatePage: activatePage,
  };
})();

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
   * ``psynet.liveGame`` lets a page with a ``LiveGameControl`` play
   * the live game its group started: send the game messages, and show
   * the views the game sends back.
   *
   * The page joins the game when it first uses ``psynet.liveGame``,
   * and leaves it when the participant moves on. Once it has checked the
   * server's time, it tells the game the player is ready, and the game
   * starts when every player is. Unless the control's ``auto_advance`` is
   * ``False``, the page hides its Next button and moves on by itself once
   * the game's result is saved, or if the server refuses its connection.
   * If the connection drops, it reconnects by itself and rejoins. The same
   * page open in another tab plays as the same player.
   *
   * ``PsyNetLiveGame.activatePage``, the page code of a
   * ``LiveGameControl``, creates ``psynet.liveGame`` with this
   * function. The connection is Dallinger's ``/experiment-socket``, joined
   * to the game. Its scope is
   * the participant's ``websocketScope``, which the experiment's
   * ``accept_websocket_connection`` checks, then a ``.`` and a name for this
   * page's connection: ``dallinger.pageScope``, which tells the
   * participant's tabs apart, and a count of the connections the tab has
   * opened, since the game pages it shows one after another each open one.
   *
   * @param {function} liveGame - Returns the page's ``liveGame``
   *   variable: the control's ``playId``, ``autoAdvance``,
   *   ``showResultFor``, ``playerLeftMessage`` and ``noGameMessage``, and the game's
   *   ``liveGameId`` and ``gameChannel``, which are ``null`` without a
   *   game, or nothing on a page without a ``LiveGameControl``
   * @param {Object} page - ``websocketScope()`` returns the participant's
   *   websocket scope, ``ready()`` says whether the page
   *   is ready to submit, ``nextPage()`` submits it,
   *   ``setNextButtonHidden(hidden)`` hides or shows its Next button, and
   *   ``showNotice(id, text)`` shows ``text`` in a notice at the top of the
   *   page, or removes the notice if ``text`` is null, and
   *   ``hideGame()`` hides the page's elements marked ``data-live-game``
   */
  function createLiveGame(liveGame, page) {
    let api = null;
    let connections = 0;

    // Whether the page is a game page whose group started no game. A page
    // without a LiveGameControl isn't, so using psynet.liveGame there
    // raises session()'s error.
    function noGame() {
      let current = liveGame();
      return Boolean(current) && current.liveGameId == null;
    }

    function session() {
      let current = liveGame();
      if (!current) {
        throw new Error(
          "This page has no live game to play: its control isn't a " +
            "LiveGameControl.",
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

    // Run as each page with a LiveGameControl activates. Returns the
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
          clearInterval(state.timeLeftTimer);
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
        timeLeftTimer: null,
        timeLeftCallbacks: [],
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
      if (view === null) {
        // A page that opened after its game failed has no view to show.
        if (state.ended) {
          state.playingElements.forEach((element) => (element.disabled = true));
          callEach(state.statusCallbacks);
        }
        return;
      }
      state.lastView = view;
      // A page that opens after the end gets no onStarted, which would turn
      // its controls back on.
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
      if (state.changeCallbacks.length > 0) {
        callEach(state.changeCallbacks, shownView(state, view));
      }
      callEach(state.statusCallbacks);
      if (state.ended) {
        state.playingElements.forEach((element) => (element.disabled = true));
        state.away.update([]);
      } else {
        state.away.update(view.psynet.away);
      }
    }

    // The result can arrive before the page is ready, as when the page
    // reloads after the game ended, and nextPage alerts the participant
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
     * Call ``callback`` once the game has started, with the first view
     * after the game starts, or at once if it already has. Until then the game
     * rejects the page's messages. Once the game has ended, it doesn't
     * run, so a page that opens after the end keeps its controls disabled.
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
     * Enable each of ``elements`` only while the game is being played:
     * disable it until the game starts, and again once it ends, when the
     * game would ignore anything the participant sends.
     *
     * @example
     * psynet.liveGame.enableWhilePlaying(...root.querySelectorAll("button"));
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
     * this ``type``. If the game rejects it, ``onRejected``'s callback gets
     * its number and the reason. The game ignores messages sent after the
     * game ends, which still get a number.
     *
     * @example
     * psynet.liveGame.send("choose", { action: "rock" });
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
        if (
          state.predict !== null &&
          state.lastView !== null &&
          state.changeCallbacks.length > 0
        ) {
          callEach(state.changeCallbacks, shownView(state, state.lastView));
        }
        callEach(state.statusCallbacks);
      }
      return number;
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
     * @example
     * psynet.liveGame.showRejections(root.querySelector("#rejection"));
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
     * Keep ``element`` showing the game's status: the control's
     * ``waiting_status`` until the game starts, what ``playing(view)``
     * returns for each view while it's played, and the control's
     * ``ended_status`` once the player's game has ended. ``texts`` can
     * replace the control's two texts, as ``{waiting, ended}``, and
     * ``ended`` can be a function that gets the final view, for an ending
     * that depends on how the game went. With a
     * ``predict`` callback, ``playing`` gets the predicted view, so the
     * status shows the player's own messages at once.
     *
     * @example
     * psynet.liveGame.showStatus(status, (view) =>
     *   view.chosen ? "Waiting for your partner to choose" : "Your turn"
     * );
     *
     * @param {HTMLElement} element - Where to show the status
     * @param {function} playing - Returns the status for a view while the
     *   game is played
     * @param {Object} [texts] - ``waiting`` and ``ended`` texts
     * @returns {Object} ``psynet.liveGame``
     */
    function showStatus(element, playing, texts = {}) {
      let state = pageState();
      let waiting = texts.waiting ?? state.session.waitingStatus;
      let ended = texts.ended ?? state.session.endedStatus;
      function show() {
        let text;
        if (state.ended) {
          text = typeof ended === "function" ? ended(state.lastView) : ended;
        } else if (state.startedView === null) {
          text = waiting;
        } else {
          let view = state.predict === null ? null : pageSocket().predictedView();
          text = playing(view ?? state.lastView);
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
     * Call ``callback`` once, when the page learns this player's game
     * has ended (see ``ended``), with why it ended and this player's
     * final view, the last view the page had if the game failed.
     * Dallinger's ``Socket.onEnded`` lists the reasons.
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
     * Call ``callback`` with ``secondsLeft()`` a few times a second, for a
     * countdown, once the page knows the time left, which is 0 once the game
     * has ended, until the participant leaves the page. A game without a
     * ``duration`` has no time left, so it never runs.
     *
     * @example
     * psynet.liveGame.onTimeLeft((left) => {
     *   timer.textContent = Math.ceil(left);
     * });
     *
     * @param {function} callback - Called with the seconds left
     * @returns {Object} ``psynet.liveGame``
     */
    function onTimeLeft(callback) {
      pageSocket();
      let state = pageState();
      state.timeLeftCallbacks.push(callback);
      if (state.timeLeftTimer === null) {
        let tick = () => {
          let left = secondsLeft();
          if (left !== null) {
            callEach(state.timeLeftCallbacks, left);
          }
        };
        state.timeLeftTimer = setInterval(tick, TIME_LEFT_INTERVAL_MS);
        tick();
      }
      return api;
    }

    /**
     * Call ``callback`` with the game as this player sees it, whenever that
     * changes: with each new view, starting when the page joins and ending
     * with the final view, and, with a ``predict`` callback, after each
     * ``send``, with the message's prediction applied. Update the page
     * here: what it shows, which controls work, and any state the page
     * keeps from the view. Once the game has ended, ``ended`` is ``true``,
     * and no more views come. A page that opens after the game has ended
     * gets just the final view. The view's ``psynet`` says who is ready and
     * who has left.
     *
     * If the game failed, the page keeps the view it had, which comes again
     * with ``ended`` set. A page that opens after its game failed gets no
     * view, so ``onChange`` doesn't run there.
     *
     * @example
     * psynet.liveGame.onChange((view) => {
     *   score.textContent = `Score: ${view.score}`;
     * });
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
     * page's predictions, and its details, which Dallinger's
     * ``Socket.onView`` describes. Most pages need ``onChange`` instead;
     * this is for code that reacts to the views arriving, such as a
     * measure of how far behind the page is. The details are ``null`` for a
     * final view that came with the ending, so check ``ended`` and not
     * ``details.ended``.
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
     * Call ``callback`` with the numbers of the other players who have
     * left the game page and not come back, each time that list changes,
     * including to an empty list when they're all back or the game ends.
     * A player counts once they've been away for a few seconds, so a reload
     * doesn't. A player who hasn't opened the game page yet hasn't left. A
     * callback added while players are away gets them at once.
     *
     * PsyNet shows the control's ``player_left_message`` in a notice while
     * anyone is away, so use this for a display of your own, with
     * ``player_left_message=None``.
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
     * page's messages, so that ``predictedView`` can show the page's
     * messages as soon as they're sent, before the game's view arrives.
     *
     * ``callback(view, type, message, sentAt)`` gets a copy of a view, and a
     * message as it was passed to ``send``, and returns the view as it will
     * be once the game has applied the message. It can change the view it's
     * given and return nothing. Set it before the page sends anything.
     * ``sentAt`` is the game time when the page sent the message, as
     * ``gameTime()`` gives it, or ``null`` if it wasn't known yet. The
     * callback runs again for each new
     * view until the game applies the message, and ``sentAt`` stays the same,
     * so use it rather than the time now to predict when something happens.
     *
     * @example
     * psynet.liveGame.predict((view, type, message) => {
     *   if (type === "choose" && message.round === view.round) {
     *     view.chosen = true;
     *   }
     * });
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
     * Return the newest view, with the page's messages that the game hasn't
     * applied yet applied by ``predict``'s callback, in the order they were
     * sent. ``onChange`` already gets it, and runs again after ``send``, so
     * call this only to draw at other times, such as in an animation loop.
     * A message the game rejects is
     * undone by the next view. Before the first view it's ``null``, and once
     * the game has ended it's the final view. Don't change the view it
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
     * psynet.liveGame.interpolate((a, b, fraction) => ({
     *   ...b,
     *   x: a.x + (b.x - a.x) * fraction,
     * }));
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
     * Return the view to draw other players from: the game two tick
     * intervals in the past, made by ``interpolate``'s callback from the
     * tick views either side of that time. Call it each time the page
     * draws, and draw the player's own piece from ``predictedView``. Before
     * the first tick view it's ``null``, and once the game has ended it's
     * the final view. Don't change the view it returns.
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

    // The started view's PsyNet entry, if the game has a duration.
    function startedTimes() {
      let view = pageState().startedView;
      return view === null || view.psynet.duration == null ? null : view.psynet;
    }

    /**
     * Return the seconds left until the game's time is up, for a countdown:
     * 0 once the game has ended, and ``null`` while ``duration`` is
     * ``null`` or before the page knows the time.
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

    /**
     * Return the seconds since the game started, the same clock as ``now``
     * in the game's methods on the server, or ``null`` before the game
     * starts or before the page knows the time. Use it with a time the game
     * put in the view, such as when a move ends.
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
       * This player's number in the game, as the game's methods on the
       * server see it: 0 for the first player, 1 for the next, and so on.
       * It's ``null`` until the page's first view.
       *
       * @member {number|null} player
       */
      get player() {
        return noGame() ? null : pageState().player;
      },
      /**
       * Whether the participant's group started a game at the page's
       * PlayLiveGame. A participant removed from their group there has none.
       * PsyNet then shows the control's ``no_game_message`` in a notice,
       * hides the page's elements marked ``data-live-game``, and the
       * other methods do nothing: ``send`` returns ``undefined``, and the
       * page's callbacks never run. Reading it doesn't join the game.
       *
       * @member {boolean} hasGame
       */
      get hasGame() {
        let current = liveGame();
        return Boolean(current && current.liveGameId != null);
      },
      /**
       * Whether the page has had a view from after the game started
       * and before it ended, so it stays ``false`` on a page that opens
       * after the end. Check ``ended`` first. ``onChange``'s callbacks see it
       * already updated for the view they get. Reading it doesn't join the
       * game.
       *
       * @member {boolean} started
       */
      get started() {
        return !noGame() && pageState().startedView !== null;
      },
      /**
       * Whether this player's game has ended, so the page gets no more
       * views and the game ignores its messages. That's when the game
       * ends, or before, when the game's ``is_done`` says the player is
       * done. ``onChange``'s callbacks see it already updated for the
       * final view. Reading it doesn't join the game.
       *
       * @member {boolean} ended
       */
      get ended() {
        return !noGame() && pageState().ended;
      },
      /**
       * Whether the game is being played: it has started and hasn't
       * ended. Check it before sending a message from a key press, for
       * example, and use ``enableWhilePlaying`` for controls that are
       * enabled whenever it's ``true``. Reading it doesn't join the game.
       *
       * @member {boolean} playing
       */
      get playing() {
        return !noGame() && pageState().startedView !== null && !pageState().ended;
      },
      /**
       * Seconds the page shows the game's result for once it's saved,
       * before moving on by itself: the control's ``show_result_for``, or 0.
       * Use it for a countdown. Reading it doesn't join the game.
       *
       * @member {number} showResultFor
       */
      get showResultFor() {
        let current = liveGame();
        return (current && current.showResultFor) || 0;
      },
      /**
       * The game's ``duration`` in seconds, once the page has had a view
       * from after the game starts, or ``null``, as for a game without one.
       * Use it with ``secondsLeft()`` for a time bar. Reading it doesn't join the
       * game.
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
       * reward, has been saved, after their game ends. The page then moves
       * on by itself, after the control's
       * ``show_result_for`` seconds, unless its ``auto_advance`` is
       * ``False``.
       *
       * @function onResultSaved
       * @param {function} callback - Called once the result is saved
       * @returns {Object} ``psynet.liveGame``
       */
      onResultSaved: passOn("onResultSaved"),
      /**
       * Call ``callback`` with the close code and reason if the server
       * refuses the page's connection, as it does long after the game
       * ended. The page then gets no ``onEnded`` or ``onResultSaved``. It
       * moves on by itself unless the control's ``auto_advance`` is
       * ``False``, in which case move on here too.
       *
       * @function onRefused
       * @param {function} callback - Called with the code and the reason
       * @returns {Object} ``psynet.liveGame``
       */
      onRefused: passOn("onRefused"),
    };
    /**
     * The page's Dallinger socket for the session, for anything else, such
     * as ``serverTime`` or ``sessionTime``.
     *
     * @member {dallinger.Socket} socket
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
    Object.defineProperty(api, "socket", { get: pageSocket });
    // For PsyNetLiveGame.activatePage, not for pages.
    Object.defineProperty(api, "activatePage", { value: activatePage });
    return api;
  }

  // The page code of a LiveGameControl. Creates ``psynet.liveGame``
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
      });
    }
    return psynet.liveGame.activatePage();
  }

  window.PsyNetLiveGame = {
    create: createLiveGame,
    activatePage: activatePage,
  };
})();

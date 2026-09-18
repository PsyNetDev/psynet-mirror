export async function activate({root, vars, psynet}) {
    const nRounds = vars.rps_config.n_rounds;

    psynet.trial.onEvent("liveSessionInit", function () {
        const participantId = String(psynet.session.participant_id);
        let round = 1;
        let completed = false;
        let finalSubmitted = false;
        let finalAnswer = null;

        const buttons = Array.from(root.querySelectorAll(".rps-choice"));
        const statusEl = root.querySelector("#rps-status");
        const scoreEl = root.querySelector("#rps-score");
        const logEl = root.querySelector("#rps-log");

        function setEnabled(enabled) {
            buttons.forEach(function (button) {
                button.disabled = !enabled;
            });
        }

        function appendReveal(msg) {
            const line = document.createElement("p");
            line.textContent = msg.result;
            logEl.appendChild(line);
            logEl.scrollTop = logEl.scrollHeight;
            scoreEl.textContent = msg.scoreboard;
            statusEl.textContent = msg.status;
        }

        function participantHasSubmitted(state) {
            return (
                (state.submitted_participant_ids || [])
                    .map(String)
                    .indexOf(participantId) !== -1
            );
        }

        function advanceIfFinished(reveal) {
            if (!reveal || !reveal.finished || finalSubmitted) return;
            completed = true;
            finalSubmitted = true;
            finalAnswer = reveal.answer;
            setEnabled(false);
            psynet.nextPage(finalAnswer);
        }

        function promptForCurrentRound() {
            statusEl.textContent =
                "Round " + round + " of " + nRounds + ": choose your action.";
        }

        function renderFreshState(freshState) {
            if (!freshState) return;

            // Fresh state is for recovery after initial load/reconnect. Normal
            // round progress is communicated by targeted roundReveal events.
            const state = freshState.state || {};
            const history = state.reveal_history || [];
            round = state.current_round || round;
            logEl.innerHTML = "";
            history.forEach(appendReveal);

            if (history.length === 0) {
                scoreEl.textContent = "Score — you: 0, partner: 0";
                promptForCurrentRound();
            }

            const latest = history[history.length - 1];
            if (latest && latest.finished) {
                setEnabled(false);
                completed = true;
                finalAnswer = latest.answer;
                advanceIfFinished(latest);
                return;
            }

            if (!freshState.started) {
                statusEl.textContent = "Waiting for your partner to load the game…";
                setEnabled(false);
            } else if (participantHasSubmitted(state)) {
                statusEl.textContent = "Waiting for your partner…";
                setEnabled(false);
            } else {
                promptForCurrentRound();
                setEnabled(true);
            }
        }

        function startLiveRound() {
            if (completed || participantHasSubmitted(psynet.session.state || {})) {
                return;
            }
            promptForCurrentRound();
            setEnabled(true);
        }

        function applyRoundReveal(reveal) {
            appendReveal(reveal);
            round = reveal.round;
            if (reveal.finished) {
                advanceIfFinished(reveal);
            } else {
                setEnabled(true);
            }
        }

        psynet.session.onFreshState(renderFreshState);
        psynet.session.onStarted(startLiveRound);
        psynet.websocket.handle("roundReveal", applyRoundReveal);
        psynet.session.ready();

        buttons.forEach(function (button) {
            button.addEventListener("click", function () {
                if (completed || button.disabled) return;
                setEnabled(false);
                statusEl.textContent = "Waiting for your partner…";
                psynet.websocket.send("choose", {
                    round: round,
                    action: button.getAttribute("data-action"),
                });
            });
        });
    });
}

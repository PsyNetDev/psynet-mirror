const RESULTS = {
  win: "You won the throw.",
  loss: "You lost the throw.",
  draw: "The throw was a draw."
};

export function activate({root, psynet}) {
  if (!psynet.liveGame.hasGame) {
    // PsyNet's notice says why, and the Next button moves on.
    root.querySelector("#rps-game").hidden = true;
    return;
  }
  let status = root.querySelector("#rps-status");
  let buttons = Array.from(root.querySelectorAll(".rps-action"));
  let score = root.querySelector("#rps-score");
  let results = root.querySelector("#rps-results");
  let last = root.querySelector("#rps-last");
  let partner = root.querySelector("#rps-partner");
  let rejection = root.querySelector("#rps-rejection");
  let current = null;

  function enableButtons(enabled) {
    buttons.forEach((button) => {
      button.disabled = !enabled;
    });
  }

  // The page draws the player's choice at once, even if a view from before
  // the game applied it arrives first, such as one the partner's choice
  // caused.
  psynet.liveGame.predict((view, type, message) => {
    if (type === "choose" && message.throw === view.throw) {
      view.chosen = true;
    }
  });

  function describe(played) {
    return (
      `You played ${played.mine}, your partner played ${played.theirs}. ` +
      RESULTS[played.result]
    );
  }

  // Each view holds every throw played so far, so a page that reloads or
  // reconnects shows the whole game again.
  function render(view) {
    if (view === null) {
      // The final view of a game that failed.
      enableButtons(false);
      status.textContent = "The game is over.";
      return;
    }
    current = view.throw;
    results.replaceChildren(
      ...view.results.map((played) => {
        let item = document.createElement("li");
        item.textContent = describe(played);
        return item;
      })
    );
    let latest = view.results.at(-1);
    last.textContent = latest
      ? `Throw ${view.results.length}: ${describe(latest)}`
      : "";
    score.textContent = `Throws won: you ${view.wins}, your partner ${view.partner_wins}`;
    if (psynet.liveGame.ended) {
      status.textContent = "The game is over.";
    } else if (!psynet.liveGame.started) {
      status.textContent = "Waiting for your partner to open the game";
    } else if (view.chosen) {
      status.textContent = "Waiting for your partner to choose";
    } else {
      status.textContent = `Throw ${view.throw} of ${view.n_throws}: choose your action`;
    }
    let playing = psynet.liveGame.playing;
    partner.textContent = playing && view.partner_chosen ? "Your partner has chosen." : "";
    enableButtons(playing && !view.chosen);
  }

  function choose(action) {
    if (psynet.liveGame.send("choose", {throw: current, action: action}) !== undefined) {
      render(psynet.liveGame.predictedView());
    }
  }

  psynet.liveGame.onView(() => render(psynet.liveGame.predictedView()));
  psynet.liveGame.showRejections(rejection);

  for (let button of buttons) {
    button.addEventListener("click", () => choose(button.dataset.action));
  }
}

const RESULTS = {
  win: "You won the throw.",
  loss: "You lost the throw.",
  draw: "The throw was a draw."
};

export function activate({root, psynet}) {
  let status = root.querySelector("#rps-status");
  let buttons = Array.from(root.querySelectorAll(".rps-action"));
  let score = root.querySelector("#rps-score");
  let results = root.querySelector("#rps-results");
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
    current = view.throw;
    results.replaceChildren(
      ...view.results.map((played) => {
        let item = document.createElement("li");
        item.textContent = describe(played);
        return item;
      })
    );
    score.textContent = `Throws won: you ${view.wins}, your partner ${view.partner_wins}`;
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
  psynet.liveGame.showStatus(status, (view) =>
    view.chosen
      ? "Waiting for your partner to choose"
      : `Throw ${view.throw} of ${view.n_throws}: choose your action`
  );
  psynet.liveGame.showRejections(rejection);

  for (let button of buttons) {
    button.addEventListener("click", () => choose(button.dataset.action));
  }
}

const SVG = "http://www.w3.org/2000/svg";

function svg(tag, attributes, ...children) {
  let element = document.createElementNS(SVG, tag);
  for (let [name, value] of Object.entries(attributes)) {
    element.setAttribute(name, value);
  }
  element.append(...children);
  return element;
}

function boatIcon(who) {
  return svg(
    "svg",
    {viewBox: "0 0 40 32", class: `fish-boat fish-who-${who}`, "aria-hidden": "true"},
    svg("path", {d: "M20 3 L20 20", class: "fish-mast"}),
    svg("path", {d: "M21 4 L33 18 L21 18 Z", class: "fish-sail"}),
    svg("path", {d: "M4 21 H36 L30 29 H10 Z", class: "fish-hull"})
  );
}

function buoyIcon() {
  return svg(
    "svg",
    {viewBox: "0 0 24 24", class: "fish-buoy", "aria-hidden": "true"},
    svg("circle", {cx: 12, cy: 12, r: 7}),
    svg("path", {d: "M5 12 H19"})
  );
}

function whoText(who) {
  return who === "you" ? "You" : `Member ${who}`;
}

export function activate({root, psynet}) {
  let live = psynet.liveSession;
  if (!live.hasSession) {
    root.querySelector("#fish-game").hidden = true;
    return;
  }
  let lake = root.querySelector("#fish-lake");
  let status = root.querySelector("#fish-status");
  let timeLeft = root.querySelector("#fish-time-left");
  let scores = root.querySelector("#fish-scores");
  let rejection = root.querySelector("#fish-rejection");
  let view = null;
  let seenCatch = 0;
  let spots = [];

  live.predict((predicted, type, message) => {
    if (type === "move") {
      let mine = predicted.boats.find((boat) => boat.who === "you");
      mine.spot = message.spot;
      mine.arrives_at = Infinity;
    }
  });

  function buildLake(n) {
    spots = [];
    lake.replaceChildren();
    for (let spot = 1; spot <= n; spot++) {
      let tile = document.createElement("button");
      tile.type = "button";
      tile.className = "fish-spot";
      tile.setAttribute("aria-label", `Spot ${spot}`);
      let label = document.createElement("span");
      label.className = "fish-spot-number";
      label.append(buoyIcon(), String(spot));
      let boats = document.createElement("div");
      boats.className = "fish-spot-boats";
      let catches = document.createElement("div");
      catches.className = "fish-catches";
      tile.append(label, boats, catches);
      tile.addEventListener("click", () => move(spot));
      lake.append(tile);
      spots.push({tile, boats, catches});
    }
  }

  function move(spot) {
    rejection.textContent = "";
    if (live.send("move", {spot}) !== undefined) {
      render();
    }
  }

  function showCatches(latest) {
    for (let caught of latest) {
      let bubble = document.createElement("span");
      bubble.className = `fish-catch fish-who-${caught.who}`;
      bubble.textContent = `+${caught.fish} 🐟`;
      spots[caught.spot - 1].catches.append(bubble);
      bubble.addEventListener("animationend", () => bubble.remove());
    }
  }

  function render() {
    view = live.predictedView();
    if (view === null) {
      status.textContent = "The round is over.";
      return;
    }
    if (spots.length !== view.n_spots) {
      buildLake(view.n_spots);
    }
    let playing = live.started && !live.ended;
    if (live.ended) {
      status.textContent = "The round is over.";
    } else if (!live.started) {
      status.textContent = "Waiting for the others to reach the lake";
    } else {
      status.textContent = "Fishing";
    }
    let now = live.socket.sessionTime();
    for (let {tile, boats} of spots) {
      boats.replaceChildren();
      tile.disabled = !playing;
    }
    for (let boat of view.boats) {
      if (boat.spot === null) {
        continue;
      }
      let icon = boatIcon(boat.who);
      icon.classList.toggle("fish-sailing", boat.arrives_at > now);
      let wrapper = document.createElement("span");
      wrapper.className = "fish-boat-wrapper";
      wrapper.title = whoText(boat.who);
      wrapper.append(icon);
      spots[boat.spot - 1].boats.append(wrapper);
    }
    if (view.catch_number > seenCatch) {
      seenCatch = view.catch_number;
      showCatches(view.latest);
    }
    // "you" first, then the others in order.
    let byWho = Object.entries(view.fish).sort(([a], [b]) =>
      a === "you" ? -1 : b === "you" ? 1 : a.localeCompare(b)
    );
    scores.replaceChildren(
      ...byWho.map(([who, fish]) => {
        let item = document.createElement("span");
        item.className = `fish-score fish-who-${who}`;
        item.append(boatIcon(who), `${whoText(who)}: ${fish} 🐟`);
        return item;
      })
    );
  }

  function tick() {
    if (view && view.ends_at !== null && !live.ended) {
      let left = view.ends_at - (live.socket.sessionTime() ?? 0);
      let fraction = Math.max(0, Math.min(1, left / view.seconds));
      timeLeft.style.width = `${fraction * 100}%`;
      // Redrawn so that boats that have arrived stop sailing.
      render();
    }
  }
  let timer = setInterval(tick, 500);

  live.onView(render);
  live.onRejected((number, reason) => {
    rejection.textContent = reason;
  });
  return () => clearInterval(timer);
}

const SVG = "http://www.w3.org/2000/svg";
// Seconds a boat takes to shift within a spot when another boat arrives or leaves.
const SHUFFLE_SECONDS = 0.4;

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

function whoText(who) {
  return who === "you" ? "You" : `Member ${who}`;
}

function byWho(fish) {
  // "you" first, then the others in order.
  return Object.entries(fish).sort(([a], [b]) =>
    a === "you" ? -1 : b === "you" ? 1 : a.localeCompare(b)
  );
}

export function activate({root, psynet}) {
  let live = psynet.liveSession;
  let game = root.querySelector("#fish-game");
  let status = root.querySelector("#fish-status");
  if (!live.hasSession) {
    status.textContent = "The round couldn't start.";
    let button = document.createElement("button");
    button.type = "button";
    button.className = "btn btn-primary";
    button.textContent = "Continue";
    button.addEventListener("click", () => psynet.nextPage());
    root.querySelector("#fish-results").replaceChildren(button);
    root.querySelector("#fish-results").hidden = false;
    return;
  }
  let lake = root.querySelector("#fish-lake");
  let dock = root.querySelector(".fish-dock");
  let layer = root.querySelector("#fish-boats");
  let timeLeft = root.querySelector("#fish-time-left");
  let secondsLeft = root.querySelector("#fish-seconds");
  let scores = root.querySelector("#fish-scores");
  let rejection = root.querySelector("#fish-rejection");
  let results = root.querySelector("#fish-results");
  let resultsSeconds = Number(game.dataset.resultsSeconds);
  let spots = [...root.querySelectorAll(".fish-spot")].map((tile) => ({
    tile,
    catches: tile.querySelector(".fish-catches"),
  }));
  // Each player's boat: its element and where it is heading.
  let boats = new Map();
  let view = null;
  let seenCatch = 0;
  let countdown = null;

  live.predict((predicted, type, message) => {
    if (type === "move") {
      let mine = predicted.boats.find((boat) => boat.who === "you");
      mine.spot = message.spot;
      mine.arrives_at = Infinity;
    }
  });

  spots.forEach(({tile}, index) => {
    tile.addEventListener("click", () => move(index + 1));
  });

  function move(spot) {
    rejection.textContent = "";
    if (live.send("move", {spot}) !== undefined) {
      render();
    }
  }

  // Where a boat sits: in a row at the dock before its first move, otherwise
  // side by side with the other boats at or heading to its spot.
  function berth(spot, index, count) {
    let box = spot === null ? dock : spots[spot - 1].tile;
    let x = box.offsetLeft + box.offsetWidth / 2;
    let y = box.offsetTop + box.offsetHeight / 2 + (spot === null ? 0 : 10);
    return {x: x + (index - (count - 1) / 2) * (spot === null ? 56 : 34), y};
  }

  function place(boat, target, seconds, easing) {
    if (boat.x === target.x && boat.y === target.y) {
      return;
    }
    if (Math.abs(target.x - boat.x) > 1) {
      boat.icon.classList.toggle("fish-facing-left", target.x < boat.x);
    }
    boat.element.style.transition =
      seconds > 0 ? `transform ${seconds}s ${easing}` : "none";
    boat.element.style.transform = `translate(${target.x}px, ${target.y}px)`;
    Object.assign(boat, target);
  }

  function drawBoats(now, instant) {
    let groups = new Map();
    for (let boat of view.boats) {
      groups.set(boat.spot, [...(groups.get(boat.spot) ?? []), boat.who]);
    }
    for (let {who, spot, arrives_at} of view.boats) {
      let boat = boats.get(who);
      let group = groups.get(spot);
      let target = berth(spot, group.indexOf(who), group.length);
      if (boat === undefined) {
        let icon = boatIcon(who);
        let element = document.createElement("span");
        element.className = "fish-boat-wrapper";
        element.title = whoText(who);
        element.append(icon);
        layer.append(element);
        boat = {element, icon, spot, x: null, y: null};
        boats.set(who, boat);
        place(boat, target, 0);
      }
      let sailing = arrives_at !== null && arrives_at > now;
      let remaining = arrives_at === Infinity ? view.travel_seconds : arrives_at - now;
      if (instant) {
        place(boat, target, 0);
      } else if (boat.spot !== spot) {
        place(boat, target, Math.max(remaining, SHUFFLE_SECONDS), "linear");
      } else {
        place(boat, target, sailing ? Math.max(remaining, SHUFFLE_SECONDS) : SHUFFLE_SECONDS, sailing ? "linear" : "ease");
      }
      boat.spot = spot;
      boat.element.classList.toggle("fish-sailing", sailing);
    }
  }

  function showCatches(latest) {
    for (let caught of latest) {
      let bubble = document.createElement("span");
      bubble.className = `fish-catch fish-who-${caught.who}`;
      bubble.textContent = `+${caught.fish}`;
      spots[caught.spot - 1].catches.append(bubble);
      bubble.addEventListener("animationend", () => bubble.remove());
    }
  }

  function drawScores(fish) {
    scores.replaceChildren(
      ...byWho(fish).map(([who, n]) => {
        let item = document.createElement("span");
        item.className = `fish-score fish-who-${who}`;
        item.append(boatIcon(who), `${whoText(who)}: ${n} fish`);
        return item;
      })
    );
  }

  function render({instant = false} = {}) {
    view = live.predictedView();
    if (view === null) {
      status.textContent = "The round is over.";
      return;
    }
    let playing = live.started && !live.ended;
    if (live.ended) {
      status.textContent = results.hidden ? "Counting the catch…" : "The round is over.";
    } else if (!live.started) {
      status.textContent = "Waiting for the others to reach the lake…";
    } else {
      status.textContent = "Fishing";
    }
    lake.classList.toggle("fish-playing", playing);
    for (let {tile} of spots) {
      tile.disabled = !playing;
    }
    drawBoats(live.socket.sessionTime() ?? 0, instant);
    if (view.catch_number > seenCatch) {
      seenCatch = view.catch_number;
      showCatches(view.latest);
    }
    drawScores(view.fish);
  }

  function drawClock() {
    if (!view || view.ends_at === null) {
      return;
    }
    let left = live.ended ? 0 : view.ends_at - (live.socket.sessionTime() ?? 0);
    let fraction = Math.max(0, Math.min(1, left / view.seconds));
    timeLeft.style.width = `${fraction * 100}%`;
    secondsLeft.textContent = `${Math.ceil(Math.max(0, left))} s`;
  }

  function showResults(seconds) {
    status.textContent = "The round is over.";
    let mine = view ? view.fish.you ?? 0 : 0;
    let heading = document.createElement("h3");
    heading.textContent = `You caught ${mine} fish this round`;
    let list = document.createElement("ol");
    list.className = "fish-results-list";
    for (let [who, n] of byWho(view ? view.fish : {}).sort((a, b) => b[1] - a[1])) {
      let item = document.createElement("li");
      item.className = `fish-who-${who}`;
      item.append(boatIcon(who), `${whoText(who)}: ${n} fish`);
      list.append(item);
    }
    let next = document.createElement("p");
    next.className = "fish-results-next";
    results.replaceChildren(heading, list, next);
    results.hidden = false;
    let until = Date.now() + seconds * 1000;
    countdown = setInterval(() => {
      let left = Math.ceil((until - Date.now()) / 1000);
      if (left <= 0) {
        clearInterval(countdown);
        psynet.nextPage();
      } else {
        next.textContent = `Continuing in ${left} s`;
      }
    }, 250);
    next.textContent = `Continuing in ${seconds} s`;
  }

  let timer = setInterval(() => {
    drawClock();
    if (view && !live.ended) {
      // Redrawn so that boats that have arrived stop sailing.
      render();
    }
  }, 500);
  let resize = () => view && render({instant: true});
  window.addEventListener("resize", resize);

  live.onView(() => {
    render();
    drawClock();
  });
  live.onRejected((number, reason) => {
    rejection.textContent = reason;
  });
  live.onResultSaved(() => showResults(resultsSeconds));
  live.onRefused(() => psynet.nextPage());
  return () => {
    clearInterval(timer);
    clearInterval(countdown);
    window.removeEventListener("resize", resize);
  };
}

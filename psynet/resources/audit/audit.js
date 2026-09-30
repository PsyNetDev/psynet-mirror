window.MathJax = {
  tex: {
    inlineMath: [
      ["$", "$"],
      ["\\(", "\\)"],
    ],
    displayMath: [
      ["$$", "$$"],
      ["\\[", "\\]"],
    ],
    processEscapes: true,
  },
  svg: {
    fontCache: "global",
  },
};

// MathJax 4 reads window.MathJax then typesets the page when tex-svg.js loads.

document.querySelectorAll(".notebook-plotly").forEach((wrapper) => {
  const specElement = wrapper.querySelector("[data-plotly-spec]");
  const target = wrapper.querySelector("[data-plotly-target]");
  const error = wrapper.querySelector("[data-plotly-error]");
  try {
    const spec = JSON.parse(specElement.textContent);
    Plotly.newPlot(target, spec.data, spec.layout, spec.config);
  } catch (exception) {
    console.error("Failed to render Plotly notebook output", exception);
    target.hidden = true;
    error.hidden = false;
  }
});

// Static servers such as GitLab Pages and `psynet audit serve` ignore
// byte-range requests, and browsers can't seek a video served that way.
// Such videos are downloaded once and played from memory instead.
document.querySelectorAll("video").forEach((video) => {
  const makeSeekable = async () => {
    const seekable =
      video.seekable.length > 0 &&
      video.seekable.end(0) >= video.duration - 1;
    if (seekable || video.currentSrc.startsWith("blob:")) return;
    try {
      const response = await fetch(video.currentSrc);
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      video.src = URL.createObjectURL(await response.blob());
    } catch (exception) {
      console.warn("Could not make video seekable", video.currentSrc, exception);
    }
  };
  if (video.readyState >= HTMLMediaElement.HAVE_METADATA) makeSeekable();
  else video.addEventListener("loadedmetadata", makeSeekable, { once: true });
});

document.querySelectorAll("[data-screenshot-gallery]").forEach((gallery) => {
  const cards = Array.from(
    gallery.querySelectorAll("[data-screenshot-card]"),
  );
  const panel = gallery.closest(".screenshot-gallery");
  const counter = panel.querySelector("[data-screenshot-counter]");
  const previous = panel.querySelector("[data-screenshot-prev]");
  const next = panel.querySelector("[data-screenshot-next]");
  const caption = panel.querySelector("[data-screenshot-caption]");
  const show = (index) => {
    cards.forEach((card, cardIndex) => {
      card.hidden = cardIndex !== index;
    });
    caption.textContent = cards[index]?.dataset.screenshotCaptionText || "";
    counter.textContent = `${index + 1} / ${cards.length}`;
    gallery.dataset.screenshotIndex = String(index);
  };
  const step = (offset) => {
    const current = Number(gallery.dataset.screenshotIndex || 0);
    show((current + offset + cards.length) % cards.length);
  };
  if (cards.length > 0) {
    show(0);
    previous.addEventListener("click", () => step(-1));
    next.addEventListener("click", () => step(1));
  }
});

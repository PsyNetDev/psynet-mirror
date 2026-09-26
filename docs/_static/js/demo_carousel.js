document.addEventListener("DOMContentLoaded", () => {
  for (const carousel of document.querySelectorAll(".demo-carousel")) {
    const track = carousel.querySelector(".demo-carousel-track");
    const slides = track.querySelectorAll(".demo-carousel-slide");
    const dots = carousel.querySelectorAll(".demo-carousel-dot");
    if (dots.length === 0) continue;

    const current = () => Math.round(track.scrollLeft / track.clientWidth);
    const show = (i) => {
      const n = (i + slides.length) % slides.length;
      track.scrollTo({ left: n * track.clientWidth });
    };
    const update = () => {
      dots.forEach((dot, i) => dot.classList.toggle("active", i === current()));
    };

    carousel.querySelector(".demo-carousel-prev").addEventListener("click", () => show(current() - 1));
    carousel.querySelector(".demo-carousel-next").addEventListener("click", () => show(current() + 1));
    dots.forEach((dot, i) => dot.addEventListener("click", () => show(i)));
    track.addEventListener("scroll", update, { passive: true });
    update();
  }
});

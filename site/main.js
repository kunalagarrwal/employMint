// employMint drawing set: smooth scrolling, plates that draw themselves with the scroll, a title block that
// follows the sheet you're on, and the copy button. Every effect is a pure function of scroll position (or,
// for the first plate, of time since load), so it runs forwards and backwards with the page.
(() => {
  const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  const clamp = (v, lo = 0, hi = 1) => Math.min(hi, Math.max(lo, v));
  const smooth = (t) => t * t * (3 - 2 * t);
  const easeOut = (t) => 1 - Math.pow(1 - t, 3);

  // ---------- smooth, inertial scrolling (wheel and trackpad; touch keeps native scrolling) ----------
  let lenis = null;
  if (!reduce && window.Lenis) {
    lenis = new window.Lenis({ lerp: 0.085, wheelMultiplier: 0.95 });
    const raf = (time) => { lenis.raf(time); requestAnimationFrame(raf); };
    requestAnimationFrame(raf);
  }
  document.querySelectorAll('a[href^="#"]').forEach((a) => {
    a.addEventListener("click", (e) => {
      const id = a.getAttribute("href");
      const target = id.length > 1 && document.querySelector(id);
      if (!target) return;
      e.preventDefault();
      if (lenis) lenis.scrollTo(target, { offset: -72, duration: 1.4 });
      else target.scrollIntoView({ behavior: reduce ? "auto" : "smooth" });
      history.replaceState(null, "", id);
      if (target.id === "main") target.focus({ preventScroll: true });
    });
  });

  // ---------- how a plate draws: construction, then ink, then wash, then labels ----------
  // p runs 0 -> 1; each layer gets its own window of p so the drawing builds up in that order.
  const setDrawing = (el, p) => {
    el.style.setProperty("--c", smooth(clamp(p / 0.45)).toFixed(3));
    el.style.setProperty("--inkp", smooth(clamp((p - 0.15) / 0.55)).toFixed(3));
    el.style.setProperty("--wash", smooth(clamp((p - 0.5) / 0.35)).toFixed(3));
    el.style.setProperty("--lab", smooth(clamp((p - 0.62) / 0.33)).toFixed(3));
  };

  const nav = document.querySelector(".nav");
  const plates = [...document.querySelectorAll(".plate")];
  const hero = document.querySelector(".plate-hero");
  const heroText = hero && hero.querySelector(".plate-text");
  const heroDrawing = hero && hero.querySelector(".drawing");
  const sheetNo = document.querySelector("[data-sheet-no]");
  const sheetName = document.querySelector("[data-sheet-name]");
  const reveals = [...document.querySelectorAll(".reveal")].map((el) => {
    const siblings = [...el.parentElement.children].filter((c) => c.classList.contains("reveal"));
    return { el, lag: Math.min(siblings.indexOf(el), 3) * 0.08 };
  });

  // Resting positions are measured once (and again when layout changes), never per frame,
  // so each frame only writes styles and transforms can't feed back into their own measurement.
  const docTop = (el) => { let y = 0; for (let n = el; n; n = n.offsetParent) y += n.offsetTop; return y; };
  let geo = null;
  const measure = () => {
    geo = {
      plates: plates.map((pl) => {
        const d = pl.querySelector(".drawing");
        return { top: docTop(pl), drawTop: d ? docTop(d) : docTop(pl) };
      }),
      reveals: reveals.map((r) => docTop(r.el)),
    };
  };

  // The first plate is already on screen, so it draws itself over 2.4s after load instead of by scroll.
  if (!reduce && hero) {
    const start = performance.now() + 250;
    const tick = (now) => {
      const p = clamp((now - start) / 2400);
      setDrawing(hero, p);
      if (p < 1) requestAnimationFrame(tick);
    };
    setDrawing(hero, 0);
    requestAnimationFrame(tick);
  }

  let current = "";
  const frame = () => {
    queued = false;
    const h = window.innerHeight;
    const y = window.scrollY;
    nav.classList.toggle("scrolled", y > 8);
    if (!geo) measure();

    // Title block: the sheet whose top has passed the middle of the screen.
    let idx = 0;
    geo.plates.forEach((g, i) => { if (g.top - y < h * 0.45) idx = i; });
    const pl = plates[idx];
    const key = pl.dataset.plate + pl.dataset.name;
    if (key !== current && sheetNo) {
      current = key;
      sheetNo.textContent = pl.dataset.plate;
      sheetName.textContent = pl.dataset.name;
    }
    if (reduce) return;

    // Plates II-VI ink themselves in as their drawing travels up the screen, and un-draw on the way back.
    plates.forEach((p, i) => {
      if (p === hero || !p.querySelector(".drawing")) return;
      const top = geo.plates[i].drawTop - y;
      setDrawing(p, clamp((h * 0.95 - top) / (h * 0.8)));
    });

    // Leaving the specimen: the text lifts away, the drawing drifts slower, like a sheet sliding under glass.
    const hp = clamp(y / (h * 0.9));
    if (heroText) {
      heroText.style.transform = `translate3d(0, ${(-hp * 80).toFixed(1)}px, 0)`;
      heroText.style.opacity = (1 - hp * 0.75).toFixed(3);
    }
    if (heroDrawing) heroDrawing.style.transform = `translate3d(0, ${(hp * 60).toFixed(1)}px, 0)`;

    // Text rises into place over the lower ~40% of the screen.
    reveals.forEach((r, i) => {
      const top = geo.reveals[i] - y;
      let p = easeOut(clamp((h - top) / (h * 0.42) - r.lag));
      if (r.el.contains(document.activeElement)) p = 1;
      r.el.style.opacity = p.toFixed(3);
      r.el.style.transform = `translate3d(0, ${((1 - p) * 40).toFixed(1)}px, 0)`;
    });
  };
  let queued = false;
  const request = () => { if (!queued) { queued = true; requestAnimationFrame(frame); } };
  const remeasure = () => { geo = null; request(); };
  if (lenis) lenis.on("scroll", request);
  window.addEventListener("scroll", request, { passive: true });
  window.addEventListener("resize", remeasure);
  document.addEventListener("focusin", request);
  if (document.fonts && document.fonts.ready) document.fonts.ready.then(remeasure);
  if ("ResizeObserver" in window) new ResizeObserver(remeasure).observe(document.body);
  frame();

  // Film grain is an endless animation: stop it while the tab is hidden.
  document.addEventListener("visibilitychange", () => {
    document.documentElement.classList.toggle("hidden-tab", document.visibilityState === "hidden");
  });

  // ---------- copy the clone command ----------
  const status = document.querySelector(".copy-status");
  document.querySelectorAll("[data-copy]").forEach((btn) => {
    btn.addEventListener("click", async () => {
      const text = document.querySelector(btn.dataset.copy).textContent.trim();
      let ok = false;
      try {
        await navigator.clipboard.writeText(text);
        ok = true;
      } catch {
        const range = document.createRange();
        range.selectNodeContents(document.querySelector(btn.dataset.copy));
        const sel = window.getSelection();
        sel.removeAllRanges();
        sel.addRange(range);
      }
      btn.textContent = ok ? "Copied" : "Copy";
      btn.classList.toggle("copied", ok);
      const msg = ok ? "Copied to your clipboard." : "Selected. Press Ctrl+C or ⌘C to copy.";
      status.textContent = "";
      requestAnimationFrame(() => { status.textContent = msg; });
      setTimeout(() => { status.textContent = ""; }, 4000);
      setTimeout(() => { btn.textContent = "Copy"; btn.classList.remove("copied"); }, 2000);
    });
  });
})();

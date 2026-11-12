// employMint site: smooth scrolling, scroll-linked motion, the self-filling form, and the copy button.
// Every scroll effect is a pure function of scroll position, computed once per frame, so motion runs
// forwards and backwards with the page instead of firing at thresholds. Only opacity and transform change.
(() => {
  const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  const desktop = window.matchMedia("(min-width: 881px)");
  const clamp = (v, lo = 0, hi = 1) => Math.min(hi, Math.max(lo, v));
  const easeOut = (t) => 1 - Math.pow(1 - t, 3);

  // ---------- smooth, inertial scrolling (wheel and trackpad; touch keeps native scrolling) ----------
  let lenis = null;
  if (!reduce && window.Lenis) {
    lenis = new window.Lenis({ lerp: 0.085, wheelMultiplier: 0.95 });
    const raf = (time) => {
      lenis.raf(time);
      requestAnimationFrame(raf);
    };
    requestAnimationFrame(raf);
  }

  // In-page links glide to their section and keep focus where keyboard users expect it.
  document.querySelectorAll('a[href^="#"]').forEach((a) => {
    a.addEventListener("click", (e) => {
      const id = a.getAttribute("href");
      const target = id.length > 1 && document.querySelector(id);
      if (!target) return;
      e.preventDefault();
      if (lenis) lenis.scrollTo(target, { offset: -72, duration: 1.3 });
      else target.scrollIntoView({ behavior: reduce ? "auto" : "smooth" });
      history.replaceState(null, "", id);
      if (target.tabIndex >= 0 || target.id === "main") target.focus({ preventScroll: true });
    });
  });

  // ---------- scroll-linked scene ----------
  const nav = document.querySelector(".nav");
  const heroCopy = document.querySelector(".hero-copy");
  const heroSheet = document.querySelector(".form-demo .sheet");
  const tint = document.querySelector(".tint");
  const tinted = [...document.querySelectorAll("[data-tint]")];
  const stepsList = document.querySelector(".steps");
  const steps = [...document.querySelectorAll(".step")];
  const panels = [...document.querySelectorAll(".panel")];
  const howGrid = document.querySelector(".how-grid");
  const reveals = [...document.querySelectorAll(".reveal")].map((el) => {
    const siblings = [...el.parentElement.children].filter((c) => c.classList.contains("reveal"));
    return { el, lag: Math.min(siblings.indexOf(el), 3) * 0.08 }; // columns in a row arrive a beat apart
  });

  // Resting positions, measured once (and again when layout changes), never per frame: each frame then
  // only writes styles, with no layout reads, and transforms can't feed back into their own measurement.
  const docTop = (el) => { let y = 0; for (let n = el; n; n = n.offsetParent) y += n.offsetTop; return y; };
  let geo = null;
  const measure = () => {
    geo = {
      reveals: reveals.map((r) => docTop(r.el)),
      tinted: tinted.map((s) => ({ top: docTop(s), bottom: docTop(s) + s.offsetHeight })),
      how: howGrid ? { top: docTop(howGrid), height: howGrid.offsetHeight } : null,
      panels: panels.map((pn) => docTop(pn) + pn.offsetHeight / 2),
    };
  };

  const frame = () => {
    queued = false;
    const h = window.innerHeight;
    const y = window.scrollY;
    nav.classList.toggle("scrolled", y > 8);
    if (reduce) return;
    if (!geo) measure();

    // Content rises into place over the lower ~40% of the screen, and settles back if you scroll up.
    reveals.forEach((r, i) => {
      const top = geo.reveals[i] - y;
      let p = easeOut(clamp((h - top) / (h * 0.42) - r.lag));
      if (r.el.contains(document.activeElement)) p = 1; // never hide what has keyboard focus
      r.el.style.opacity = p.toFixed(3);
      r.el.style.transform = `translate3d(0, ${((1 - p) * 56).toFixed(1)}px, 0)`;
    });

    // Leaving the hero: the words lift away a little faster than the page, the form sinks behind them.
    const hp = clamp(y / (h * 0.9));
    if (heroCopy) {
      heroCopy.style.transform = `translate3d(0, ${(-hp * 90).toFixed(1)}px, 0)`;
      heroCopy.style.opacity = (1 - hp * 0.8).toFixed(3);
    }
    if (heroSheet) heroSheet.style.transform = `translate3d(0, ${(hp * 46).toFixed(1)}px, 0) scale(${(1 - hp * 0.05).toFixed(4)})`;

    // One fixed tint layer fades in under the darker sections, so backgrounds blend instead of banding.
    let t = 0;
    for (const s of geo.tinted) {
      const enter = clamp((h * 0.85 - (s.top - y)) / (h * 0.55));
      const leave = clamp((s.bottom - y - h * 0.15) / (h * 0.55));
      t = Math.max(t, Math.min(enter, leave));
    }
    tint.style.opacity = t.toFixed(3);

    // How it works: a line fills down the steps, and the panel nearest the middle comes into focus.
    if (geo.how && desktop.matches) {
      const g = geo.how;
      stepsList.style.setProperty("--p", clamp((h * 0.5 - (g.top - y)) / Math.max(g.height - h * 0.4, 1)).toFixed(3));
      let best = 0;
      let bestD = Infinity;
      panels.forEach((pn, i) => {
        const d = Math.abs(geo.panels[i] - y - h / 2) / h;
        if (d < bestD) { bestD = d; best = i; }
        const k = clamp(d * 1.7);
        pn.style.opacity = (1 - k * 0.72).toFixed(3);
        pn.style.transform = `translate3d(0, 0, 0) scale(${(1 - k * 0.06).toFixed(4)})`;
      });
      steps.forEach((s, i) => s.classList.toggle("is-active", i === best));
    } else {
      panels.forEach((pn) => { pn.style.opacity = ""; pn.style.transform = ""; });
    }
  };
  let queued = false;
  const request = () => {
    if (!queued) { queued = true; requestAnimationFrame(frame); }
  };
  if (lenis) lenis.on("scroll", request);
  window.addEventListener("scroll", request, { passive: true });
  const remeasure = () => { geo = null; request(); };
  window.addEventListener("resize", remeasure);
  if (document.fonts && document.fonts.ready) document.fonts.ready.then(remeasure);
  if ("ResizeObserver" in window) new ResizeObserver(remeasure).observe(document.body);
  document.addEventListener("focusin", request);
  frame();

  // Film grain is an endless animation: stop it while the tab is hidden.
  document.addEventListener("visibilitychange", () => {
    document.documentElement.classList.toggle("hidden-tab", document.visibilityState === "hidden");
  });

  // ---------- the form fills itself in, the pointer heads for Submit, and stops ----------
  const demo = document.querySelector(".form-demo");
  const showAll = () => {
    demo.querySelectorAll(".value").forEach((v) => v.classList.add("on"));
    demo.classList.add("pointing", "done");
  };
  const wait = (ms) => new Promise((r) => setTimeout(r, ms));
  const type = async (el) => {
    const text = el.textContent;
    el.style.minHeight = `${el.offsetHeight}px`; // keep the final height so nothing below moves while typing
    el.textContent = "";
    el.classList.add("on", "caret");
    const step = text.length > 40 ? 6 : 18; // long answers "draft" faster than names are typed; whole run stays under 5s
    for (let i = 1; i <= text.length; i++) {
      el.textContent = text.slice(0, i);
      await wait(step);
    }
    el.classList.remove("caret");
  };
  const play = async () => {
    for (const el of demo.querySelectorAll(".value")) {
      if (el.hasAttribute("data-type")) await type(el);
      else { el.classList.add("on"); await wait(220); }
      await wait(80);
    }
    await wait(150);
    demo.classList.add("pointing");
    await wait(1100);
    demo.classList.add("done");
  };
  if (demo) {
    if (reduce || !("IntersectionObserver" in window)) showAll();
    else {
      const io = new IntersectionObserver((entries) => {
        if (entries.some((e) => e.isIntersecting)) {
          io.disconnect();
          setTimeout(play, 300);
        }
      }, { threshold: 0.35 });
      io.observe(demo);
    }
  }

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
      status.textContent = ""; // clear first so screen readers announce a repeat
      requestAnimationFrame(() => { status.textContent = msg; });
      setTimeout(() => { status.textContent = ""; }, 4000);
      setTimeout(() => {
        btn.textContent = "Copy";
        btn.classList.remove("copied");
      }, 2000);
    });
  });
})();

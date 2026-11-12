// employMint specimen file: plates that snap one per scroll (native scroll snapping), images that come out of a washed, grainy haze as
// they settle, a title block that follows the sheet you're on, and the copy button. Every effect is a pure
// function of scroll position (or, for the first plate, of time since load).
(() => {
  const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  const clamp = (v, lo = 0, hi = 1) => Math.min(hi, Math.max(lo, v));
  const smooth = (t) => t * t * (3 - 2 * t);
  const easeOut = (t) => 1 - Math.pow(1 - t, 3);

  // ---------- in-page links: the browser's scroll snapping takes it from here ----------
  document.querySelectorAll('a[href^="#"]').forEach((a) => {
    a.addEventListener("click", (e) => {
      const id = a.getAttribute("href");
      const target = id.length > 1 && document.querySelector(id);
      if (!target) return;
      e.preventDefault();
      target.scrollIntoView({ behavior: reduce ? "auto" : "smooth" });
      history.replaceState(null, "", id);
      if (target.id === "main") target.focus({ preventScroll: true });
    });
  });

  // A camera flash on an image: the specimen is photographed for the file.
  const flash = (el) => {
    const ph = el && el.querySelector(".photo");
    if (!ph || reduce) return;
    ph.classList.remove("flashing"); void ph.offsetWidth; ph.classList.add("flashing");
  };
  const nav = document.querySelector(".nav");
  const plates = [...document.querySelectorAll(".plate")];
  const hero = document.querySelector(".plate-hero");
  const sheetNo = document.querySelector("[data-sheet-no]");
  const sheetName = document.querySelector("[data-sheet-name]");
  const reveals = [...document.querySelectorAll(".reveal")].map((el) => {
    const siblings = [...el.parentElement.children].filter((c) => c.classList.contains("reveal"));
    return { el, lag: Math.min(siblings.indexOf(el), 3) * 0.08 };
  });

  // Resting positions are measured once (and again when layout changes), never per frame.
  const docTop = (el) => { let y = 0; for (let n = el; n; n = n.offsetParent) y += n.offsetTop; return y; };
  let geo = null;
  const measure = () => {
    geo = { plates: plates.map((pl) => docTop(pl)), reveals: reveals.map((r) => docTop(r.el)) };
  };

  // The first plate is already on screen: it develops out of the wash over 2.6s after load.
  if (!reduce && hero) {
    const start = performance.now() + 200;
    const tick = (now) => {
      const p = clamp((now - start) / 2600); // a slower develop, like a print coming up in the tray
      hero.style.setProperty("--clear", smooth(p).toFixed(3));
      if (p < 1) requestAnimationFrame(tick);
    };
    hero.style.setProperty("--clear", "0");
    setTimeout(() => flash(hero), 180);
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
    geo.plates.forEach((top, i) => { if (top - y < h * 0.45) idx = i; });
    const pl = plates[idx];
    const key = pl.dataset.plate + pl.dataset.name;
    if (key !== current && sheetNo) {
      if (current) flash(pl); // each plate is photographed as it arrives
      current = key;
      sheetNo.textContent = pl.dataset.plate;
      sheetName.textContent = pl.dataset.name;
    }
    if (reduce) return;

    // Each plate's image is washed out and grainy while it travels in, and clear once it has snapped into place.
    plates.forEach((p, i) => {
      if (p === hero) return;
      const top = geo.plates[i] - y;
      p.style.setProperty("--clear", smooth(clamp(1 - top / (h * 0.75))).toFixed(3));
    });

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
  window.addEventListener("scroll", request, { passive: true });
  window.addEventListener("resize", remeasure);
  document.addEventListener("focusin", request);
  if (document.fonts && document.fonts.ready) document.fonts.ready.then(remeasure);
  if ("ResizeObserver" in window) new ResizeObserver(remeasure).observe(document.body);
  frame();

  // ---------- light / dark toggle ----------
  // The page follows the system until you choose; your choice is remembered on this device.
  const root = document.documentElement;
  const toggle = document.querySelector(".theme-toggle");
  const systemDark = window.matchMedia("(prefers-color-scheme: dark)");
  const isDark = () => (root.dataset.theme ? root.dataset.theme === "dark" : systemDark.matches);
  const syncToggle = () => {
    const dark = isDark();
    if (toggle) toggle.setAttribute("aria-pressed", String(dark));
    document.querySelectorAll('meta[name="theme-color"]').forEach((m) => m.setAttribute("content", dark ? "#171613" : "#f2ede2"));
  };
  if (toggle) {
    toggle.addEventListener("click", () => {
      const next = isDark() ? "light" : "dark";
      const apply = () => {
        root.dataset.theme = next;
        try { localStorage.setItem("employmint-theme", next); } catch (e) { /* private mode: still switches */ }
        syncToggle();
      };
      if (reduce) { apply(); return; }
      if (document.startViewTransition) {
        // The new theme spreads out from the switch in a growing circle, like a light coming on.
        const b = toggle.getBoundingClientRect();
        const x = b.left + b.width / 2, y = b.top + b.height / 2;
        const r = Math.hypot(Math.max(x, window.innerWidth - x), Math.max(y, window.innerHeight - y));
        document.startViewTransition(apply).ready.then(() => {
          root.animate({ clipPath: [`circle(0px at ${x}px ${y}px)`, `circle(${r}px at ${x}px ${y}px)`] },
                       { duration: 750, easing: "cubic-bezier(.65, 0, .35, 1)", pseudoElement: "::view-transition-new(root)" });
        }).catch(() => {});
      } else {
        // No View Transitions: colours fade across instead of snapping.
        root.classList.add("theme-fade");
        apply();
        setTimeout(() => root.classList.remove("theme-fade"), 550);
      }
    });
  }
  systemDark.addEventListener("change", syncToggle);
  syncToggle();

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

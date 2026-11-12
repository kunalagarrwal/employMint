// employMint specimen file: plates that snap one per scroll (native scroll snapping), images that develop out of a
// grainy haze when their plate arrives, a title block that follows the sheet you're on, the theme switch and the copy
// button. Scrolling itself runs no JavaScript work: observers flip classes, CSS transitions do the motion.
(() => {
  const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

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

  // Nothing here runs per scroll frame. Two observers fire only when a plate crosses a line:
  // - a plate "develops" (.on) when a good part of it is on screen, and fades back when it leaves, so it develops
  //   again next time; CSS does the rest with opacity and transform transitions.
  // - the title block follows the plate under the middle of the screen, and that plate gets its camera flash.
  if (reduce || !("IntersectionObserver" in window)) {
    plates.forEach((p) => p.classList.add("on"));
  } else {
    const develop = new IntersectionObserver((entries) => {
      entries.forEach((e) => { if (e.target !== hero || e.isIntersecting) e.target.classList.toggle("on", e.isIntersecting); });
    }, { threshold: 0.3 });
    plates.forEach((p) => { if (p !== hero) develop.observe(p); });
    // The first plate is already on screen: it develops over a few seconds after load, with a flash.
    if (hero) requestAnimationFrame(() => requestAnimationFrame(() => { hero.classList.add("on"); flash(hero); }));
  }
  let current = null;
  if ("IntersectionObserver" in window && sheetNo) {
    // rootMargin shrinks the viewport to a thin line 45% down the screen: whichever plate crosses it is current.
    const follow = new IntersectionObserver((entries) => {
      entries.forEach((e) => {
        if (!e.isIntersecting || e.target === current) return;
        if (current) flash(e.target); // each plate is photographed as it arrives
        current = e.target;
        sheetNo.textContent = e.target.dataset.plate;
        sheetName.textContent = e.target.dataset.name;
      });
    }, { rootMargin: "-45% 0px -54% 0px" });
    plates.forEach((p) => follow.observe(p));
  }
  // The nav gets its hairline once the page has moved; a cheap check that only writes when it changes.
  let scrolled = null;
  const onScroll = () => { const s = window.scrollY > 8; if (s !== scrolled) { scrolled = s; nav.classList.toggle("scrolled", s); } };
  window.addEventListener("scroll", onScroll, { passive: true });
  onScroll();

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
  // Ink: the outline of a drop of ink spreading over paper from (x, y), as clip-path polygons over time. It is a vector
  // shape, so the edge stays crisp at any size. The outline is a circle bent by a few slow, low lobes that drift as it
  // grows, so it moves like liquid rather than a perfect circle, and its centre flows a little across the page.
  const inkFrames = (x, y) => {
    const W = innerWidth, H = innerHeight, N = 120, F = 36;
    const lobes = [2, 3, 4, 5, 7, 11].map((k) => ({
      k, a: (k < 6 ? 0.032 : 0.007) / Math.sqrt(k / 2), ph: Math.random() * 6.283, sp: (Math.random() - 0.5) * 1.6,
    }));
    const amp = lobes.reduce((s, l) => s + l.a, 0);
    const dx = (W / 2 - x) * 0.22, dy = (H / 2 - y) * 0.22; // the ink runs a little towards the middle of the sheet
    const far = Math.hypot(Math.max(x + dx, W - x - dx), Math.max(y + dy, H - y - dy));
    const R = (far / (1 - amp)) * 1.04;
    const frames = [];
    for (let f = 0; f < F; f++) {
      const t = f / (F - 1);
      const p = t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2; // gathers, spreads, then settles
      const cx = x + dx * p, cy = y + dy * p, r = R * p;
      const pts = [];
      for (let i = 0; i < N; i++) {
        const th = (i / N) * 6.283;
        let w = 1;
        for (const l of lobes) w += l.a * Math.sin(l.k * th + l.ph + l.sp * t * 3);
        pts.push(`${(cx + Math.cos(th) * r * w).toFixed(1)}px ${(cy + Math.sin(th) * r * w).toFixed(1)}px`);
      }
      frames.push({ clipPath: `polygon(${pts.join(",")})`, offset: t });
    }
    return frames;
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
        // Going dark, ink spreads from the switch until the whole sheet is dark. Going light, the same ink draws
        // back into the switch: the old (dark) page sits on top and its outline shrinks away.
        const b = toggle.getBoundingClientRect();
        const frames = inkFrames(b.left + b.width / 2, b.top + b.height / 2);
        const soak = next === "dark";
        root.classList.add(soak ? "ink-in" : "ink-out");
        const vt = document.startViewTransition(apply);
        vt.ready.then(() => {
          root.animate(soak ? frames : frames.reverse().map((k, i, a) => ({ ...k, offset: i / (a.length - 1) })), {
            duration: soak ? 1250 : 1050, easing: "linear", fill: "both",
            pseudoElement: soak ? "::view-transition-new(root)" : "::view-transition-old(root)",
          });
        }).catch(() => {});
        vt.finished.finally(() => root.classList.remove("ink-in", "ink-out"));
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

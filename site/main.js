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
  // The ink stain is fetched once the page is idle, so the first switch already has it.
  let inkReady = false;
  if (toggle && !reduce && document.startViewTransition && CSS.supports("mask-size", "1px 1px")) {
    const later = window.requestIdleCallback || ((f) => setTimeout(f, 1200));
    later(() => { const im = new Image(); im.onload = () => { inkReady = true; }; im.src = "img/ink-blot.png"; });
  }
  if (toggle) {
    toggle.addEventListener("click", () => {
      const next = isDark() ? "light" : "dark";
      const apply = () => {
        root.dataset.theme = next;
        try { localStorage.setItem("employmint-theme", next); } catch (e) { /* private mode: still switches */ }
        syncToggle();
      };
      if (reduce) { apply(); return; }
      if (document.startViewTransition && inkReady) {
        // Ink: going dark, a drop lands on the switch and soaks across the paper until the whole sheet is dark.
        // Going light, the ink draws back out of the paper into the switch. The stain is an image used as a mask on
        // the page snapshot (img/ink-blot.png), scaled from nothing to larger than the screen.
        const b = toggle.getBoundingClientRect();
        const x = b.left + b.width / 2, y = b.top + b.height / 2;
        const reach = Math.hypot(Math.max(x, innerWidth - x), Math.max(y, innerHeight - y));
        const size = reach / 0.33; // the blot's solid core is about a third of its image: make the core cover the screen
        const at = (s) => ({ maskSize: `${s}px ${s}px`, maskPosition: `${x - s / 2}px ${y - s / 2}px`,
                             webkitMaskSize: `${s}px ${s}px`, webkitMaskPosition: `${x - s / 2}px ${y - s / 2}px` });
        const soak = next === "dark";
        root.classList.add(soak ? "ink-in" : "ink-out");
        const vt = document.startViewTransition(apply);
        vt.ready.then(() => {
          root.animate(soak ? [at(0), at(size * 0.18), at(size)] : [at(size), at(size * 0.18), at(0)], {
            duration: soak ? 1300 : 1100, fill: "both", pseudoElement: soak ? "::view-transition-new(root)" : "::view-transition-old(root)",
            easing: soak ? "cubic-bezier(.4, 0, .2, 1)" : "cubic-bezier(.6, 0, .5, 1)",
          });
        }).catch(() => {});
        vt.finished.finally(() => root.classList.remove("ink-in", "ink-out"));
      } else if (document.startViewTransition) {
        // Ink stain not loaded yet: a plain circle from the switch.
        const b = toggle.getBoundingClientRect();
        const x = b.left + b.width / 2, y = b.top + b.height / 2;
        const r = Math.hypot(Math.max(x, innerWidth - x), Math.max(y, innerHeight - y));
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

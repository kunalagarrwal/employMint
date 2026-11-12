// employMint site: scroll reveals, the self-filling form, the pinned steps, and the copy button.
(() => {
  const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  // Nav gets a hairline once the page scrolls.
  const nav = document.querySelector(".nav");
  const onScroll = () => nav.classList.toggle("scrolled", window.scrollY > 8);
  onScroll();
  window.addEventListener("scroll", onScroll, { passive: true });

  // Sections fade up as they arrive; siblings arrive a beat apart.
  const reveals = [...document.querySelectorAll(".reveal")];
  if (reduce || !("IntersectionObserver" in window)) {
    reveals.forEach((el) => el.classList.add("in"));
  } else {
    reveals.forEach((el) => {
      const siblings = [...el.parentElement.children].filter((c) => c.classList.contains("reveal"));
      el.style.setProperty("--d", `${Math.min(siblings.indexOf(el), 4) * 90}ms`);
    });
    const io = new IntersectionObserver((entries) => {
      entries.forEach((e) => {
        if (e.isIntersecting) {
          e.target.classList.add("in");
          io.unobserve(e.target);
        }
      });
    }, { rootMargin: "0px 0px -8% 0px", threshold: 0.12 });
    reveals.forEach((el) => io.observe(el));
  }

  // The form fills itself in, the pointer heads for Submit, and stops.
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

  // How it works: the step beside the panel in view lights up.
  const steps = [...document.querySelectorAll(".step")];
  const panels = [...document.querySelectorAll(".panel")];
  if (steps.length && "IntersectionObserver" in window) {
    const io = new IntersectionObserver((entries) => {
      entries.forEach((e) => {
        if (!e.isIntersecting) return;
        const n = e.target.dataset.panel;
        steps.forEach((s) => s.classList.toggle("is-active", s.dataset.step === n));
      });
    }, { rootMargin: "-45% 0px -45% 0px" });
    panels.forEach((p) => io.observe(p));
  }

  // Copy the clone command.
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

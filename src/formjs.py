"""JavaScript that employMint runs inside application pages: read the form, mark fields, show the panel."""


# Tags each question block with data-em-q, each control with data-em-c and each clickable option with data-em-o,
# then returns [{i, title, kind, required, options, visible}].
EXTRACT_JS = r"""() => {
  // Single-page sites (Workday) keep the page between steps: clear tags left by earlier passes first.
  document.querySelectorAll('[data-em-q], [data-em-c], [data-em-o]').forEach(el => {
    el.removeAttribute('data-em-q'); el.removeAttribute('data-em-c'); el.removeAttribute('data-em-o'); });
  const T = el => (el ? (el.innerText || el.textContent || '') : '').replace(/\s+/g, ' ').trim();
  const vis = el => { if (!el) return false; const r = el.getBoundingClientRect(); const s = getComputedStyle(el);
                      return r.width > 0 && r.height > 0 && s.visibility !== 'hidden' && s.display !== 'none'; };
  const CONT = ['[data-automation-id^="formField-"]', 'li.application-question', '.ashby-application-form-field-entry', '[class*="_fieldEntry"]',
                '.select__container', '.text-input-wrapper', '.file-upload', 'fieldset', '.field-wrapper', '.field', '.form-group'];
  const SKIP = new Set(['hidden', 'submit', 'button', 'image', 'reset', 'search']);
  const ctrls = [...document.querySelectorAll('input, select, textarea, button[aria-haspopup="listbox"]')].filter(el =>
    (el.tagName === 'BUTTON' || !SKIP.has(el.type)) && el.name !== 'g-recaptcha-response' &&
    !el.closest('.grecaptcha-badge, [class*="autofill"], .iti__dropdown-content, #employmint-panel, header, nav, [data-automation-id="utilityButtonBar"], [data-automation-id="header"]'));
  const groups = [], byCont = new Map();
  for (const el of ctrls) {
    let c = null;
    for (const s of CONT) { c = el.closest(s); if (c) break; }
    if (!c) c = el.parentElement;
    if (!byCont.has(c)) { const g = {c, els: []}; byCont.set(c, g); groups.push(g); }
    byCont.get(c).els.push(el);
  }
  // A block holding several different fields (e.g. Ashby "Education History": school, degree, major, dates,
  // "still a student") is split so each field gets its own label and answer.
  const isChoice = e => e.type === 'radio' || e.type === 'checkbox';
  const split = [];
  // Hidden helper inputs inside dropdown widgets (no id, name, placeholder or label) are not fields.
  const aux = e => e.tagName === 'INPUT' && !e.id && !e.name && !e.placeholder && !e.getAttribute('aria-label');
  for (const g of groups) {
    const real = g.els.filter(e => !aux(e));
    const plain = real.filter(e => !isChoice(e));
    if (plain.length < 2 && !(plain.length === 1 && real.length > 1)) { split.push(g); continue; }
    const byName = new Map();
    for (const el of real) {
      const key = el.type === 'radio' && el.name ? 'r:' + el.name : el;
      if (!byName.has(key)) byName.set(key, []);
      byName.get(key).push(el);
    }
    for (const els of byName.values()) {
      let w = els[0];  // smallest wrapper that holds this field and no other field of the block
      while (w.parentElement && w.parentElement !== g.c && !g.els.some(o => !els.includes(o) && w.parentElement.contains(o))) w = w.parentElement;
      split.push({c: w, els, parent: g.c, all: g.els});
    }
  }
  groups.length = 0; groups.push(...split);
  const optTarget = el => {
    if (el.id) { const l = document.querySelector(`label[for="${CSS.escape(el.id)}"]`); if (l) return l; }
    return el.closest('label') || el;
  };
  const labelOf = el => {
    if (el.id) { const l = document.querySelector(`label[for="${CSS.escape(el.id)}"]`); if (l && T(l)) return T(l); }
    const lb = el.getAttribute('aria-labelledby');
    if (lb) { const t = lb.split(/\s+/).map(x => document.getElementById(x)).filter(Boolean).map(T).join(' '); if (t) return t; }
    return el.getAttribute('aria-label') || T(el.closest('label')) || el.placeholder || '';
  };
  const LABELS = 'legend, .application-label, label, [class*="question-title"], [class*="_heading"], [class*="label"], [class*="Label"]';
  // Label for one field inside a split block: its own <label>, else the nearest label above it in the block.
  const subLabel = g => {
    const el = g.els[0];
    let t = '';
    if (!(g.els.length === 1 && isChoice(el))) {
      if (el.id) { const l = document.querySelector(`label[for="${CSS.escape(el.id)}"]`); if (l) t = T(l); }
      if (!t) t = el.getAttribute('aria-label') || '';
      for (let a = el.parentElement; !t && a && a !== g.parent.parentElement; a = a.parentElement) {
        const l = [...a.querySelectorAll(LABELS)].find(x => T(x) && !g.all.some(o => x.contains(o) || (o.id && x.getAttribute('for') === o.id && !g.els.includes(o))));
        if (l) t = T(l);
      }
    } else {
      t = labelOf(el);
    }
    if (el.tagName === 'SELECT' && el.options.length) {
      const first = T(el.options[0]).replace(/[.…]+$/, '');
      if (first && first.length < 15 && !t.toLowerCase().includes(first.toLowerCase())) t = (t ? t + ' ' : '') + first;
    }
    return t || el.placeholder || '';
  };
  const out = [];
  groups.forEach((g, i) => {
    const {c, els} = g, e0 = els[0];
    const choice = els.every(isChoice);
    const optEls = new Set(choice ? els.map(optTarget) : []);
    let title = '';
    if (g.parent) title = subLabel(g);
    else for (const cand of c.querySelectorAll(LABELS)) {
      if (optEls.has(cand) || [...optEls].some(o => cand.contains(o) || o.contains(cand))) continue;
      if (cand.tagName !== 'LEGEND' && els.some(e => cand.contains(e))) continue;
      const t = T(cand);
      if (t) { title = t; break; }
    }
    if (!title && !choice) title = labelOf(e0);
    if (!title) title = (T(c).split(/(?<=[?:*])\s/)[0] || '').slice(0, 200);
    const required = /[*✱]/.test(title) || els.some(e => e.required || e.getAttribute('aria-required') === 'true');
    title = title.replace(/[*✱]/g, ' ').replace(/\s+/g, ' ').trim();
    const yn = [...c.querySelectorAll('button')].filter(b => /^(yes|no)$/i.test(T(b)));
    let kind, options = [];
    if (e0.getAttribute('data-uxi-widget-type') === 'selectinput') kind = 'prompt';  // Workday search-and-pick
    else if (e0.tagName === 'BUTTON') kind = 'listbox';  // Workday-style dropdown
    else if (e0.type === 'file') kind = 'file';
    else if (choice && els.length === 1 && yn.length >= 2) { kind = 'yesno'; options = yn.map(T); yn.forEach((b, j) => b.setAttribute('data-em-o', `${i}-${j}`)); }
    else if (choice && els.length === 1 && e0.type === 'checkbox') { kind = 'check'; options = [labelOf(e0) || title]; optTarget(e0).setAttribute('data-em-o', `${i}-0`); }
    else if (choice) { kind = els.some(e => e.type === 'radio') ? 'radio' : 'checks';
                       els.forEach((e, j) => { options.push(T(optTarget(e)) || e.value); optTarget(e).setAttribute('data-em-o', `${i}-${j}`); }); }
    else if (e0.tagName === 'SELECT') { kind = 'select'; options = [...e0.options].map(T).filter(Boolean); }
    else if (e0.getAttribute('role') === 'combobox' || e0.closest('.select__control') || e0.getAttribute('aria-autocomplete')) kind = 'combo';
    else if (e0.tagName === 'TEXTAREA') kind = 'textarea';
    else kind = e0.type === 'number' ? 'number' : 'text';
    c.setAttribute('data-em-q', i);
    els.forEach((e, j) => e.setAttribute('data-em-c', `${i}-${j}`));
    let value = '';
    if (kind === 'prompt') value = [...c.querySelectorAll('[data-automation-id="selectedItem"]')].map(T).join(', ');
    else if (kind === 'listbox') value = T(e0).replace(/^select( one)?\.*$/i, '');
    else if (kind === 'file') value = (e0.files && e0.files.length) ? e0.files[0].name :
      T(c.querySelector('[data-automation-id="file-upload-item-name"]')) || (c.querySelector('[data-automation-id="delete-file"]') ? 'uploaded file' : '');
    else if (kind === 'select') value = e0.selectedIndex > 0 ? T(e0.options[e0.selectedIndex]) : '';
    else if (kind === 'radio' || kind === 'checks') value = els.filter(e => e.checked).map(e => T(optTarget(e))).join(', ');
    else if (kind !== 'check' && kind !== 'yesno') value = (e0.value || '').trim();
    out.push({i, title, kind, options, required, value, inEntry: !!c.closest('[data-em-g]'), visible: vis(c) || vis(e0) || kind === 'file',
              disabled: els.every(e => e.disabled), checked: kind === 'check' && e0.checked});
  });
  return out;
}"""

MARK_JS = r"""([i, state, note]) => {
  const c = document.querySelector(`[data-em-q="${i}"]`);
  if (!c) return;
  const color = {filled: '#1a7f37', drafted: '#1f5eff', check: '#b26b00', you: '#d92d20'}[state];
  c.style.outline = `2px solid ${color}`; c.style.outlineOffset = '4px'; c.style.borderRadius = '6px';
  if (note) c.title = 'employMint: ' + note;
}"""

PANEL_JS = r"""([items, filled, company, queue]) => {
  // queue: {pos, total} inside the apply queue, plus review: {fit, why, gaps} from the tailored resume.
  document.getElementById('employmint-panel')?.remove();
  queue = queue || {};
  const p = document.createElement('div');
  p.id = 'employmint-panel';
  p.style.cssText = 'position:fixed;top:12px;right:12px;z-index:2147483647;width:320px;max-height:70vh;overflow:auto;' +
    'background:#fff;color:#1b1b1b;border:1px solid #ccc;border-radius:12px;box-shadow:0 6px 24px rgba(0,0,0,.18);' +
    'font:13px/1.45 -apple-system,BlinkMacSystemFont,sans-serif;padding:12px 14px';
  const esc = s => String(s).replace(/[&<>"]/g, ch => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;'}[ch]));
  const dot = c => `<span style="display:inline-block;width:9px;height:9px;border-radius:50%;background:${c};margin-right:6px"></span>`;
  const col = {drafted: '#1f5eff', check: '#b26b00', you: '#d92d20'};
  const act = typeof window.employmintAction === 'function';
  const rv = queue.review || {};
  const fitWord = f => f >= 8 ? 'strong fit' : f >= 6 ? 'fair fit' : 'long shot';
  const review = (rv.fit || rv.why || (rv.gaps || []).length) ?
    `<div style="margin:6px 0;padding:8px 10px;background:#f6f6f4;border-radius:8px">` +
    (rv.fit ? `<b>Fit ${esc(rv.fit)}/10</b> <span style="color:#666">· ${fitWord(+rv.fit)}</span><br>` : '') +
    (rv.why ? `<span>${esc(rv.why)}</span>` : '') +
    ((rv.gaps || []).length ? `<br><span style="color:#666">Gaps: ${rv.gaps.map(esc).join('; ')}</span>` : '') + `</div>` : '';
  const remember = it => (it.remember && act) ?
    `<label style="display:block;margin-top:3px;color:#1b1b1b;cursor:pointer"><input type="checkbox" data-rem="${it.i}"` +
    `${it.on ? ' checked' : ''} style="margin:0 5px 0 0;vertical-align:-2px">Remember my answer for ${esc(it.remember)} questions</label>` : '';
  p.innerHTML = `<div style="display:flex;justify-content:space-between;align-items:center"><b>employMint · ${esc(company)}</b>` +
    `<button id="em-min" style="border:0;background:none;cursor:pointer;font-size:16px">–</button></div>` +
    `<div id="em-body">` + (queue.total ? `<p style="margin:4px 0;color:#666">Job ${queue.pos} of ${queue.total} in your queue</p>` : '') +
    review +
    `<p style="margin:6px 0">${dot('#1a7f37')}${filled} fields filled from your profile.</p>` +
    (items.length ? '<p style="margin:6px 0 4px"><b>Look at these:</b></p>' : '<p>Nothing flagged.</p>') +
    items.map(it => `<div style="padding:4px 0;border-top:1px solid #eee"><a href="#" data-q="${it.i}" style="display:block;color:inherit;text-decoration:none">` +
      `${dot(col[it.state])}<b>${esc(it.title.slice(0, 70))}</b><br><span style="color:#666">${esc(it.note)}</span></a>${remember(it)}</div>`).join('') +
    `<p style="margin:10px 0 0;padding-top:8px;border-top:1px solid #eee"><b>Read everything, then click Submit yourself.</b> ` +
    `Submitting is your yes. This tool never submits.</p>` +
    (act ?
      `<div style="display:flex;gap:6px;flex-wrap:wrap;margin-top:8px">` +
      `<button data-act="manual" title="Use this if you submitted but no confirmation page was detected">I submitted it</button>` +
      `<button data-act="pass" title="Don't apply to this job. It moves to Skipped on the review page">Not for me</button>` +
      (queue.total ? `<button data-act="skip" title="Leave it for another time">Later</button><button data-act="stop">Stop queue</button>` : '') +
      `</div>` : '') + `</div>`;
  document.body.appendChild(p);
  p.querySelectorAll('button[data-act]').forEach(b => {
    b.style.cssText = 'font:12px sans-serif;padding:5px 9px;border:1px solid #bbb;border-radius:7px;background:#f6f6f4;cursor:pointer';
    b.onclick = () => { b.disabled = true; b.textContent = 'OK…'; window.employmintAction(b.dataset.act); };
  });
  p.querySelectorAll('input[data-rem]').forEach(c => c.onchange = () =>
    window.employmintAction(`remember:${c.dataset.rem}:${c.checked ? 1 : 0}`));
  p.querySelector('#em-min').onclick = () => { const b = p.querySelector('#em-body'); b.style.display = b.style.display === 'none' ? '' : 'none'; };
  p.querySelectorAll('a[data-q]').forEach(a => a.onclick = ev => { ev.preventDefault();
    document.querySelector(`[data-em-q="${a.dataset.q}"]`)?.scrollIntoView({behavior: 'smooth', block: 'center'}); });
  const sub = [...document.querySelectorAll('button, input[type=submit]')].find(b =>
    /^(submit|submit application|apply|send application)$/i.test((b.innerText || b.value || '').trim()));
  if (sub) { sub.style.outline = '3px dashed #7c3aed'; sub.style.outlineOffset = '4px'; }
}"""

# What the applicant has entered in the listed questions right now: [{i, text, value}] (text: the block's
# words, to check the tag still points at the same question). Used to save answers they ticked "Remember".
READ_JS = r"""(ids) => ids.map(i => {
  const c = document.querySelector(`[data-em-q="${i}"]`);
  if (!c) return null;
  const T = el => (el ? (el.innerText || el.textContent || '') : '').replace(/\s+/g, ' ').trim();
  const els = [...c.querySelectorAll(`[data-em-c^="${i}-"]`)];
  const e0 = els[0];
  let value = '';
  if (!e0) value = '';
  else if (e0.type === 'radio' || e0.type === 'checkbox') {
    value = els.filter(e => e.checked).map(e => {
      const l = e.id && document.querySelector(`label[for="${CSS.escape(e.id)}"]`);
      return T(l || e.closest('label')) || e.value; }).join(', ');
  } else if (e0.tagName === 'SELECT') value = e0.selectedIndex > 0 ? T(e0.options[e0.selectedIndex]) : '';
  else if (e0.tagName === 'BUTTON') value = T(e0).replace(/^select( one)?\.*$/i, '');
  else {
    const picked = c.querySelector('.select__single-value, [class*="singleValue"], [class*="single-value"], [data-automation-id="selectedItem"]');
    value = picked ? T(picked) : (e0.value || '').trim();
  }
  if (!value) {  // yes/no button pairs (Ashby): the pressed one
    const on = [...c.querySelectorAll('[data-em-o]')].find(b => b.getAttribute('aria-pressed') === 'true' ||
      /(^|[_-])(active|selected|checked)/i.test(b.className || ''));
    if (on) value = T(on);
  }
  return {i, text: T(c).slice(0, 400), value};
})"""

BANNER_JS = """(msg) => { document.getElementById('employmint-banner')?.remove();
  const d = document.createElement('div'); d.id = 'employmint-banner'; d.textContent = msg;
  d.style.cssText = 'position:fixed;top:12px;left:50%;transform:translateX(-50%);z-index:2147483647;background:#1a7f37;' +
    'color:#fff;padding:10px 16px;border-radius:10px;font:14px -apple-system,sans-serif;box-shadow:0 4px 16px rgba(0,0,0,.2)';
  document.body.appendChild(d); }"""

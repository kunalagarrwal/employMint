# Code tour: one job, from listing to "applied"

Follow a single internship through the system. Each stop names the file and function, what it does,
and the design decision behind it.

## 1. Finding it: `src/jobs.py`

- **`cmd_fetch`** downloads the SimplifyJobs list for your season (from `preferences.json`) into SQLite.
- **`classify`** assigns a track (SWE, AI, product, fintech, design) from the title and drops
  roles that don't fit, like PhD-only or non-US jobs.
- **`visa_flags`** scans the downloaded description with the regexes in `VISA_PATTERNS`
 . If you need sponsorship, anything blocking (citizenship, clearance, "will not sponsor", no CPT) removes
  the job before any work is spent on it.
  *Decision:* skip boilerplate like "without regard to citizenship"; an F-1 student shouldn't lose a job
  to an equal-opportunity sentence. `tests/test_jobs.py` locks that in.
- **`score_job`** gives 0–100: track priority, skill overlap with the profile, graduation
  date match, sponsorship, freshness.
- **`cmd_batch`** picks today's jobs, at most one per company and respecting each
  company's application limit.

## 2. Writing the resume: the `tailor-resume` skill + `src/verify.py`

Your AI assistant reads the posting and writes `resumes/<slug>/tailored.json`. Every bullet cites the facts it uses:

```json
{"text": "Built a room-booking web app in React and Flask used by 3 campus offices", "sources": ["campus-it:0"]}
```

**`verify`** is the gate. For each bullet it pulls the cited facts and compares:
`numbers_in` — any number not in the facts is an error; `terms_in` —
any technology not in the facts or the entry's skills is an error. Skills, courses and certifications must
exist in the profile.
*Decision:* the model is allowed to reword, never to add. The check is plain code so it can't be
talked out of it.

`render.py` `main` then renders the PDF at the largest font that fits one page, and
`measure` reports how full the page is and flags bullets that wrap onto a lonely word.

## 3. Deciding: `src/review.py`

`page` shows each job with its fit score, gaps, pay, location and sponsorship signal.
You click Approve or Skip. Approved jobs feed the apply queue.
*Decision:* the server binds to 127.0.0.1 and `Handler.trusted` rejects requests whose Host or Origin
isn't local, so a website can't use DNS rebinding to approve jobs or read the page.

## 4. Filling the form: `src/apply.py` and friends

`cmd_queue` opens one Chrome window and goes through approved jobs. For each one:

1. **`prepare`** opens the form URL and routes by site:
   Workday → `site_workday.workday_flow`;
   Lever → `site_lever.lever_handoff`; everything else → `fill.fill_form`.
2. **`fill_form`** runs `formjs.EXTRACT_JS` to read every question, uploads the resume first
   (sites parse it and may overwrite fields), then answers each question.
3. **`answers.resolve`** finds the answer: the job's drafts first, then the saved rules.
   **`pick_option`** picks the option.
   *Decision:* rules are ordered regexes with a fallback list, best first. Each real-world miss became a
   rule fix plus a case in your hand-checked set (`evals/golden_answers.json`).
4. **`fill_question`** types, selects or clicks, and returns filled / drafted / check / you.
   One failing field is logged and marked *you*; it never stops the rest.
5. **`wait_outcome`** waits. `page_tools.submitted` watches for a
   confirmation page, and **`mark_applied`** records it.

### Workday

`workday_flow` handles sign-in (you type your own password), resume autofill, then each wizard step:
fill, save a local snapshot for debugging, Save and Continue, and stop at Review.
`wd_experience` builds Education and Work Experience entries from the profile
(`preferences.workday_experience` picks which jobs),
updating entries the resume parser already created instead of duplicating them.

### Lever

Lever puts an invisible hCaptcha on Submit, and it rejects script-controlled browsers.
*Decision:* don't evade it. `lever_handoff` opens the form in your normal Chrome and shows an answer
sheet with every question answered and a Copy button, built by `lever_rows` → `answers.sheet_answer`.

## 5. Measuring: `src/evals.py`

Five numbers: form-answer accuracy on the golden set, the share of required questions answered on real
forms, resumes fully grounded, cover letters passing the check, and page fill. Each run appends to
`evals/history.jsonl`, so a change to the rules can be judged by whether the numbers go up.
Exits non-zero if any hand-checked answer is wrong, so it can gate changes to your answer rules.

## Design questions

- *Why rules instead of letting the model fill the form?* Visa and consent answers must be exact and
  explainable; a regex rule with a test is auditable, a model's guess isn't.
- *What happens when a site changes its layout?* The extractor reads labels and roles, not fixed selectors,
  for Greenhouse, Ashby and Lever. Failures surface as *you* fields in the panel and as a lower coverage
  number in the evals.
- *How do you know it doesn't make things up?* `verify.py`, the cover letter check, and the grounding
  share in the eval report (100% across 88 resumes on the author's applications).
- *What would you do next?* Run the extractor against saved page snapshots in CI, and track coverage per site.

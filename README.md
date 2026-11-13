# employMint

An AI copilot for internship applications that runs on your own computer, with the AI assistant you
already use (Claude Code, Codex and others). It finds US internships that fit you, writes a truthful
one-page resume and cover letter for each one, fills the application form, and then **stops before
Submit** so you read everything and submit it yourself.

Everything stays on your laptop: a SQLite database, a local Chrome profile, and PDFs on disk. No server,
no account, no upload of your resume to anyone.

## Quick start

You need macOS or Linux (on Windows, use WSL), Python 3.9+, Google Chrome, and an AI coding assistant.

```bash
./install.sh
```

Then open this folder in your assistant (for Claude Code, run `claude` here) and say:

1. **"Set me up"** and give it your resume. It reads it, asks you a few questions (work authorization,
   graduation, which roles you want), and builds your profile. Nothing it writes goes beyond what you told it.
2. **"Run today's batch"**. It finds today's best-matching postings, tailors a resume (and cover letter
   where needed) for each, and opens a review page at http://127.0.0.1:8765.
3. Click **Start applying** on the review page. Chrome opens each form already filled, with a panel showing
   the job's fit and anything you need to answer. Read it, then click Submit yourself (that's your yes) or
   **Not for me** (your no); the next one opens. There's no separate approve step. For questions only you can
   answer (pay, working in person, travel, availability), tick **Remember my answer** once and later forms
   fill them for you to check.

## Why it's built this way

Job applications are a messy, high-stakes workflow: unstructured postings, dozens of form layouts, visa
questions where one wrong click disqualifies you, and resumes where one invented number ends an interview.
employMint splits the work so each part does what it's reliable at:

| Part | Who does it | Why |
|---|---|---|
| Reading postings, drafting bullets and essays | Your AI assistant (the skills in `.claude/skills/`) | Unstructured text is what models are good at |
| Eligibility, form answers, what's allowed on a resume | Plain rules and checkers | Deterministic, testable, explainable |
| Approving jobs, consent boxes, demographics, clicking Submit | You | Accountability stays with a person |

Guardrails that are enforced in code, not just in prompts:

- **No invented facts.** Every resume bullet cites the profile facts it uses (`"sources": ["campus-it:0"]`).
  `verify.py` refuses to render a resume if a bullet contains a number or technology that isn't in its cited
  facts. Cover letters get the same check against the facts plus the job posting.
- **Never submits.** The form filler has no code path that clicks Submit. It detects the confirmation page
  after you submit and records the job as applied.
- **No bot evasion.** When a site blocks automated browsers (Lever's hCaptcha, SmartRecruiters), employMint
  hands the form to your own Chrome with a copy-paste answer sheet instead of trying to look human.
- **Visa-aware.** If you need sponsorship (`needs_sponsorship` in your preferences), postings that rule you out
  (citizenship, clearance, "will not sponsor") are filtered before any work is spent on them.
- **Your choices stay yours.** Demographic questions default to "decline to self-identify"; salary,
  relocation and consent questions are always left for you.

## Measured quality

`python3 src/evals.py` scores the output on your own applications and writes `evals/report.md`. On the
original author's applications (November 2026):

| Measure | Result |
|---|---|
| Form-answer accuracy on a hand-checked set | 100% (48/48) |
| Required questions answered automatically, on 37 real forms | 84.7% |
| Resumes where every bullet traces to a profile fact | 100% (88/88) |
| Cover letters passing the fact check | 100% (56/56) |
| Average resume page fill | 93.9% |

## How it works

```
SimplifyJobs list ─► jobs.py ─► daily batch ─► tailor (AI) ─► review page ─► apply queue ─► you submit
   (5,000+ listings)   filter,      top N         resume + cover    skip any you    fill form,
                       visa scan,                 letter, verified  don't want      stop at Submit
                       score
```

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for the components and [docs/CODE_TOUR.md](docs/CODE_TOUR.md)
for a walk through the code, following one job from listing to submitted application.
[AGENTS.md](AGENTS.md) is what your AI assistant reads.

## Supported application sites

| Site | How |
|---|---|
| Greenhouse, Ashby | Filled automatically in a local Chrome window |
| Workday | Walks the multi-step wizard after you sign in; stops at Review |
| Lever | Opens in your own Chrome (hCaptcha blocks automation) with a copy-paste answer sheet |
| SmartRecruiters, others | Answer sheet only |

## Your data

| Path | What | In git? |
|---|---|---|
| `profile/` | Your facts (`profile.json`), form answers, preferences, optional `guidance.md` | Never (ignored) |
| `resumes/<slug>/` | Each job's posting, tailored resume, cover letter, form answers | Never (ignored) |
| `data/` | Job database, saved postings, Chrome logins, logs | Never (ignored) |
| `examples/profile/` | A made-up sample applicant showing the file formats | Yes |

## Commands

Your assistant runs these for you; they're here if you want to run a step yourself.

```bash
python3 src/profile_check.py            # check your profile files
python3 src/jobs.py run                 # refresh listings, download descriptions, visa scan, score
python3 src/jobs.py batch --n 20        # pick today's jobs to tailor
python3 src/render.py resumes/<slug>/tailored.json   # verify + render a resume PDF
python3 src/cover.py resumes/<slug>/cover.json       # verify + render a cover letter
python3 src/review.py                   # review page at http://127.0.0.1:8765
python3 src/apply.py queue [--group quick|workday|manual]  # fill each waiting application; Submit is your yes
python3 src/live.py check               # check approved postings are still open; closed ones move to Closed
python3 src/evals.py [--fill]           # quality report
```

If `install.sh` set up a `.venv/`, use `.venv/bin/python` in place of `python3`.

## Optional: recruiter outreach

After you apply, employMint can find a recruiter at the company on LinkedIn and draft a short message for
you to approve. **It's off by default.** Automating LinkedIn is against LinkedIn's user agreement and can get
an account restricted, so turn it on only if you accept that risk: set `"recruiter_outreach": true` in
`profile/preferences.json`. Drafting uses the `claude` command-line tool.

## Limits

- Listings come from the [SimplifyJobs](https://github.com/SimplifyJobs) US internship lists, so postings are US-based.
- macOS and Linux only; Windows through WSL.
- Form filling needs Google Chrome itself (not Chromium).

## Development

```bash
pip install -r requirements-dev.txt
python3 -m pytest                      # shared tests, run against the sample applicant
python3 -m pytest profile/tests        # your own tests, if you keep any (profile/ is never committed)
python3 tools/snapshot.py save before  # hash every output for your profile; compare after a refactor
python3 tools/check_private.py         # look for your personal details in what you would push
ln -sf ../../tools/check_private.py .git/hooks/pre-push   # run that check before every git push
python3 tools/export_public.py         # or build a separate shareable copy with no personal data in it
```

## Stack

Python 3.9, Playwright (your installed Chrome), SQLite, headless Chrome for PDFs, and any AI coding
assistant for the writing steps. Built with AI-assisted development.

## License

[MIT](LICENSE): use it, change it, share it; keep the copyright notice.

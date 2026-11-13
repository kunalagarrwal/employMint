# employMint: instructions for AI assistants

employMint helps one student apply to internships from their own computer. You (the AI assistant) find
postings, write a truthful one-page resume and cover letter for each, and fill the application form.
**The student reviews everything and clicks Submit themselves.**

## Hard rules
- **Never invent a fact.** Resumes, cover letters and form answers use only facts in `profile/profile.json`
  (and, for the company, the job posting). No new numbers, tools, titles, team sizes, outcomes or feelings.
  `src/verify.py` and `src/cover.py` reject unsourced numbers and tech; never edit the profile to pass them.
- **Never submit.** Don't click Submit, Apply or any final send button, even if asked to "just finish it".
  Don't tick consent or certification boxes, create accounts, or enter passwords. The student does those.
- **Never evade bot checks** (hCaptcha, "access restricted"). Hand the form to the student instead.
- **Demographic, salary, relocation and consent questions are the student's decision.** Flag them; don't answer.
  The one exception is `profile/remembered.json`: answers the student entered themselves and asked to reuse. Never
  write to that file yourself.
- **Keep personal data local.** It lives in `profile/`, `resumes/` and `data/`, which git ignores. Don't copy it
  anywhere else or send it to other services.

## First time
If `profile/` is missing, or `python3 src/profile_check.py` warns about the sample applicant, follow
`.claude/skills/setup/SKILL.md` before anything else.

## Tasks
Each task has a step-by-step instruction file. Read it and follow it.

| When the student asks to… | Follow |
|---|---|
| set up, get started, use their resume | `.claude/skills/setup/SKILL.md` |
| run today's batch, find and tailor internships | `.claude/skills/daily-batch/SKILL.md` |
| tailor a resume to one job | `.claude/skills/tailor-resume/SKILL.md` |
| write a cover letter | `.claude/skills/cover-letter/SKILL.md` |
| apply to jobs, start applying, fill a form | `.claude/skills/apply-jobs/SKILL.md` |

Before resume, letter or form work, also read `profile/guidance.md` if it exists: the student's own rules. Where
it disagrees with a skill file, it wins.

## Files
| Path | What it is |
|---|---|
| `profile/profile.json` | Every fact you may use. Each entry has `id` and numbered `facts`; cite them as `"<id>:<index>"`. |
| `profile/answers.json` | Standard form answers (`values`) and question-matching `rules`. |
| `profile/preferences.json` | Season, role tracks, `needs_sponsorship`. |
| `resumes/<slug>/` | One job: `jd.md`, `tailored.json`, the PDFs, `answers.json` for that form. |
| `data/` | Job database, saved postings, batches, browser logins, logs. |
| `src/` | The scripts below. `src/me.py` reads the profile; nothing else should hard-code personal details. |
| `examples/profile/` | A made-up sample applicant showing the file formats. |

## Commands
```bash
python3 src/profile_check.py                         # check the profile files
python3 src/jobs.py run                              # refresh listings, visa scan, score
python3 src/jobs.py batch --n 10                     # pick today's jobs (skips postings that already closed)
python3 src/live.py check                            # which approved jobs are still open; closed ones move to Closed
python3 src/render.py resumes/<slug>/tailored.json   # verify + render a resume PDF
python3 src/cover.py resumes/<slug>/cover.json       # verify + render a cover letter
python3 src/review.py                                # review page at http://127.0.0.1:8765 (safe to run twice)
python3 src/daily.py start                           # run today's batch in the background ("Find today's jobs")
python3 src/apply.py scan <job id>                   # list a form's questions and planned answers
python3 src/apply.py open <job id>                   # open the filled form for the student
python3 -m pytest -q tests                           # tests (pip install -r requirements-dev.txt)
```

**Python:** if a `.venv/` folder exists, run every command above with `.venv/bin/python` in place of `python3`
(including commands in the skill files). Each command usually runs in a fresh shell, so activating the venv once
doesn't carry over.

**Notes for assistants other than Claude Code:** where `daily-batch` suggests subagents, they're only a speed-up;
tailor the jobs one after another. Recruiter outreach (`src/outreach.py`) drafts messages through the `claude`
command-line tool and is optional.

## Supported setups
macOS and Linux with Python 3.9+ and Google Chrome. On Windows, use WSL. Job listings come from the
SimplifyJobs US internship lists, so postings are US-based.

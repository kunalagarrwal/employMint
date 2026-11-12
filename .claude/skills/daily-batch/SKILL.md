---
name: daily-batch
description: Run the applicant's daily internship batch - refresh job listings, pick today's top matches, tailor a resume for each, and open the local review page so they can approve or skip. Use when asked to run today's batch, do the daily review, find and tailor today's internships, or similar.
---

# Daily internship batch

This prepares applications for review. **It never submits anything.** Applying is a separate step that only touches jobs the applicant approved.

## Steps

1. **Refresh listings** (new postings appear daily; this takes a few minutes):
   `python3 src/jobs.py run`
   It downloads the season set in `profile/preferences.json`. If it fails on the network, continue with the existing database and say so.

2. **Pick the batch:** `python3 src/jobs.py batch --n 10` (use another number if the applicant asked for one).
   - This picks at most one job per company and the best job of each track first.
   - It skips companies at their application limit and writes `data/batches/<today>.json`.
   - If today's batch already exists, keep working through it. Don't make a new one unless the applicant asks (`--force` adds more).

3. **Tailor each job** in the batch file that isn't tailored yet, plus any job still `queued` from an earlier batch (`sqlite3 data/jobs.sqlite "select id, company, title from jobs where app_status='queued'"`; take its `jd_path` and `slug` from that day's batch file). Hand-picked lists (queued with `jobs.py batch --ids`) come first. Follow the `tailor-resume` skill:
   - Use the entry's `jd_path` and `slug`, and write to `resumes/<slug>/`.
   - Do the eligibility check first. If the posting rules the applicant out (visa, when `needs_sponsorship` is true, or graduation date), run `python3 src/jobs.py mark <id> skip` and move on.
   - If fit is clearly 4 or below (e.g. needs 2+ years of experience or a language they haven't used), mark it `skip` with no resume and list it in the report. Don't spend effort on long shots.
   - Include the `review` block (fit, why, emphasized, gaps).
   - After rendering: `python3 src/jobs.py tailored <id> resumes/<slug>`.
   - The fact rules from `tailor-resume` apply in full. Never add a fact to make a resume fit.
   - To go faster, tailor several jobs in parallel with subagents. Give each one its batch entry and tell it to follow `.claude/skills/tailor-resume/SKILL.md` and read `profile/guidance.md`.
   - Then prepare the form, following `.claude/skills/apply-jobs/SKILL.md` steps 1–2: `python3 src/apply.py scan <id>`, and draft `resumes/<slug>/answers.json` for any questions marked NEEDS ANSWER or job-specific.
   - If the form has a cover letter field, or the job is on a manual site (Workday, SmartRecruiters), write a cover letter following `.claude/skills/cover-letter/SKILL.md`. It uploads automatically.

4. **Open the review page:** start `python3 src/review.py` in the background. It serves http://127.0.0.1:8765/ on this computer only and opens it in the browser.

5. **Report to the applicant:**
   - How many jobs were tailored
   - A short table: company, role, fit, top gap
   - What was skipped and why
   - Any company close to its application limit

   Then tell them to approve or skip on the review page. Approved jobs get an "Open application" button there (see the `apply-jobs` skill).

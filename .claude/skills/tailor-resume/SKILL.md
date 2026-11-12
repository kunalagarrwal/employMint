---
name: tailor-resume
description: Build a one-page resume for the applicant tailored to one specific job posting, using only facts from profile/profile.json and Google's XYZ bullet formula. Use when given a job URL or job description and asked to tailor, write, or generate a resume for it.
---

# Tailor a resume to one job

You write a resume for **one** job from the applicant's master profile. You may reword, select, reorder and emphasize. You may **never** add a fact, number, tool, title, team size, or outcome that isn't in `profile/profile.json`. A recruiter will interview them on every line.

## Files
- `profile/profile.json`: the only source of facts. Entries have `id`, `facts[]` (0-indexed), `skills[]`.
- `profile/preferences.json`: tracks, season, and whether they need visa sponsorship.
- `profile/guidance.md` (if it exists): **read it first.** It holds this person's own rules: which entries lead, which projects suit which roles, what never to claim. Where it disagrees with this skill, it wins.
- Output folder: `resumes/<company>-<role>/` (lowercase, hyphens, e.g. `resumes/stripe-swe-intern/`).

## Steps

1. **Get the job.**
   - From a daily batch: the description is already saved at the batch entry's `jd_path`. Read it, use the entry's `slug`, and copy the file to `resumes/<slug>/jd.md`.
   - Otherwise, fetch the URL or take the pasted text, and save the full description to `resumes/<slug>/jd.md` with company, title, location and URL at the top.

2. **Check eligibility first.** If `preferences.json` has `needs_sponsorship: true` and the posting requires US citizenship, a security clearance, or says it will never sponsor now or in the future, stop and tell them. Don't build the resume. Also stop if the posting's graduation-date requirement clearly excludes their `education[0].graduation`.

3. **Read the job.** List the must-have skills, the nice-to-haves, the main verbs and nouns it repeats, and which track from `preferences.json` it fits.

4. **Pick entries.**
   - Show 3–5 experience entries and 1–2 projects, most relevant first. Follow `guidance.md` on which entries lead or come last.
   - Use 2–4 bullets per entry: 3–4 for the most relevant, 1–2 for the rest.

5. **Write bullets with Google's XYZ formula.**
   - The formula: **Accomplished [X] as measured by [Y], by doing [Z].**
   - Typical shape: `<Strong verb> <X: what was achieved> <Y: real number> by <Z: how>`.
   - Example shape: "Cut page load time from 4s to under 1s by caching API responses." (Use `guidance.md`'s examples when it has them.)
   - **Y must come from the cited facts.** If no cited fact has a number, use a real scope figure from the same entry if there is one (screens built, tests written). Otherwise write X-by-Z with no number. Never estimate, round up or invent a metric. Words like "improved" or "faster" with no source are also inventions.
   - Mirror the job's wording only where the facts support it. Never claim tools they haven't used.
   - Start with a strong verb (Built, Shipped, Launched, Found, Designed, Rebuilt, Documented). Avoid cliché words such as spearheaded, leveraged, utilized and passionate.
   - **One line per bullet: 100 characters or fewer.** A bullet that wraps onto a second line with one or two words looks sloppy. The renderer flags these, so rewrite any it reports.
   - Don't imply what isn't stated: team size, leadership, launch status, users. Check the entry's facts and `_source`/`_note` fields, and `guidance.md`.
   - Every bullet gets `"sources": ["<id>:<fact index>", ...]`, listing every fact it draws on.

6. **Skills.**
   - Use 3–4 rows (e.g. Languages, Frameworks & Tools, AI, Design).
   - Use only items found in the profile's skills lists or entry `skills`, spelled the same way.
   - Put job-relevant items first. Leave out irrelevant ones.
   - Add `"certifications": [...]` only with names from `profile.certifications`, and only where they fit the role.
   - An **Interests** line prints automatically under Skills from `profile.interests_on_resume`. It gives recruiters something human to ask about. Only override it with `"interests": [...]` using items from `profile.interests`, or `[]` to hide it if the page overflows.

7. **Coursework.**
   - Pick 4–6 of the most relevant courses from `completed` or any `in_progress_*` group. Write them exactly as stored; the course code is stripped automatically.
   - Next term's courses (the coursework key named like `spring_2027`) go only in `upcoming_coursework`, and only when clearly relevant. Skip any marked "not yet enrolled".

8. **Write `resumes/<slug>/tailored.json`:**
```json
{
  "job": {"company": "...", "title": "...", "url": "...", "track": "<track from preferences.json>"},
  "section_order": ["education", "experience", "projects", "skills"],
  "show_gpa": true,
  "coursework": ["Data Structures & Algorithms (CS 210)"],
  "upcoming_coursework": [],
  "experience": [
    {"id": "<entry id>", "bullets": [
      {"text": "Built ... used by 3 campus offices", "sources": ["<entry id>:0"]}
    ]}
  ],
  "projects": [{"id": "<project id>", "bullets": [{"text": "...", "sources": ["<project id>:0"]}]}],
  "skills": [{"label": "Languages", "items": ["Python", "TypeScript"]}],
  "review": {
    "fit": 7,
    "why": "One sentence: why this is or isn't a good match.",
    "emphasized": ["what you led with"],
    "gaps": ["Requirements in the posting they don't meet, stated plainly"]
  }
}
```
The `review` block is shown on the daily review page.
- **Fit** is out of 10: 8+ strong, 6–7 reasonable, 5 or less a long shot.
- Be honest about gaps (a required language they lack, a grad-year mismatch, years of experience). They help the applicant decide; they never go on the resume.

9. **Render:** `python3 src/render.py resumes/<slug>/tailored.json`.
   - It verifies first. On errors, fix the **bullet** (reword it or cite the right fact). Never edit `profile.json` to make a check pass.
   - If the result is longer than one page, cut the weakest bullets, then drop the least relevant entry.
   - **Fill the page: aim for 90–100% full.** The renderer prints how full the page is. If it's under 90%, add more **true** material, in this order:
     1. More bullets from facts already in the profile.
     2. Another relevant entry (`guidance.md` may say which projects suit which roles). Respect each entry's `_source` notes.
     3. One more relevant course.
   - Never pad with vague filler ("strong communicator", "passionate about…"), and never repeat the same fact in two bullets.
   - Experience prints newest-first automatically. Projects print in the order you give them, most relevant first.

10. **Self-review before reporting.** Re-read each bullet next to its cited facts and ask: would the applicant be comfortable defending every word in an interview? The script can't catch implied claims (team size, ownership, launch status, impact), so fix those yourself.

11. **For a batch job,** record it: `python3 src/jobs.py tailored <job id> resumes/<slug>`.

12. **Report to the applicant:**
    - The PDF path
    - A one-line fit score out of 10, with the reason
    - Which entries and keywords you emphasized
    - **Gaps**: requirements in the job they don't meet. Name them; never paper over them.

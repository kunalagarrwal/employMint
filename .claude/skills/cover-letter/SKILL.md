---
name: cover-letter
description: Write a one-page cover letter for the applicant tailored to one job, using only facts from profile/profile.json and the job posting, then render it to PDF. Use when asked for a cover letter, or when a job's form has a cover letter field or is a manual site (Workday, SmartRecruiters) that accepts one.
---

# Cover letter for one job

`src/cover.py` renders `resumes/<slug>/cover.json` into `<First>_<Last>_Cover_Letter.pdf` (from the profile's name) and `cover.txt` for paste-in boxes.
`src/apply.py` uploads the PDF automatically wherever a form has a cover letter field.
It refuses to render if a paragraph has a number or tech term that isn't in the facts it cites, the profile's skills, or the posting.

**Read `profile/guidance.md` first if it exists.** It holds this person's writing style, true opening moments, and which stories prove what. Where it disagrees with this skill, it wins.

## When to write one
- The form has a cover letter field, required or optional. Check `resumes/<slug>/questions.json` from `apply.py scan`.
- The job is on a manual site (Workday, SmartRecruiters, company site), where an attachment is usually possible.
- Skip forms with no cover letter field.

## Before writing
1. Read the posting (`data/jd/<id>.md`): what the team builds, the 2–3 things they ask for most, location, and any eligibility rules.
2. **Re-check eligibility.** If `preferences.json` has `needs_sponsorship: true` and the posting excludes people who "now or in the future require sponsorship", stop. Mark the job skip with a note: `python3 src/jobs.py mark <id> skip --note "..."`.
3. Pick their 2–3 strongest true proofs for what the posting asks, using fact indices from `profile/profile.json`.

## Make it interesting to read
- **Open with a real moment from their work, not with them.** The first sentence should make a recruiter want the second. Use an opening from `guidance.md` if it has some; otherwise find one in the profile's facts (a surprising number, a hard constraint, a bug that mattered).
- Then connect that moment to the problem the company is solving, in one or two sentences.
- Keep sentences short and concrete, mixed with a few longer ones. Prefer specific nouns (pages, defects, screens) over adjectives.
- Interests from the profile can add personality where they fit, at most once.
- The "who I am" line (degree, minor, school, graduation from `profile.json`) goes in the closing paragraph, not the opening.

## Shape (220–380 words, 4 paragraphs)
1. **Hook:** a real moment (see above), then why it connects to their work, taken from the posting (product, team, problem).
2. **Main proof:** the most relevant story, with real numbers from cited facts.
3. **Second proof:** a different strength the posting asks for.
4. **Close:** what they'd help with, tied to the company's mission or location from the posting. Keep it short.

## Rules
- Every paragraph has `"sources": ["entry:index", ...]` for each fact it uses. A hook or close that uses no profile facts can have `[]`.
- Facts about the company come only from the posting. Never invent feelings, stories, product usage or contacts ("I've used Notion every day…") unless the profile says so.
- Use past tense for roles that have ended (check `end` in the profile). Respect launch status and team size exactly as the facts state them.
- When the role connects to their classes, follow `guidance.md`'s writing style if it has one. Completed courses are "I took", `in_progress_*` courses are "I'm taking … this term", and next term's courses are never described as taken.
- State a gap honestly when it helps ("I haven't used Spring Boot yet, but…"). Never claim a tool they haven't used.
- Don't mention the visa. The forms handle that.
- No stock phrases ("I am writing to express", "passionate", "team player", "perfect fit"). The checker warns on these.

## cover.json
```json
{"job": {"id": "<job id>", "company": "...", "title": "..."},
 "greeting": "Dear <Company> <Team> Team,",
 "paragraphs": [{"text": "...", "sources": ["<entry id>:0", "<entry id>:2"]}],
 "closing": "Sincerely,"}
```

## Render and check
`python3 src/cover.py resumes/<slug>/cover.json`. Fix any ERROR by rewording or citing the right fact; never edit the profile to pass. Then read the PDF once as a recruiter would: is it specific to this company, and could the applicant defend every sentence?

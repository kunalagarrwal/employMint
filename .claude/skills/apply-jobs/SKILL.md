---
name: apply-jobs
description: Prepare and open job applications for the applicant - scan an application form, draft job-specific answers from their profile, and open Chrome with the form filled so they can review and click Submit themselves. Use when asked to apply to jobs, start the apply queue, prepare application answers, or fill an application form.
---

# Apply to jobs

`src/apply.py` fills application forms from `profile/answers.json` (standard answers) and
`resumes/<slug>/answers.json` (answers for one job). **It never clicks Submit, and neither do you.**
The applicant reads the filled form and submits it themselves. When the confirmation page appears, the job is marked `applied`.

**Read `profile/guidance.md` first if it exists.** It holds this person's own writing style and form quirks.

Auto-fill works on Greenhouse and Ashby. **Lever** guards Submit with an invisible hCaptcha that rejects script-controlled browsers ("Something went wrong, try again"), so Lever jobs open in the applicant's own Chrome and the tool's window shows an answer sheet (every question resolved, Copy buttons, Show resume in Finder). They click **I submitted it** there. Never try to hide automation from hCaptcha.
On **Workday** it clicks Apply, then Autofill with Resume, and fills the applicant's email on the sign-in page. The applicant signs in or creates the account themselves (one per company; never enter passwords). Then it uploads the resume, fills each step, clicks "Save and Continue" (which saves a draft), and stops at Review for the applicant to Submit.
On other company sites it clicks a plain "Apply" button first, fills what it can, and shows copy-paste answers in the panel. SmartRecruiters blocks automated browsers ("Access is temporarily restricted"); never try to get around that.

## Steps

1. **Scan the form** (headless, nothing is filled or sent):
   `python3 src/apply.py scan <job id>`
   It saves `resumes/<slug>/questions.json` and shows how each question will be answered:
   - `profile`: answered by a rule in `profile/answers.json`
   - `profile (check)`: answered with a default the applicant may want to change (demographics → decline)
   - `you: …`: deliberately left for the applicant (relocation, salary, consent boxes, citizenship, class standing)
   - `NEEDS ANSWER` / `optional, left blank`: no answer yet

2. **Draft job-specific answers** in `resumes/<slug>/answers.json`:
   ```json
   {"answers": [
     {"q": "<exact question label from questions.json>", "a": "text to type", "note": "what the applicant should check"},
     {"q": "<label>", "pick": ["^2$"], "note": "..."},
     {"q": "<label>", "flag": "Why the applicant must answer this themselves"}
   ]}
   ```
   - `a` = text for text boxes; `pick` = option patterns (regex, lowercase) for dropdowns, radios and checkboxes; `flag` = don't fill it, highlight it for the applicant.
   - Use the question label exactly as `questions.json` has it.
   - **Essays ("Why X?", "Tell us about…") use only facts in `profile/profile.json`.** Same rules as resumes: no invented numbers, tools, outcomes or feelings. Don't claim they use the company's product unless the profile says so. Keep it to 3–5 sentences and add a `note` asking them to make it personal.
   - Follow `guidance.md`'s writing style for "why us" / "tell us about yourself" answers if it has one. Use exact course names from `profile.json`: completed courses are "I took", `in_progress_*` courses are "I'm taking … this term", and next term's courses are never described as taken.
   - Self-ratings (e.g. "rate your Swift 1–10"), relocation, in-office days, pay, visa plans after graduation, demographics and consent: always `flag`. Those are their decisions.
   - Factual questions the profile answers (number of internships, graduation date, major) can be filled, with a `note` saying where the answer came from.
   - Re-run `scan` to confirm every required question now resolves.

3. **Check the fill without opening a window** (optional, good for a new kind of form):
   `python3 src/apply.py try <job id>`
   It fills the form in a hidden browser, prints what happened to each field, saves a screenshot to `data/apply-logs/<company>-try.png`, then throws it all away.
   Look at the screenshot. Dropdowns can pick a wrong but similar option (e.g. the wrong campus of their school). If one does, tighten the pattern in `profile/answers.json` (the rule's `a` and `search`).

4. **Open it for the applicant:** they click **Start applying** (the whole queue) or **Apply now** / **Open** (one job) on the review page (http://127.0.0.1:8765/), or run
   `python3 src/apply.py open <job id>`.
   Chrome opens with the form filled and a panel listing what to check. The outlines mean:
   - green: filled from the profile
   - blue: drafted for this job
   - amber: check it
   - red: they must answer

   The job must be `tailored` or `approved`: there's no separate approve step, because reading the filled form *is* the
   review. Submitting marks it `applied`; **Not for me** moves it to Skipped; **Later** leaves it for the next run.
   The panel's top shows the job's fit, why and gaps from `tailored.json`. Logins are kept in `data/browser-profile/` on this computer.

   **Remember my answer.** On red questions that are the applicant's own call and recur (pay, working in person,
   relocation, travel, availability, other offers, non-competes, class standing, high school, country of birth), the panel
   shows a "Remember my answer" box. If they tick it and submit, *their* answer is saved to `profile/remembered.json`
   and fills the same kind of question on later forms, amber, for them to check (`scan` shows it as `remembered (check)`).
   Consent, certification, demographic and company-specific questions are never remembered. Never write to
   `remembered.json` yourself: only the applicant's own entries go there.

5. **Report**: per job, what was filled, and what the applicant needs to answer themselves before submitting.

## Never
- Click Submit, Apply, or any final send button, even if asked to "just finish it". The applicant submits.
- Tick consent, certification or terms boxes for them.
- Create accounts (Workday etc.) or enter passwords. They do that in the opened window.
- Put anything in an answer that isn't in their profile.

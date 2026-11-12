---
name: setup
description: Set up employMint for a new applicant - read their resume, draft profile/profile.json, answers.json and preferences.json from it plus a short interview, then check the files and render a test resume. Use when someone is new, there is no profile/ folder, profile_check reports the sample applicant, or they ask to set up, onboard, or start fresh.
---

# Set up a new applicant

You turn one person's resume and a few answers into the three files everything else reads:
`profile/profile.json` (facts), `profile/answers.json` (form answers) and `profile/preferences.json` (what they want).
`profile/` is ignored by git, so nothing personal is ever committed.

**The one rule that matters:** every fact in `profile.json` comes from their resume or from what they tell you. Never invent, round up or "improve" a number, tool, title, date or outcome. Resumes and cover letters are later checked against these facts, so a made-up fact here becomes a made-up claim on every application.

## Steps

1. **Check what's there.** Run `python3 src/profile_check.py`.
   - `profile/` missing: copy the sample as a starting structure with `cp -R examples/profile profile`.
   - It warns about the sample applicant (Alex Rivera): continue and replace it.
   - It reports a real profile (no sample warning): ask before changing anything. If they want a fresh start, back it up first with `cp -R profile data/profile-backup-$(date +%Y%m%d)`.

2. **Get their resume.** Ask for the file path (PDF, DOCX or text) or pasted text, and read it in full. Save a copy as `profile/source-resume.pdf` (or `.txt`) and set `"source"` in `profile.json` to that path.

3. **Draft `profile.json`** from the resume, keeping the sample's structure (see `examples/profile/README.md`):
   - `contact`: name, email, phone, linkedin, github, all as text. Use `""` for anything they don't have; it's left off the resume.
   - `education[0]`: school, college, location, degree (e.g. "B.S. Computer Science"), minor (leave it out if none), graduation like "May 2028", gpa like "3.60/4.0" (leave it out if they don't want it shown), honors, start as YYYY-MM.
   - `coursework`: `completed` is an object of subject → list of courses (`{"cs": [...], "math": [...]}`). This term's courses go under `in_progress_<term>_<year>` (e.g. `in_progress_fall_2026`), next term's under `<term>_<year>` (e.g. `spring_2027`). Keys are **lowercase**. Use exact course names and codes.
   - `experience` and `projects`: one entry each, with an `id` slug (lowercase, hyphens, unique), dates as YYYY-MM (`end` can be `"present"`, lowercase), and `facts`: **one true claim per sentence**, with numbers copied exactly. Split a resume bullet that makes three claims into three facts. Add `skills` (a list) the entry actually used. A project `name` can be "Name - short subtitle"; the part after " - " prints under the name.
   - Use `_source` or `_note` on an entry for limits the person mentions ("prototype only", "team of 4", "not launched yet"). The skills read these before writing.
   - `skills`, `interests`, `interests_on_resume`, `certifications` (name, issuer, file if they have one).
   - Add things they mention in the interview that aren't on the resume (more projects, real numbers), but only what they state.

4. **Ask a short interview** in one or two messages, not one question at a time:
   - **Work authorization:** US citizen, permanent resident, or a visa (which one)? Will they need sponsorship now or later? (For F-1 students: CPT for internships, OPT after.)
   - **Graduation** month and year, if the resume doesn't say. **GPA:** show it or not?
   - **Season** they're applying for (e.g. "Summer 2027") and which **roles** they want most.
   - **Location** for forms: city and state. A street address is optional and only used if they want forms filled with it.
   - **Demographic questions** (gender, race, veteran, disability, orientation): the default is "decline to self-identify". Change it only if they choose to answer.
   - **Pronouns** (optional) and how they usually hear about jobs.
   - Anything they want resumes to lead with or avoid.

5. **Write `work_authorization`** in `profile.json`:
   - `status`, e.g. "US citizen" or "F-1 student visa".
   - `requires_future_sponsorship`.
   - `future_visa` (only if they have one, e.g. "OPT").
   - `form_answers.authorized_to_work_in_us` and `form_answers.will_require_sponsorship`, in the exact words they want typed into forms.

6. **Write `answers.json`.** Keep the sample's rules, which cover common form questions. Update:
   - **`values`:** every key, as text, from their profile. The code needs at least `full_name` (must equal `contact.name`), `email`, `phone`, `linkedin`, `school`, `degree` (e.g. "Bachelor of Science"), `major`, `gpa` (`""` if they'd rather not), `grad` ("May 2028"), `grad_year` ("2028") and `heard_from`.
   - **Rules with personal answers:**
     - citizenship / nationality
     - sponsorship, visa type, CPT, OPT, "legally authorized"
     - current company (their current role, or delete the rule)
     - pronouns
     - demographics (per their choice)
   - **Rules with patterns for the sample:**
     - school (`a` and `search`, matching how forms list their school)
     - city and state, and the street-address rule's text
     - education start year
     - graduation year and month
     - the availability rule (`summer 2027` in `q`, `a` and `text`: change it to their season)
   - A question nobody should answer automatically gets a `flag` instead of an answer.

7. **Write `preferences.json`:**
   - `season`, like "Summer 2027".
   - `needs_sponsorship`, the same value as `requires_future_sponsorship`.
   - `tracks` priorities: each track keeps a whole-number `priority`, 1 = most wanted. Keep the track names already in the file; the job filter knows those.
   - `exclude`.
   - Optional `workday_experience`: the experience ids to enter on Workday forms, in order. Without it, the 3 most recent are used.

8. **Optional `profile/guidance.md`:** personal rules for the other skills, such as which entry usually leads, a writing style, or things never to claim. Write only what they told you. Skip the file if they had nothing to add.

9. **Check:** run `python3 src/profile_check.py` and fix every ERROR. Read each WARN and fix it or tell them why it's fine. The sample-applicant warning must be gone.

10. **Test render:** write `data/setup-check/tailored.json` with 2–3 real bullets citing their facts (same format as the `tailor-resume` skill), then run `python3 src/render.py data/setup-check/tailored.json`. This proves Chrome and the fact checker work on their profile. Show them the PDF path.

11. **Report:**
    - What you filled in and from where (resume or interview).
    - What is still empty or guessed-at (`gaps_to_fill` in `profile.json`).
    - The next step: run the `daily-batch` skill to find and tailor today's internships.

## Never
- Invent or embellish a fact, or copy anything from the sample applicant into their profile.
- Answer demographic, consent or salary questions for them without asking.
- Ask for passwords, or put the profile anywhere outside `profile/`.

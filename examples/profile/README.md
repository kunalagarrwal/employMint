# Sample profile

A made-up applicant, Alex Rivera (US citizen, graduating May 2028), so you can see what employMint
needs before adding your own details.

| File | What it holds |
|---|---|
| `profile.json` | Every fact a resume or cover letter may use. Each bullet must trace back to a fact here. |
| `answers.json` | Standard form answers (`values`) and rules that match form questions to answers. |
| `preferences.json` | Internship season, which roles you want, and whether you need visa sponsorship. |

To try it, copy the folder to `profile/` at the project root:

```bash
cp -R examples/profile profile
```

Your real `profile/` folder is ignored by git, so your details never get committed.

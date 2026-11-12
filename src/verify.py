"""Checks a tailored resume against the master profile.

Every bullet must cite profile facts ("id:index"). Numbers and tech terms in a
bullet must come from the facts it cites. Skills and coursework must exist in
the profile. Errors block rendering; warnings are shown but don't block.

Usage: python3 src/verify.py resumes/<slug>/tailored.json
"""
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import me  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
PROFILE_PATH = me.PROFILE_PATH

# Tech terms a bullet might claim. If one appears in a bullet, it must also
# appear in the facts or skills of the entry it cites.
TECH_TERMS = [
    "python", "java", "javascript", "typescript", "c\\+\\+", "c#", "go", "golang", "rust", "kotlin", "swift",
    "ruby", "php", "scala", "sql", "matlab", "html", "css",
    "react", "react native", "next\\.js", "vue", "angular", "node\\.js", "express", "django", "flask",
    "fastapi", "spring boot", "rails", "expo", "flutter", "swiftui",
    "aws", "gcp", "azure", "docker", "kubernetes", "terraform", "firebase", "supabase", "postgres",
    "postgresql", "mysql", "mongodb", "redis", "graphql", "kafka", "spark", "hadoop", "airflow",
    "tensorflow", "pytorch", "scikit-learn", "pandas", "numpy", "langchain", "llm", "llms", "openai",
    "rag", "ocr", "tesseract", "nlp", "computer vision", "machine learning", "deep learning",
    "selenium", "appium", "cypress", "jest", "playwright", "ci/cd", "sentry", "revenuecat",
    "figma", "tableau", "power bi", "excel", "jira", "linux", "edge functions",
]

AI_CLICHES = [
    "spearheaded", "leveraged", "leveraging", "synergy", "synergies", "passionate", "results-driven",
    "cutting-edge", "seamlessly", "robust", "dynamic", "utilized", "orchestrated", "pivotal", "fostered",
]

MAX_BULLET_CHARS = 170


def norm(s):
    return re.sub(r"\s+", " ", s.lower()).strip()


def course_name(c):
    """'Data Structures & Algorithms (CMPSC 465)' -> 'data structures & algorithms'"""
    return norm(re.sub(r"\s*\(.*?\)\s*$", "", c))


def numbers_in(text):
    """Numbers as written, normalized: '14,500+' -> '14500', '$18.8M' -> '18.8'."""
    return {m.replace(",", "") for m in re.findall(r"\d[\d,]*(?:\.\d+)?", text)}


def terms_in(text):
    t = norm(text)
    found = set()
    for term in TECH_TERMS:
        if re.search(r"(?<![\w+#.])" + term + r"(?![\w+#])", t):
            found.add(term.replace("\\", ""))
    return found


def profile_entries(profile):
    entries = {}
    for e in profile.get("experience", []):
        entries[e["id"]] = ("experience", e)
    for p in profile.get("projects", []):
        entries[p["id"]] = ("projects", p)
    return entries


def all_profile_skills(profile):
    skills = set()
    for v in profile.get("skills", {}).values():
        if isinstance(v, list):
            skills.update(norm(s) for s in v)
    for _, e in profile_entries(profile).values():
        skills.update(norm(s) for s in e.get("skills", []))
    return skills


def allowed_courses(profile):
    cw = profile["education"][0].get("coursework", {})
    current, upcoming = set(), set()
    for group in cw.get("completed", {}).values():
        current.update(course_name(c) for c in group)
    current.update(course_name(c) for c in me.in_progress_courses(cw))
    for c in cw.get(me.upcoming_term(cw)[0], []):
        if "not yet enrolled" not in c.lower():
            upcoming.add(course_name(c))
    return current, upcoming


def verify(tailored, profile):
    errors, warnings = [], []
    entries = profile_entries(profile)
    seen = set()

    for section in ("experience", "projects"):
        for item in tailored.get(section, []):
            eid = item.get("id")
            if eid not in entries:
                errors.append(f"{section}: unknown id '{eid}' (not in profile)")
                continue
            if entries[eid][0] != section:
                errors.append(f"'{eid}' belongs in {entries[eid][0]}, not {section}")
            if eid in seen:
                errors.append(f"'{eid}' appears twice")
            seen.add(eid)
            entry = entries[eid][1]
            if entry.get("priority") == "low":
                warnings.append(f"'{eid}' is low priority; keep it only if there's spare room")

            bullets = item.get("bullets", [])
            if not bullets:
                errors.append(f"'{eid}' has no bullets")
            for b in bullets:
                text, sources = b.get("text", ""), b.get("sources", [])
                label = f"[{eid}] \"{text[:60]}...\""
                if not sources:
                    errors.append(f"{label} cites no sources")
                    continue
                cited = []
                for ref in sources:
                    sid, _, idx = ref.partition(":")
                    if sid not in entries or not idx.isdigit():
                        errors.append(f"{label} bad source '{ref}'")
                        continue
                    facts = entries[sid][1].get("facts", [])
                    if int(idx) >= len(facts):
                        errors.append(f"{label} source '{ref}' out of range")
                        continue
                    cited.append(facts[int(idx)])
                    if sid != eid:
                        warnings.append(f"{label} cites another entry ('{ref}')")
                if not cited:
                    continue
                source_text = " ".join(cited)
                source_vocab = source_text + " " + " ".join(entry.get("skills", []))

                extra_nums = numbers_in(text) - numbers_in(source_text)
                if extra_nums:
                    errors.append(f"{label} has numbers not in its sources: {sorted(extra_nums)}")
                extra_terms = terms_in(text) - terms_in(source_vocab)
                if extra_terms:
                    errors.append(f"{label} mentions tech not in its sources: {sorted(extra_terms)}")
                if len(text) > MAX_BULLET_CHARS:
                    warnings.append(f"{label} is {len(text)} chars (aim for <= {MAX_BULLET_CHARS})")
                for w in AI_CLICHES:
                    if re.search(r"\b" + w + r"\b", text.lower()):
                        warnings.append(f"{label} uses cliche word '{w}'")

    known_skills = all_profile_skills(profile)
    for group in tailored.get("skills", []):
        for s in group.get("items", []):
            if norm(s) not in known_skills:
                errors.append(f"skills: '{s}' is not in the profile")

    known_interests = {norm(s) for s in profile.get("interests", [])}
    for s in tailored.get("interests", profile.get("interests_on_resume", [])):
        if norm(s) not in known_interests:
            errors.append(f"interests: '{s}' is not in the profile's interests")

    known_certs = {c["name"] for c in profile.get("certifications", [])}
    for c in tailored.get("certifications", []):
        if c not in known_certs:
            errors.append(f"certifications: '{c}' is not in the profile")

    current, upcoming = allowed_courses(profile)
    for c in tailored.get("coursework", []):
        if course_name(c) not in current:
            errors.append(f"coursework: '{c}' is not a completed/in-progress course")
    for c in tailored.get("upcoming_coursework", []):
        if course_name(c) not in upcoming:
            errors.append(f"upcoming coursework: '{c}' is not an enrolled {me.upcoming_term(profile['education'][0].get('coursework', {}))[1]} course")

    return errors, warnings


def main():
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    tailored = json.loads(Path(sys.argv[1]).read_text())
    profile = json.loads(PROFILE_PATH.read_text())
    errors, warnings = verify(tailored, profile)
    for w in warnings:
        print("WARN ", w)
    for e in errors:
        print("ERROR", e)
    print(f"{len(errors)} errors, {len(warnings)} warnings")
    sys.exit(1 if errors else 0)


if __name__ == "__main__":
    main()

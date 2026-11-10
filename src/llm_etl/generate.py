"""Deterministic synthetic job-posting feed with ground truth.

Produces three kinds of record:
  * valid      - a realistic posting with known labels (incl. "sibling" postings:
                 same company + title, different city/stack - hard negatives for dedup)
  * duplicate  - a lightly edited repost of a valid posting (dedup ground truth)
  * invalid    - spam, truncated text, or an inverted salary range (should be quarantined)
"""

import json
import random
from datetime import date, timedelta

from llm_etl.config import GOLDEN_LABELS, GROUND_TRUTH, RAW_POSTINGS
from llm_etl.schema import TAXONOMY

SEED = 42
N_VALID, N_SIBLINGS, N_DUPLICATES = 600, 30, 60
LONGTAIL_SHARE = 0.2
GOLDEN_PER_SLICE = {"standard": 35, "longtail": 15}

CITIES = {
    "USD": ["Austin, TX", "New York, NY", "Seattle, WA", "Chicago, IL", "Denver, CO", "Boston, MA"],
    "GBP": ["London, UK", "Manchester, UK", "Edinburgh, UK"],
    "EUR": ["Berlin, Germany", "Amsterdam, Netherlands", "Dublin, Ireland", "Paris, France"],
}
CURRENCY_SCALE = {"USD": 1.0, "EUR": 0.65, "GBP": 0.55}
BASE_SALARY = {"junior": 75_000, "mid": 105_000, "senior": 140_000, "staff": 175_000, "lead": 165_000}
YEARS = {"junior": "0-2", "mid": "3+", "senior": "5+", "staff": "8+", "lead": "7+"}

ROLES = {
    "Data Engineer": (["python", "sql"], ["spark", "airflow", "dbt", "snowflake", "kafka", "aws", "azure",
                      "azure data factory", "databricks", "docker", "terraform", "postgresql", "scala",
                      "fivetran", "git", "bigquery", "redshift", "gcp"]),
    "Analytics Engineer": (["sql", "dbt"], ["snowflake", "bigquery", "looker", "tableau", "python",
                           "fivetran", "airflow", "git", "power bi", "redshift"]),
    "Machine Learning Engineer": (["python"], ["pytorch", "tensorflow", "mlflow", "docker", "kubernetes",
                                  "aws", "gcp", "spark", "sql", "llms", "databricks"]),
    "AI Engineer": (["python", "llms"], ["langchain", "pytorch", "docker", "kubernetes", "aws", "azure",
                    "postgresql", "sql", "mlflow", "git"]),
    "Data Platform Engineer": (["python"], ["kubernetes", "terraform", "kafka", "spark", "airflow", "aws",
                               "gcp", "docker", "snowflake", "databricks", "java", "scala"]),
    "BI Developer": (["sql"], ["power bi", "tableau", "looker", "azure", "snowflake", "python",
                     "azure data factory"]),
}
TITLE_FORMS = {
    "junior": ["Junior {r}", "Associate {r}", "Graduate {r}", "{r} I"],
    "mid": ["{r}", "{r}", "{r} II"],
    "senior": ["Senior {r}", "Sr. {r}", "{r} III"],
    "staff": ["Staff {r}", "Principal {r}"],
    "lead": ["Lead {r}", "{r} Team Lead"],
}
COMPANIES = [
    "Northwind Analytics", "Bluefin Health", "Copperleaf Energy", "Halcyon Retail", "Meridian Logistics",
    "Quartzline Bank", "Saltmarsh Media", "Tidewater Insurance", "Vantage Mobility", "Wrenfield Labs",
    "Aldergrove Foods", "Brightpath Learning", "Cobalt Freight", "Driftwood Travel", "Emberly Games",
    "Foxglove Pharma", "Granite Peak Capital", "Harborview Telecom", "Ironbark Security", "Juniper Grid",
    "Kestrel Robotics", "Lumen Street", "Mistral Payments", "Nimbus Weather", "Orchard Commerce",
    "Pinecrest Realty", "Quillon Legal", "Redwood Clinics", "Sablewood Studios", "Thornbury Water",
]
BLURBS = [
    "{c} builds software that thousands of businesses rely on every day.",
    "At {c}, data is at the heart of every product decision we make.",
    "{c} is a fast-growing company backed by leading investors.",
    "Join {c} and help us modernise how our industry uses data.",
    "{c} serves customers in more than 20 countries.",
]
SKILL_PHRASES = [
    "Strong {s} skills", "Experience with {s}", "Hands-on {s} in production",
    "Familiarity with {s}", "Solid working knowledge of {s}", "You have shipped projects using {s}",
]
BENEFITS = [
    "Learning budget of $2,000 per year.", "25 days holiday plus bank holidays.",
    "401(k) matching and private health insurance.", "Annual team offsite.",
    "Home office stipend of $500.", "Generous parental leave.",
]
REMOTE_LINES = {
    "remote": ["This role is fully remote, with an optional hub in {city}.",
               "Remote-first team; our nearest office is in {city}, but you can work from anywhere.",
               "100% remote (team anchored in {city})."],
    "hybrid": ["Hybrid: 2 days a week in our {city} office.",
               "We follow a hybrid working model from our {city} office.",
               "Flexible hybrid setup, 3 days on-site in {city}."],
    "onsite": ["This is an on-site role in our {city} office.",
               "Office-based in {city}, five days a week.",
               "Interviews are remote-friendly, but the role itself is on-site in {city}."],
}
SPAM = [
    "EARN $5,000 PER WEEK FROM HOME!!! No experience needed. DM us now.",
    "Make money online fast - click the link in bio. Limited spots!!!",
    "Crypto trading opportunity, guaranteed returns of 300%. Message me.",
    "We are hiring!!! Send your CV to win an iPhone. Act now.",
    "Be your own boss. Work 2 hours a day. Unlimited income potential.",
]


# "Long-tail" phrasings: written AFTER the rule-based extractor was frozen and deliberately not
# taught to it. They simulate the phrasing drift real feeds have, and are the slice the eval
# uses to show where regex rules stop generalising.
LONGTAIL_ALIASES = {"azure data factory": "Data Factory", "llms": "foundation models", "kubernetes": "Kube",
                    "power bi": "PowerBI", "pytorch": "Torch", "postgresql": "PG"}
LONGTAIL_REMOTE = {
    "remote": ["Distributed team across time zones - work wherever you're most productive ({city} hub).",
               "Remote OK - our HQ is in {city}."],
    "hybrid": ["You'll split your week between home and our {city} office.",
               "Hybrid-flexible, anchored to {city}."],
    "onsite": ["Must be able to commute to {city} daily.", "Based on-site at our {city} campus."],
}
CURRENCY_WORD = {"USD": "dollars", "EUR": "euros", "GBP": "pounds"}


def _a(word: str) -> str:
    return "an" if word[0].lower() in "aeiou" else "a"


def _salary_text(rng: random.Random, cur: str, lo: int, hi: int) -> str:
    k = lambda v: f"{v // 1000}k"
    sym = {"USD": "$", "EUR": "€", "GBP": "£"}[cur]
    if lo == hi:
        return f"Base salary: {sym}{lo:,}."
    if cur == "EUR":
        dots = lambda v: f"{v:,}".replace(",", ".")
        forms = [f"€{dots(lo)} – €{dots(hi)} per year.", f"Salary: EUR {k(lo)}-{k(hi)}.",
                 f"Compensation: {lo:,} to {hi:,} EUR annually."]
    elif cur == "GBP":
        forms = [f"£{lo:,} - £{hi:,} per annum.", f"Salary £{k(lo)} to £{k(hi)} plus bonus.",
                 f"Compensation: GBP {lo:,}-{hi:,}."]
    else:
        forms = [f"${lo:,} - ${hi:,} base salary.", f"Pay range: ${k(lo)}–${k(hi)}.",
                 f"Salary range: {lo // 1000}-{hi // 1000}K USD.", f"USD {lo:,} to {hi:,} per year."]
    return rng.choice(forms)


def _make_valid(rng: random.Random, company: str, role: str, seniority: str, title: str,
                salary_override: str | None = None, longtail: bool = False) -> tuple[str, dict]:
    cur = rng.choice(["USD", "USD", "USD", "EUR", "GBP"])
    city = rng.choice(CITIES[cur])
    core, pool = ROLES[role]
    skills = sorted(set(core) | set(rng.sample(pool, rng.randint(2, 6))))
    remote = rng.choice(["remote", "hybrid", "hybrid", "onsite"])

    roll = rng.random()
    lo = hi = None
    if roll < 0.70:
        base = BASE_SALARY[seniority] * CURRENCY_SCALE[cur] * rng.uniform(0.9, 1.15)
        lo = int(round(base / 5000) * 5000)
        hi = lo if rng.random() < 0.1 else lo + rng.choice([15_000, 20_000, 25_000, 30_000])
        salary_line = _salary_text(rng, cur, lo, hi)
        if longtail and lo != hi:
            salary_line = rng.choice([
                f"We pay between {lo // 1000} and {hi // 1000} thousand {CURRENCY_WORD[cur]} a year.",
                f"Total base: {lo // 1000}k-{hi // 1000}k ({cur}).",
            ])
    elif roll < 0.73 and cur == "USD":
        salary_line = f"Contract rate: ${rng.choice([65, 75, 85, 95])}/hour."  # not annual -> null by contract
    else:
        salary_line = rng.choice(["Competitive salary and equity.", "Salary depends on experience.", ""])

    if salary_override:
        salary_line = salary_override
    rendered = [LONGTAIL_ALIASES[s] if longtail and s in LONGTAIL_ALIASES and rng.random() < 0.7
                else rng.choice(TAXONOMY[s]) for s in skills]
    rng.shuffle(rendered)
    if rng.random() < 0.5:
        reqs = "Requirements:\n" + "\n".join(f"- {rng.choice(SKILL_PHRASES).format(s=s)}" for s in rendered)
    else:
        reqs = "Our stack: " + ", ".join(rendered[:-1]) + f" and {rendered[-1]}."
    reqs += f"\n{YEARS[seniority]} years of relevant experience."

    blurb = rng.choice(BLURBS).format(c=company)
    remote_line = rng.choice((LONGTAIL_REMOTE if longtail else REMOTE_LINES)[remote]).format(city=city)
    header = rng.choice([
        f"Role: {title} ({company})",
        f"Our platform team at {company} needs {_a(title)} {title}.",
    ] if longtail else [
        f"{title}\n{company} | {city}",
        f"Job Title: {title}\nLocation: {city}\nCompany: {company}",
        f"{company} is hiring {_a(title)} {title} to join our data team.",
        f"About the role\nWe're looking for {_a(title)} {title} who loves clean, reliable data.",
    ])
    body = [header, blurb, reqs, remote_line, salary_line, rng.choice(BENEFITS)]
    text = "\n\n".join(p for p in body if p)
    labels = {
        "title": title, "seniority": seniority, "skills": skills,
        "salary_min": lo, "salary_max": hi, "salary_currency": cur if lo else None,
        "remote_policy": remote, "location": city, "slice": "longtail" if longtail else "standard",
    }
    return text, labels


def _mutate(rng: random.Random, text: str) -> str:
    """Light edits a job board repost typically introduces."""
    lines = text.split("\n")
    ops = rng.sample(["repost", "whitespace", "deadline", "case", "drop_benefit"], rng.randint(1, 2))
    if "case" in ops:
        lines[0] = lines[0].upper()
    if "whitespace" in ops:
        lines = [ln + "  " if i % 2 else ln for i, ln in enumerate(lines)]
    if "drop_benefit" in ops and len(lines) > 3:
        lines = lines[:-1]
    if "repost" in ops:
        lines.insert(0, "[Reposted]")
    if "deadline" in ops:
        lines.append(f"Apply by {rng.randint(1, 28)} {rng.choice(['July', 'August', 'September'])}.")
    return "\n".join(lines)


def generate() -> dict[str, int]:
    rng = random.Random(SEED)
    start = date(2026, 6, 1)
    postings, truth = [], []

    def add(text: str, company: str, posted: date, kind: str, labels=None, duplicate_of=None) -> str:
        pid = f"JP-{len(postings) + 1:05d}"
        postings.append({"posting_id": pid, "source": "synthetic_board", "company": company,
                         "posted_at": posted.isoformat(), "text": text})
        truth.append({"posting_id": pid, "kind": kind, "duplicate_of": duplicate_of, "labels": labels})
        return pid

    valid = []  # (posting_id, company, role, seniority, title, posted)
    for _ in range(N_VALID):
        company, role = rng.choice(COMPANIES), rng.choice(list(ROLES))
        seniority = rng.choice(list(TITLE_FORMS))
        title = rng.choice(TITLE_FORMS[seniority]).format(r=role)
        posted = start + timedelta(days=rng.randint(0, 120))
        text, labels = _make_valid(rng, company, role, seniority, title, longtail=rng.random() < LONGTAIL_SHARE)
        valid.append((add(text, company, posted, "valid", labels), company, role, seniority, title, posted))

    for _, company, role, seniority, title, posted in rng.sample(valid, N_SIBLINGS):
        text, labels = _make_valid(rng, company, role, seniority, title, longtail=rng.random() < LONGTAIL_SHARE)
        add(text, company, posted + timedelta(days=rng.randint(0, 10)), "valid", labels)

    for pid, company, *_, posted in rng.sample(valid, N_DUPLICATES):
        original = postings[int(pid[3:]) - 1]["text"]
        add(_mutate(rng, original), company, posted + timedelta(days=rng.randint(3, 30)), "duplicate",
            duplicate_of=pid)

    for spam in SPAM:
        add(spam, "unknown", start + timedelta(days=rng.randint(0, 120)), "invalid")
    for _ in range(4):  # inverted salary range - a classic source-data typo
        company = rng.choice(COMPANIES)
        text, _ = _make_valid(rng, company, "Data Engineer", "senior", "Senior Data Engineer",
                              salary_override="Salary: $150,000 - $120,000.")
        add(text, company, start + timedelta(days=rng.randint(0, 120)), "invalid")
    for _ in range(3):  # truncated by an upstream scraper
        company = rng.choice(COMPANIES)
        role = rng.choice(list(ROLES))
        text, _ = _make_valid(rng, company, role, "mid", role)
        add(text[: rng.randint(25, 60)], company, start + timedelta(days=rng.randint(0, 120)), "invalid")

    order = sorted(range(len(postings)), key=lambda i: (postings[i]["posted_at"], postings[i]["posting_id"]))
    RAW_POSTINGS.parent.mkdir(parents=True, exist_ok=True)
    GOLDEN_LABELS.parent.mkdir(parents=True, exist_ok=True)
    _write_jsonl(RAW_POSTINGS, [postings[i] for i in order])
    _write_jsonl(GROUND_TRUTH, [truth[i] for i in order])
    golden = [t for slice_, n in GOLDEN_PER_SLICE.items()
              for t in rng.sample([t for t in truth if t["kind"] == "valid" and t["labels"]["slice"] == slice_], n)]
    _write_jsonl(GOLDEN_LABELS, sorted(({"posting_id": t["posting_id"], **t["labels"]} for t in golden),
                                       key=lambda r: r["posting_id"]))
    return {k: sum(t["kind"] == k for t in truth) for k in ("valid", "duplicate", "invalid")}


def _write_jsonl(path, rows) -> None:
    with path.open("w") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

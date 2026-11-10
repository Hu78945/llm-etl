import pytest

from llm_etl.extract_rules import extract_fields


@pytest.mark.parametrize("line, expected", [
    ("$120,000 - $150,000 base salary.", (120_000, 150_000, "USD")),
    ("Pay range: $120k–$150k.", (120_000, 150_000, "USD")),
    ("Salary range: 120-150K USD.", (120_000, 150_000, "USD")),
    ("USD 120,000 to 150,000 per year.", (120_000, 150_000, "USD")),
    ("€70.000 – €85.000 per year.", (70_000, 85_000, "EUR")),
    ("Compensation: 70,000 to 85,000 EUR annually.", (70_000, 85_000, "EUR")),
    ("Salary £55k to £65k plus bonus.", (55_000, 65_000, "GBP")),
    ("Base salary: $135,000.", (135_000, 135_000, "USD")),
    ("Contract rate: $85/hour.", (None, None, None)),
    ("Learning budget of $2,000 per year. 3+ years of relevant experience.", (None, None, None)),
])
def test_salary_formats(line, expected):
    f = extract_fields(line)
    assert (f["salary_min"], f["salary_max"], f["salary_currency"]) == expected


def test_longest_alias_wins_and_aliases_map_to_canonical():
    f = extract_fields("Our stack: Azure Data Factory, PySpark, k8s, Postgres and large language models.")
    assert f["skills"] == ["azure data factory", "kubernetes", "llms", "postgresql", "spark"]


def test_skill_word_boundaries():
    assert extract_fields("JavaScript and NoSQL and scalable systems")["skills"] == []


@pytest.mark.parametrize("text, expected", [
    ("Flexible hybrid setup, 3 days on-site in Paris, France.", "hybrid"),
    ("Interviews are remote-friendly, but the role itself is on-site in Paris, France.", "onsite"),
    ("100% remote (team anchored in Austin, TX).", "remote"),
    ("Office-based in Denver, CO, five days a week.", "onsite"),
])
def test_remote_policy_precedence(text, expected):
    assert extract_fields(text)["remote_policy"] == expected


@pytest.mark.parametrize("header, title, seniority", [
    ("Job Title: Sr. Data Engineer\nLocation: Boston, MA", "Sr. Data Engineer", "senior"),
    ("Acme is hiring an Analytics Engineer II to join our data team.", "Analytics Engineer II", "mid"),
    ("About the role\nWe're looking for a Principal AI Engineer who loves data.", "Principal AI Engineer", "staff"),
    ("BI Developer Team Lead\nAcme | London, UK", "BI Developer Team Lead", "lead"),
    ("Machine Learning Engineer I\nAcme | Seattle, WA", "Machine Learning Engineer I", "junior"),
    ("EARN $5,000 PER WEEK FROM HOME!!!", None, "mid"),
])
def test_title_and_seniority(header, title, seniority):
    f = extract_fields(header)
    assert (f["title"], f["seniority"]) == (title, seniority)

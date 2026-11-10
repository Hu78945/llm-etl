import anthropic
import pytest
from pydantic import ValidationError

from llm_etl.extract_llm import LLMOutput
from llm_etl.schema import JobPosting

VALID = {"title": "Senior Data Engineer", "seniority": "senior", "skills": ["sql", "python", "sql"],
             "salary_min": 120_000, "salary_max": 150_000, "salary_currency": "USD",
             "remote_policy": "hybrid", "location": "Austin, TX"}


def test_valid_posting_normalises_skills():
    assert JobPosting(**VALID).skills == ["python", "sql"]


def test_no_salary_is_valid():
    p = JobPosting(**{**VALID, "salary_min": None, "salary_max": None, "salary_currency": None})
    assert p.salary_min is None


@pytest.mark.parametrize("override, message", [
    ({"salary_min": 150_000, "salary_max": 120_000}, "salary_min 150000 > salary_max 120000"),
    ({"salary_currency": None}, "without salary_currency"),
    ({"salary_max": None}, "both be set"),
    ({"salary_min": 85, "salary_max": 85}, "outside annual bounds"),  # an hourly rate mis-read as salary
    ({"salary_min": None, "salary_max": None}, "salary_currency set without a salary"),
    ({"skills": ["cobol"]}, "skills.0"),
    ({"seniority": "rockstar"}, "seniority"),
    ({"title": ""}, "title"),
    ({"bonus": 1}, "bonus"),  # extra="forbid": no silent schema drift
])
def test_invalid_postings_are_rejected(override, message):
    with pytest.raises(ValidationError, match=message):
        JobPosting(**{**VALID, **override})


def test_llm_output_schema_is_structured_output_compatible():
    """The SDK must be able to turn LLMOutput into a structured-output JSON schema."""
    schema = anthropic.transform_schema(LLMOutput.model_json_schema())
    assert set(schema["required"]) == set(LLMOutput.model_fields)
    assert schema["additionalProperties"] is False

"""Extraction contract: the strict Pydantic schema every extractor must satisfy.

The skill vocabulary lives in dbt/seeds/skill_taxonomy.csv so Python validation and
the dbt `relationships` test share one source of truth.
"""

import csv
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from llm_etl.config import TAXONOMY_CSV

with TAXONOMY_CSV.open() as f:
    TAXONOMY: dict[str, list[str]] = {
        row["skill"]: row["aliases"].split("|") for row in csv.DictReader(f)
    }

Seniority = Literal["junior", "mid", "senior", "staff", "lead"]
RemotePolicy = Literal["remote", "hybrid", "onsite"]
Currency = Literal["USD", "EUR", "GBP"]
Skill = Literal[tuple(TAXONOMY)]  # type: ignore[valid-type]

# Annual base salary sanity bounds. Values outside are almost always a
# mis-read (hourly rate, monthly figure, a stray number), so they are rejected.
MIN_ANNUAL, MAX_ANNUAL = 10_000, 1_000_000


class JobPosting(BaseModel):
    """Silver-layer record. Construction fails loudly; failures go to quarantine."""

    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=3, max_length=120)
    seniority: Seniority
    skills: list[Skill]
    salary_min: int | None = None
    salary_max: int | None = None
    salary_currency: Currency | None = None
    remote_policy: RemotePolicy
    location: str | None = None

    @field_validator("skills")
    @classmethod
    def _dedupe_sorted(cls, v: list[str]) -> list[str]:
        return sorted(set(v))

    @model_validator(mode="after")
    def _salary_consistent(self) -> Self:
        lo, hi, cur = self.salary_min, self.salary_max, self.salary_currency
        if (lo is None) != (hi is None):
            raise ValueError("salary_min and salary_max must both be set or both null")
        if lo is None:
            if cur is not None:
                raise ValueError("salary_currency set without a salary")
            return self
        if cur is None:
            raise ValueError("salary present without salary_currency")
        if lo > hi:
            raise ValueError(f"salary_min {lo} > salary_max {hi}")
        if not (MIN_ANNUAL <= lo and hi <= MAX_ANNUAL):
            raise ValueError(f"salary {lo}-{hi} outside annual bounds")
        return self


def format_errors(e: ValidationError) -> str:
    return "; ".join(f"{'.'.join(map(str, d['loc'])) or 'record'}: {d['msg']}" for d in e.errors())

"""LLM extractor: Claude structured output -> strict Pydantic validation, with feedback retries."""

import time

import anthropic
from pydantic import BaseModel, ValidationError

from llm_etl import config
from llm_etl.schema import Currency, JobPosting, RemotePolicy, Seniority, Skill, format_errors

PROMPT_VERSION = "v1"
MAX_ATTEMPTS = 3

SYSTEM = f"""You extract structured fields from a single job posting.

Rules:
- title: the job title exactly as written (no company, no location). null if the text is not a job posting.
- seniority: junior (junior/associate/graduate/"I"), mid (no level marker or "II"), senior (senior/sr/"III"),
  staff (staff/principal), lead (lead/team lead).
- skills: every technology the posting mentions, mapped to these canonical names only: {", ".join(Skill.__args__)}.
- salary_min / salary_max: ANNUAL base salary in whole currency units. A single figure means min = max.
  Hourly, daily or monthly rates, budgets, stipends and bonuses are NOT salary: use null.
- salary_currency: ISO code (USD, EUR, GBP), null when there is no salary.
- remote_policy: remote, hybrid or onsite - judge the role itself, not the interview process.
- location: the city as written (e.g. "Austin, TX"), or null.
Never invent values the posting does not state; use null."""


class LLMOutput(BaseModel):
    """What the model is asked to return. Deliberately looser than JobPosting (nullable fields,
    no cross-field rules) so business-rule failures surface as validation errors we can feed back."""

    title: str | None
    seniority: Seniority | None
    skills: list[Skill]
    salary_min: int | None
    salary_max: int | None
    salary_currency: Currency | None
    remote_policy: RemotePolicy | None
    location: str | None


def extractor_name() -> str:
    return f"llm:{config.ANTHROPIC_MODEL}:{PROMPT_VERSION}"


def make_client() -> anthropic.Anthropic:
    # The SDK retries 429/5xx/connection errors with exponential backoff and honours retry-after.
    return anthropic.Anthropic(max_retries=6)


def extract(client: anthropic.Anthropic, text: str) -> dict:
    """Returns a cache row dict. Transient API errors propagate (so they are retried next run,
    never cached); validation failures after MAX_ATTEMPTS are returned as a cached error."""
    messages: list = [{"role": "user", "content": f"<posting>\n{text}\n</posting>"}]
    usage_in = usage_out = 0
    started = time.perf_counter()
    error = None
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            resp = client.messages.parse(
                model=config.ANTHROPIC_MODEL,
                max_tokens=2048,
                system=SYSTEM,
                messages=messages,
                output_format=LLMOutput,
                output_config={"effort": "low"},
            )
        except ValidationError as e:  # model output did not even match LLMOutput
            error = f"output schema: {e.errors()[0]['msg']}"
            messages.append({"role": "user", "content": f"Your previous output was invalid ({error}). Retry."})
            continue
        usage_in += resp.usage.input_tokens
        usage_out += resp.usage.output_tokens
        if resp.stop_reason == "refusal" or resp.parsed_output is None:
            error = f"no output (stop_reason={resp.stop_reason})"
            break
        try:
            posting = JobPosting.model_validate(resp.parsed_output.model_dump())
            error = None
            break
        except ValidationError as e:
            error = format_errors(e)
            messages += [
                # Echo the turn back as-is (thinking blocks must be returned unchanged), minus the
                # SDK-local parsed_output field, which is not part of the API's content schema.
                {"role": "assistant", "content": [b.model_dump(exclude={"parsed_output"}, exclude_none=True)
                                                  for b in resp.content]},
                {"role": "user", "content": f"That output failed validation: {error}. Return corrected "
                 "fields; if the posting does not state a value, use null rather than guessing."},
            ]
    return {
        "result": None if error else posting.model_dump(),
        "error": error,
        "attempts": attempt,
        "input_tokens": usage_in,
        "output_tokens": usage_out,
        "cost_usd": (usage_in * config.PRICE_IN_PER_MTOK + usage_out * config.PRICE_OUT_PER_MTOK) / 1e6,
        "latency_ms": int((time.perf_counter() - started) * 1000),
    }

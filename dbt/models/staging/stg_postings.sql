select
    s.posting_id,
    b.company,
    b.posted_at,
    s.title,
    s.seniority,
    s.remote_policy,
    s.location,
    s.salary_min,
    s.salary_max,
    s.salary_currency,
    s.extractor
from {{ source('silver', 'extracted_postings') }} s
join {{ source('bronze', 'raw_postings') }} b using (posting_id)

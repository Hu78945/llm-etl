-- Reposts flagged by semantic dedup must never reach the gold layer.
select f.posting_id
from {{ ref('fct_postings') }} f
join {{ source('silver', 'duplicates') }} d using (posting_id)

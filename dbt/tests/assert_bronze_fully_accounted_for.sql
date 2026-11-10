-- Reconciliation: every bronze posting must land in exactly one place - silver, quarantine,
-- or the duplicates table. Rows returned here were silently dropped or double-counted.
with routed as (
    select posting_id, 'silver' as dest from {{ source('silver', 'extracted_postings') }}
    union all
    select posting_id, 'quarantine' from {{ source('silver', 'quarantine') }}
    union all
    select posting_id, 'duplicate' from {{ source('silver', 'duplicates') }}
)

select b.posting_id, count(r.posting_id) as destinations
from {{ source('bronze', 'raw_postings') }} b
left join routed r using (posting_id)
group by b.posting_id
having count(r.posting_id) != 1

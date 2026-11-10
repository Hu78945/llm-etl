with skills as (
    select posting_id, count(*) as skill_count
    from {{ ref('stg_posting_skills') }}
    group by posting_id
)

select
    p.*,
    coalesce(s.skill_count, 0) as skill_count,
    round((p.salary_min + p.salary_max) / 2.0 * fx.usd_per_unit, 0) as salary_mid_usd
from {{ ref('stg_postings') }} p
left join skills s using (posting_id)
left join {{ ref('fx_rates') }} fx on fx.currency = p.salary_currency

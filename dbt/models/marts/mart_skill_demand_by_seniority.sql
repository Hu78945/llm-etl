-- Share of postings at each seniority level that ask for each skill.
with totals as (
    select seniority, count(*) as postings_at_level
    from {{ ref('fct_postings') }}
    group by seniority
),

demand as (
    select f.seniority, ps.skill, count(*) as postings_with_skill
    from {{ ref('stg_posting_skills') }} ps
    join {{ ref('fct_postings') }} f using (posting_id)
    group by f.seniority, ps.skill
)

select
    d.seniority,
    d.skill,
    sk.category,
    d.postings_with_skill,
    t.postings_at_level,
    round(d.postings_with_skill * 1.0 / t.postings_at_level, 4) as share_of_postings,
    rank() over (partition by d.seniority order by d.postings_with_skill desc) as demand_rank
from demand d
join totals t using (seniority)
join {{ ref('dim_skills') }} sk using (skill)

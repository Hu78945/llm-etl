select
    t.skill,
    t.category,
    count(ps.posting_id) as postings
from {{ ref('skill_taxonomy') }} t
left join {{ ref('stg_posting_skills') }} ps using (skill)
group by t.skill, t.category

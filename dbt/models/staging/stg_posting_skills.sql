with exploded as (
    {{ unnest_skills(source('silver', 'extracted_postings')) }}
)

select
    posting_id || ':' || skill as posting_skill_id,
    posting_id,
    skill
from exploded

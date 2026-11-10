select seniority, skill, share_of_postings
from {{ ref('mart_skill_demand_by_seniority') }}
where share_of_postings <= 0 or share_of_postings > 1

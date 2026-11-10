-- Salary bands per seniority, normalised to USD (annual base, midpoint of the posted range).
select
    seniority,
    count(*) as postings_with_salary,
    min(salary_mid_usd) as min_usd,
    percentile_cont(0.25) within group (order by salary_mid_usd) as p25_usd,
    percentile_cont(0.50) within group (order by salary_mid_usd) as median_usd,
    percentile_cont(0.75) within group (order by salary_mid_usd) as p75_usd,
    max(salary_mid_usd) as max_usd
from {{ ref('fct_postings') }}
where salary_mid_usd is not null
group by seniority

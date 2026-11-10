-- Salary must be all-or-nothing, ordered, and within annual bounds.
select posting_id, salary_min, salary_max, salary_currency
from {{ ref('fct_postings') }}
where salary_min > salary_max
   or (salary_min is null) != (salary_currency is null)
   or (salary_min is null) != (salary_max is null)
   or salary_min < 10000
   or salary_max > 1000000

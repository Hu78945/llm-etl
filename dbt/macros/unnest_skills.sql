{# One row per (posting, skill). The only adapter-specific SQL in the project. #}
{% macro unnest_skills(relation) %}
    {{ return(adapter.dispatch('unnest_skills')(relation)) }}
{% endmacro %}

{% macro default__unnest_skills(relation) %}
    select posting_id, unnest(skills) as skill from {{ relation }}
{% endmacro %}

{% macro snowflake__unnest_skills(relation) %}
    select p.posting_id, f.value::string as skill
    from {{ relation }} p, lateral flatten(input => p.skills) f
{% endmacro %}

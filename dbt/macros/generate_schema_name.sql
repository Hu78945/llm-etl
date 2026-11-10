{# Use the configured schema name as-is (staging / gold / reference) instead of
   dbt's default "<target_schema>_<custom_schema>" concatenation. #}
{% macro generate_schema_name(custom_schema_name, node) -%}
    {{ custom_schema_name if custom_schema_name else target.schema }}
{%- endmacro %}

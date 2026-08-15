-- Test that coverage_pct is between 0 and 100
-- Used to validate that coverage calculations are sensible

{% test coverage_pct_between_0_100(model, column_name) %}

select *
from {{ model }}
where {{ column_name }} is not null
  and ({{ column_name }} < 0 or {{ column_name }} > 100)

{% endtest %}

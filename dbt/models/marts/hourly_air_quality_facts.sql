{{
  config(
    materialized='table',
    alias='hourly_air_quality_facts',
    on_schema_change='fail',
    indexes=[
      {'columns': ['location_id', 'hour_start_utc']},
      {'columns': ['location_id', 'pollutant', 'hour_start_utc']},
    ],
    tags=['marts', 'air_quality', 'fact']
  )
}}

with deduplicated_air_quality as (
  select
    source,
    station_id,
    pollutant,
    value,
    observed_at_utc,
    raw_payload_hash
  from {{ ref('int_air_quality_deduplicated') }}
  where pollutant in ('pm25', 'pm10', 'no2', 'o3', 'so2')
),

hourly_aggregation as (
  select
    source,
    station_id,
    pollutant,
    -- Align to hour
    date_trunc('hour', observed_at_utc) as hour_start_utc,
    -- Calculate metrics
    count(*) as observation_count,
    count(distinct raw_payload_hash) as unique_measurement_count,
    avg(value) as mean_value,
    cast(percentile_cont(0.5) within group (order by value) as decimal(10, 2)) as median_value,
    min(value) as min_value,
    max(value) as max_value,
    cast(stddev_pop(value) as decimal(10, 2)) as stddev_value,
    -- Data quality
    sum(case when value > 0 then 1 else 0 end) as non_zero_count
  from deduplicated_air_quality
  group by 1, 2, 3, 4
),

-- Map station to location (mock join for now)
with_location_mapping as (
  select
    coalesce(dim_station.location_id, 'UNMAPPED') as location_id,
    hourly_agg.source,
    hourly_agg.station_id,
    hourly_agg.pollutant,
    hourly_agg.hour_start_utc,
    hourly_agg.observation_count,
    hourly_agg.mean_value,
    hourly_agg.median_value,
    hourly_agg.min_value,
    hourly_agg.max_value,
    hourly_agg.stddev_value,
    hourly_agg.non_zero_count
  from hourly_aggregation as hourly_agg
  left join {{ ref('dim_station') }} as dim_station
    on hourly_agg.station_id = dim_station.station_id
    and hourly_agg.source = dim_station.source
),

-- Join with baselines for comparison
with_baselines as (
  select
    wlm.location_id,
    wlm.source,
    wlm.station_id,
    wlm.pollutant,
    wlm.hour_start_utc,
    wlm.observation_count,
    wlm.mean_value,
    wlm.median_value,
    wlm.min_value,
    wlm.max_value,
    wlm.stddev_value,
    wlm.non_zero_count,
    -- Expected observations (assuming 60-minute measurement interval)
    1 as expected_observation_count,
    cast(
      case
        when 1 > 0 then (wlm.observation_count::float / 1.0) * 100.0
        else 0.0
      end as decimal(5, 2)
    ) as coverage_pct,
    -- Baseline comparisons
    coalesce(baseline.historical_median, wlm.median_value) as baseline_median,
    coalesce(baseline.mad, 0) as baseline_mad,
    coalesce(baseline.p90, wlm.max_value) as baseline_p90,
    coalesce(baseline.p95, wlm.max_value) as baseline_p95,
    coalesce(baseline.p99, wlm.max_value) as baseline_p99,
    -- Anomaly detection
    case
      when baseline.historical_median is not null
        and abs(wlm.median_value - baseline.historical_median) > 3 * baseline.mad
      then 1
      else 0
    end as anomaly_flag,
    -- Quality score (0-100)
    cast(
      least(
        100,
        greatest(
          0,
          (wlm.observation_count::float / 1.0) * 100.0 * 0.7  -- 70% weight to coverage
          + (1.0 - least(1.0, abs(wlm.mean_value - coalesce(baseline.historical_median, wlm.mean_value)) / (coalesce(baseline.mad, 1) + 0.1))) * 30.0  -- 30% to deviation
        )
      ) as decimal(5, 2)
    ) as quality_score
  from with_location_mapping as wlm
  left join {{ ref('dim_air_quality_baselines') }} as baseline
    on wlm.location_id = baseline.location_id
    and wlm.pollutant = baseline.pollutant
    and extract(month from wlm.hour_start_utc) = baseline.month
    and extract(hour from wlm.hour_start_utc) = baseline.hour_of_day
)

select
  {{ dbt_utils.generate_surrogate_key(['location_id', 'pollutant', 'hour_start_utc']) }} as fact_key,
  location_id,
  source,
  station_id,
  pollutant,
  hour_start_utc,
  observation_count,
  mean_value,
  median_value,
  min_value,
  max_value,
  stddev_value,
  expected_observation_count,
  coverage_pct,
  baseline_median,
  baseline_mad,
  baseline_p90,
  baseline_p95,
  baseline_p99,
  anomaly_flag,
  quality_score,
  cast(current_timestamp as timestamp with time zone) as loaded_at
from with_baselines
where location_id != 'UNMAPPED'  -- Filter out unmapped records

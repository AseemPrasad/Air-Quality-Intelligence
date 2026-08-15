{{
  config(
    materialized='table',
    alias='hourly_weather_facts',
    on_schema_change='fail',
    indexes=[
      {'columns': ['location_id', 'hour_start_utc']},
    ],
    tags=['marts', 'weather', 'fact']
  )
}}

with weather_aligned as (
  select
    source,
    location_id,
    hour_start_utc,
    temperature_c,
    humidity_pct,
    wind_speed_kmh,
    wind_direction_deg,
    pressure_hpa,
    precipitation_mm,
    cloud_cover_pct,
    observed_at_utc,
    raw_payload_hash,
    obs_rank_in_hour
  from {{ ref('int_weather_aligned') }}
),

hourly_aggregation as (
  select
    source,
    location_id,
    hour_start_utc,
    count(*) as observation_count,
    count(distinct raw_payload_hash) as unique_measurement_count,
    -- Temperature: mean (continuous)
    cast(avg(temperature_c) as decimal(5, 2)) as mean_temperature_c,
    cast(min(temperature_c) as decimal(5, 2)) as min_temperature_c,
    cast(max(temperature_c) as decimal(5, 2)) as max_temperature_c,
    -- Humidity: mean (continuous percentage)
    cast(avg(humidity_pct) as decimal(5, 2)) as mean_humidity_pct,
    cast(min(humidity_pct) as decimal(5, 2)) as min_humidity_pct,
    cast(max(humidity_pct) as decimal(5, 2)) as max_humidity_pct,
    -- Wind speed: mean (continuous)
    cast(avg(wind_speed_kmh) as decimal(5, 2)) as mean_wind_speed_kmh,
    cast(max(wind_speed_kmh) as decimal(5, 2)) as max_wind_speed_kmh,
    -- Wind direction: mean (circular mean, approximated)
    cast(avg(wind_direction_deg) as decimal(5, 2)) as mean_wind_direction_deg,
    -- Pressure: mean (continuous)
    cast(avg(pressure_hpa) as decimal(7, 2)) as mean_pressure_hpa,
    -- Precipitation: sum (cumulative in hour)
    cast(sum(precipitation_mm) as decimal(8, 2)) as total_precipitation_mm,
    -- Cloud cover: mean (percentage)
    cast(avg(cloud_cover_pct) as decimal(5, 2)) as mean_cloud_cover_pct
  from weather_aligned
  group by 1, 2, 3
),

-- Map location metadata
with_location_mapping as (
  select
    coalesce(dim_location.location_id, hourly_agg.location_id) as location_id,
    coalesce(dim_location.city, 'UNKNOWN') as city,
    hourly_agg.source,
    hourly_agg.hour_start_utc,
    hourly_agg.observation_count,
    hourly_agg.mean_temperature_c,
    hourly_agg.min_temperature_c,
    hourly_agg.max_temperature_c,
    hourly_agg.mean_humidity_pct,
    hourly_agg.min_humidity_pct,
    hourly_agg.max_humidity_pct,
    hourly_agg.mean_wind_speed_kmh,
    hourly_agg.max_wind_speed_kmh,
    hourly_agg.mean_wind_direction_deg,
    hourly_agg.mean_pressure_hpa,
    hourly_agg.total_precipitation_mm,
    hourly_agg.mean_cloud_cover_pct,
    -- Expected observations (assuming 60-minute measurement interval)
    1 as expected_observation_count,
    cast(
      case
        when 1 > 0 then (hourly_agg.observation_count::float / 1.0) * 100.0
        else 0.0
      end as decimal(5, 2)
    ) as coverage_pct,
    -- Quality score based on coverage
    cast(
      least(
        100,
        greatest(
          0,
          (hourly_agg.observation_count::float / 1.0) * 100.0
        )
      ) as decimal(5, 2)
    ) as quality_score
  from hourly_aggregation as hourly_agg
  left join {{ ref('dim_location') }} as dim_location
    on hourly_agg.location_id = dim_location.location_id
)

select
  {{ dbt_utils.generate_surrogate_key(['location_id', 'hour_start_utc']) }} as fact_key,
  location_id,
  city,
  source,
  hour_start_utc,
  observation_count,
  mean_temperature_c,
  min_temperature_c,
  max_temperature_c,
  mean_humidity_pct,
  min_humidity_pct,
  max_humidity_pct,
  mean_wind_speed_kmh,
  max_wind_speed_kmh,
  mean_wind_direction_deg,
  mean_pressure_hpa,
  total_precipitation_mm,
  mean_cloud_cover_pct,
  expected_observation_count,
  coverage_pct,
  quality_score,
  cast(current_timestamp as timestamp with time zone) as loaded_at
from with_location_mapping

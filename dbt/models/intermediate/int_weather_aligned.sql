{{
  config(
    materialized='view',
    alias='weather_aligned',
    tags=['intermediate', 'weather']
  )
}}

with raw_weather as (
  select
    source,
    location_id,
    temperature_c,
    humidity_pct,
    wind_speed_kmh,
    wind_direction_deg,
    pressure_hpa,
    precipitation_mm,
    cloud_cover_pct,
    observed_at,
    ingested_at,
    raw_payload_hash,
    row_number() over (
      partition by source, location_id, observed_at
      order by ingested_at desc
    ) as rn
  from {{ ref('stg_weather_raw') }}
  where temperature_c is not null
),

deduplicated as (
  select
    source,
    location_id,
    temperature_c,
    humidity_pct,
    wind_speed_kmh,
    wind_direction_deg,
    pressure_hpa,
    precipitation_mm,
    cloud_cover_pct,
    cast(observed_at as timestamp with time zone) as observed_at_utc,
    cast(ingested_at as timestamp with time zone) as ingested_at_utc,
    raw_payload_hash
  from raw_weather
  where rn = 1
),

-- Align to nearest hour (round down)
hourly_aligned as (
  select
    source,
    location_id,
    temperature_c,
    humidity_pct,
    wind_speed_kmh,
    wind_direction_deg,
    pressure_hpa,
    precipitation_mm,
    cloud_cover_pct,
    -- Round observation time down to nearest hour
    date_trunc('hour', observed_at_utc) as hour_start_utc,
    observed_at_utc,
    ingested_at_utc,
    raw_payload_hash,
    row_number() over (
      partition by source, location_id, date_trunc('hour', observed_at_utc)
      order by observed_at_utc
    ) as obs_rank_in_hour
  from deduplicated
)

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
  ingested_at_utc,
  raw_payload_hash,
  obs_rank_in_hour,
  cast(current_timestamp as timestamp with time zone) as processed_at
from hourly_aligned
where obs_rank_in_hour = 1  -- Keep first observation in each hour

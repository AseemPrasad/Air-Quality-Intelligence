{{
  config(
    materialized='view',
    alias='air_quality_deduplicated',
    tags=['intermediate', 'air_quality']
  )
}}

with raw_data as (
  select
    source,
    station_id,
    sensor_id,
    pollutant,
    value,
    unit,
    observed_at,
    ingested_at,
    raw_payload_hash,
    row_number() over (
      partition by source, station_id, sensor_id, pollutant, observed_at
      order by ingested_at desc
    ) as rn
  from {{ ref('stg_air_quality_raw') }}
  where value is not null
),

deduplicated as (
  select
    source,
    station_id,
    sensor_id,
    pollutant,
    -- Normalize unit to µg/m³
    case
      when unit in ('µg/m³', 'ug/m3') then value
      when unit = 'mg/m³' then value * 1000  -- Convert mg/m³ to µg/m³
      when unit in ('ppb', 'ppm') then value * 1.2  -- Rough approximation (depends on gas)
      else value
    end as normalized_value_ug_m3,
    unit as original_unit,
    -- Ensure timezone awareness
    cast(observed_at as timestamp with time zone) as observed_at_utc,
    cast(ingested_at as timestamp with time zone) as ingested_at_utc,
    raw_payload_hash,
    row_number() over (
      partition by source, station_id, sensor_id, pollutant, observed_at
      order by ingested_at desc
    ) as duplicate_rank
  from raw_data
  where rn = 1  -- Keep only latest version if multiple updates
)

select
  source,
  station_id,
  sensor_id,
  pollutant,
  normalized_value_ug_m3 as value,
  original_unit,
  observed_at_utc,
  ingested_at_utc,
  raw_payload_hash,
  cast(current_timestamp as timestamp with time zone) as processed_at
from deduplicated
where duplicate_rank = 1

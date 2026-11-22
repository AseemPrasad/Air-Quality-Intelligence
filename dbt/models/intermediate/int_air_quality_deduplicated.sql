
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
            partition by
                source,
                station_id,
                sensor_id,
                pollutant,
                observed_at
            order by
                ingested_at desc nulls last,
                raw_payload_hash desc nulls last
        ) as rn

    from {{ ref('stg_air_quality_raw') }}

    where value is not null
      and observed_at is not null

),

deduplicated as (

    select
        source,
        station_id,
        sensor_id,
        pollutant,

        case
            when lower(trim(unit)) in (
                'µg/m³',
                'ug/m3',
                'μg/m³'
            )
                then value

            when lower(trim(unit)) in (
                'mg/m³',
                'mg/m3'
            )
                then value * 1000

            -- Gas concentration conversion requires
            -- pollutant-specific molecular weight
            -- and temperature/pressure information.
            when lower(trim(unit)) in ('ppb', 'ppm')
                then null

            else null
        end as normalized_value_ug_m3,

        unit as original_unit,

        case
            when lower(trim(unit)) in (
                'µg/m³', 'ug/m3', 'μg/m³',
                'mg/m³', 'mg/m3'
            )
                then 'converted'

            when lower(trim(unit)) in ('ppb', 'ppm')
                then 'requires_gas_conversion'

            else 'unsupported_unit'
        end as conversion_status,

        cast(
            observed_at as timestamp with time zone
        ) as observed_at_utc,

        cast(
            ingested_at as timestamp with time zone
        ) as ingested_at_utc,

        raw_payload_hash

    from raw_data

    where rn = 1

)

select
    source,
    station_id,
    sensor_id,
    pollutant,
    normalized_value_ug_m3 as value,
    original_unit,
    conversion_status,
    observed_at_utc,
    ingested_at_utc,
    raw_payload_hash,
    current_timestamp as processed_at

from deduplicated

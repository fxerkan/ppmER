{{
    config(
        materialized="table",
        schema="core",
        tags=["core", "dim", "reference"],
        unique_key="holiday_date"
    )
}}

{#
  Turkish Holidays and Special Working Days Reference Table

  This dimension stores Turkish national holidays, religious holidays, and special working days.

  Expected effort values:
  - 0.0: Full holiday (no work expected)
  - 0.5: Half day work (4 hours / 0.5 person-day expected)
  - 1.0: Full work day (8 hours / 1.0 person-day expected) - DEFAULT for all other days

  Usage:
  This table is joined with dim_calendar to determine expected working effort per day.
  Easily extendable by adding new rows for future years or special cases.
#}

select
    holiday_date::date,
    holiday_name,
    holiday_type,
    expected_effort_person_days,
    year,
    description
from (
    values
    -- 2025 Turkish Holidays
    ('2025-01-01', 'Yılbaşı', 'National Holiday', 0.0, 2025, 'New Year'),
    ('2025-03-31', 'Ramazan Bayramı Arefe', 'Religious Holiday Eve', 0.5, 2025, 'Ramadan Eve - Half Day'),
    ('2025-04-01', 'Ramazan Bayramı 1. Gün', 'Religious Holiday', 0.0, 2025, 'Ramadan Day 1'),
    ('2025-04-02', 'Ramazan Bayramı 2. Gün', 'Religious Holiday', 0.0, 2025, 'Ramadan Day 2'),
    ('2025-04-03', 'Ramazan Bayramı 3. Gün', 'Religious Holiday', 0.0, 2025, 'Ramadan Day 3'),
    ('2025-04-23', '23 Nisan Ulusal Egemenlik ve Çocuk Bayramı', 'National Holiday', 0.0, 2025, 'National Sovereignty and Children''s Day'),
    ('2025-05-01', '1 Mayıs İşçi Bayramı', 'National Holiday', 0.0, 2025, 'Labour Day'),
    ('2025-05-19', '19 Mayıs Atatürk''ü Anma Gençlik ve Spor Bayramı', 'National Holiday', 0.0, 2025, 'Youth and Sports Day'),
    ('2025-06-06', 'Kurban Bayramı Arefe', 'Religious Holiday Eve', 0.5, 2025, 'Sacrifice Eve - Half Day'),
    ('2025-06-07', 'Kurban Bayramı 1. Gün', 'Religious Holiday', 0.0, 2025, 'Sacrifice Day 1'),
    ('2025-06-08', 'Kurban Bayramı 2. Gün', 'Religious Holiday', 0.0, 2025, 'Sacrifice Day 2'),
    ('2025-06-09', 'Kurban Bayramı 3. Gün', 'Religious Holiday', 0.0, 2025, 'Sacrifice Day 3'),
    ('2025-06-10', 'Kurban Bayramı 4. Gün', 'Religious Holiday', 0.0, 2025, 'Sacrifice Day 4'),
    ('2025-07-15', '15 Temmuz Demokrasi ve Milli Birlik Günü', 'National Holiday', 0.0, 2025, 'Democracy and National Unity Day'),
    ('2025-08-30', '30 Ağustos Zafer Bayramı', 'National Holiday', 0.0, 2025, 'Victory Day'),
    ('2025-10-28', '29 Ekim Cumhuriyet Bayramı Arefe', 'National Holiday Eve', 0.5, 2025, 'Republic Day Eve - Half Day'),
    ('2025-10-29', '29 Ekim Cumhuriyet Bayramı', 'National Holiday', 0.0, 2025, 'Republic Day'),

    -- 2026 Turkish Holidays
    ('2026-01-01', 'Yılbaşı', 'National Holiday', 0.0, 2026, 'New Year'),
    ('2026-03-20', 'Ramazan Bayramı Arefe', 'Religious Holiday Eve', 0.5, 2026, 'Ramadan Eve - Half Day'),
    ('2026-03-21', 'Ramazan Bayramı 1. Gün', 'Religious Holiday', 0.0, 2026, 'Ramadan Day 1'),
    ('2026-03-22', 'Ramazan Bayramı 2. Gün', 'Religious Holiday', 0.0, 2026, 'Ramadan Day 2'),
    ('2026-03-23', 'Ramazan Bayramı 3. Gün', 'Religious Holiday', 0.0, 2026, 'Ramadan Day 3'),
    ('2026-04-23', '23 Nisan Ulusal Egemenlik ve Çocuk Bayramı', 'National Holiday', 0.0, 2026, 'National Sovereignty and Children''s Day'),
    ('2026-05-01', '1 Mayıs İşçi Bayramı', 'National Holiday', 0.0, 2026, 'Labour Day'),
    ('2026-05-19', '19 Mayıs Atatürk''ü Anma Gençlik ve Spor Bayramı', 'National Holiday', 0.0, 2026, 'Youth and Sports Day'),
    ('2026-05-27', 'Kurban Bayramı Arefe', 'Religious Holiday Eve', 0.5, 2026, 'Sacrifice Eve - Half Day'),
    ('2026-05-28', 'Kurban Bayramı 1. Gün', 'Religious Holiday', 0.0, 2026, 'Sacrifice Day 1'),
    ('2026-05-29', 'Kurban Bayramı 2. Gün', 'Religious Holiday', 0.0, 2026, 'Sacrifice Day 2'),
    ('2026-05-30', 'Kurban Bayramı 3. Gün', 'Religious Holiday', 0.0, 2026, 'Sacrifice Day 3'),
    ('2026-05-31', 'Kurban Bayramı 4. Gün', 'Religious Holiday', 0.0, 2026, 'Sacrifice Day 4'),
    ('2026-07-15', '15 Temmuz Demokrasi ve Milli Birlik Günü', 'National Holiday', 0.0, 2026, 'Democracy and National Unity Day'),
    ('2026-08-30', '30 Ağustos Zafer Bayramı', 'National Holiday', 0.0, 2026, 'Victory Day'),
    ('2026-10-28', '29 Ekim Cumhuriyet Bayramı Arefe', 'National Holiday Eve', 0.5, 2026, 'Republic Day Eve - Half Day'),
    ('2026-10-29', '29 Ekim Cumhuriyet Bayramı', 'National Holiday', 0.0, 2026, 'Republic Day')
) as holidays(
    holiday_date,
    holiday_name,
    holiday_type,
    expected_effort_person_days,
    year,
    description
)
order by holiday_date

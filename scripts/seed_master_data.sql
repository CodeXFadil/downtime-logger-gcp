-- scripts/seed_master_data.sql
-- Run AFTER migrate_schema.sql
-- Equipment is site-specific; update equipment_id / display_name per plant.
-- DowntimeReasons is global.

-- DowntimeReasons (global — same across all sites)
INSERT INTO DowntimeReasons (reason_name, category)
SELECT reason_name, category FROM (VALUES
    ('Mechanical Failure',         'Unplanned'),
    ('Electrical Failure',         'Unplanned'),
    ('Instrument / Control Fault', 'Unplanned'),
    ('Process Upset',              'Unplanned'),
    ('Utility Failure',            'Unplanned'),
    ('Safety / Emergency Stop',    'Unplanned'),
    ('Raw Material Issue',         'Unplanned'),
    ('Other',                      'Unplanned'),
    ('Planned Maintenance',        'Planned'),
    ('Scheduled Shutdown',         'Planned'),
    ('Inspection / Regulatory',    'Planned'),
    ('Trial / Commissioning',      'Planned')
) AS v(reason_name, category)
WHERE NOT EXISTS (SELECT 1 FROM DowntimeReasons WHERE reason_name = v.reason_name);

-- Equipment — Curtis Bay (site_name must match SITE_NAME env var exactly)
INSERT INTO Equipment (site_name, equipment_id, display_name) VALUES
    ('Curtis Bay', 'PUMP-01',     'Feed Pump'),
    ('Curtis Bay', 'PUMP-02',     'Discharge Pump'),
    ('Curtis Bay', 'COMP-01',     'Air Compressor'),
    ('Curtis Bay', 'REACTOR-A',   'Reactor Vessel A'),
    ('Curtis Bay', 'REACTOR-B',   'Reactor Vessel B'),
    ('Curtis Bay', 'FILTER-01',   'Process Filter'),
    ('Curtis Bay', 'CONVEYOR-01', 'Feed Conveyor'),
    ('Curtis Bay', 'DRYER-01',    'Spray Dryer'),
    ('Curtis Bay', 'HX-01',       'Heat Exchanger')
ON CONFLICT (site_name, equipment_id) DO NOTHING;

-- Equipment — Kuantan (update IDs/names to match real plant equipment)
INSERT INTO Equipment (site_name, equipment_id, display_name) VALUES
    ('Kuantan', 'PUMP-01',     'Feed Pump'),
    ('Kuantan', 'PUMP-02',     'Discharge Pump'),
    ('Kuantan', 'COMP-01',     'Air Compressor'),
    ('Kuantan', 'REACTOR-A',   'Reactor Vessel A'),
    ('Kuantan', 'REACTOR-B',   'Reactor Vessel B'),
    ('Kuantan', 'FILTER-01',   'Process Filter'),
    ('Kuantan', 'CONVEYOR-01', 'Feed Conveyor'),
    ('Kuantan', 'DRYER-01',    'Spray Dryer'),
    ('Kuantan', 'HX-01',       'Heat Exchanger')
ON CONFLICT (site_name, equipment_id) DO NOTHING;

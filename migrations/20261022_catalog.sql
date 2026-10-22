-- Additive migration; works on PostgreSQL and SQLite. No existing rows change.
CREATE TABLE IF NOT EXISTS catalog_entries (
    kind VARCHAR NOT NULL,
    name VARCHAR NOT NULL,
    unit_type VARCHAR NOT NULL DEFAULT 'continuous',
    PRIMARY KEY (kind, name)
);

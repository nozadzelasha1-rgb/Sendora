CREATE SCHEMA IF NOT EXISTS dbo;

CREATE TABLE dbo.dictionary_spec (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    name text NOT NULL
);

CREATE TABLE dbo.dictionary (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    spec_id bigint NOT NULL REFERENCES dbo.dictionary_spec(id),
    name text NOT NULL,
    description text
);

CREATE TABLE dbo.organizations (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    name text NOT NULL,
    type bigint NOT NULL REFERENCES dbo.dictionary(id),
    contact text,
    phone varchar(20),
    delivery_fee_gel numeric(12,2),
    active boolean NOT NULL DEFAULT true
);

CREATE TABLE dbo.zones (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    name text NOT NULL,
    city text NOT NULL,
    boundary jsonb,
    manager_id uuid,
    assignment_rule bigint REFERENCES dbo.dictionary(id),
    status bigint NOT NULL REFERENCES dbo.dictionary(id)
);

CREATE TABLE dbo.users (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    name text NOT NULL UNIQUE,
    role bigint NOT NULL REFERENCES dbo.dictionary(id),
    organization_id uuid NOT NULL REFERENCES dbo.organizations(id),
    zone_id uuid REFERENCES dbo.zones(id),
    active boolean NOT NULL DEFAULT true,
    email varchar(255) UNIQUE,
    phone varchar(20) UNIQUE,
    password_hash text
);

ALTER TABLE dbo.zones
    ADD CONSTRAINT zones_manager_id_fkey FOREIGN KEY (manager_id) REFERENCES dbo.users(id);

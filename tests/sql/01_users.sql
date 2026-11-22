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
    delivery_fee_gel numeric(12,2),
    active boolean NOT NULL DEFAULT true
);

CREATE TABLE dbo.zones (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    name text NOT NULL,
    city text NOT NULL,
    boundary jsonb,
    assignment_rule bigint REFERENCES dbo.dictionary(id),
    status bigint NOT NULL REFERENCES dbo.dictionary(id)
);

CREATE TABLE dbo.users (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    name text NOT NULL UNIQUE,
    role bigint NOT NULL REFERENCES dbo.dictionary(id),
    active boolean NOT NULL DEFAULT true,
    email varchar(255) UNIQUE,
    phone varchar(20) UNIQUE,
    password_hash text
);

CREATE TABLE dbo.organizations_users (
    organization_id uuid NOT NULL REFERENCES dbo.organizations(id),
    user_id uuid NOT NULL REFERENCES dbo.users(id) ON DELETE CASCADE,
    PRIMARY KEY (organization_id, user_id)
);
CREATE INDEX organizations_users_user_id_idx ON dbo.organizations_users (user_id);

CREATE TABLE dbo.zones_users (
    zone_id uuid NOT NULL REFERENCES dbo.zones(id),
    user_id uuid NOT NULL REFERENCES dbo.users(id) ON DELETE CASCADE,
    PRIMARY KEY (zone_id, user_id)
);
CREATE INDEX zones_users_user_id_idx ON dbo.zones_users (user_id);

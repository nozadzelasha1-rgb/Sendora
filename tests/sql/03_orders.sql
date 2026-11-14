CREATE TABLE dbo.orders (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    tracking_number text NOT NULL UNIQUE,
    external_order_id text,
    partner_id uuid NOT NULL REFERENCES dbo.organizations(id),
    service_type bigint NOT NULL REFERENCES dbo.dictionary(id),
    zone_id uuid REFERENCES dbo.zones(id),
    courier_id uuid REFERENCES dbo.users(id),
    status bigint NOT NULL REFERENCES dbo.dictionary(id),
    tracking_url text,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    delivered_at timestamptz,
    UNIQUE (partner_id, external_order_id)
);

CREATE TABLE dbo.order_status_history (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    order_id bigint NOT NULL REFERENCES dbo.orders(id),
    status bigint NOT NULL REFERENCES dbo.dictionary(id),
    exception_reason bigint REFERENCES dbo.dictionary(id),
    next_action bigint REFERENCES dbo.dictionary(id),
    comment text,
    changed_by uuid REFERENCES dbo.users(id),
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE dbo.order_senders (
    order_id bigint PRIMARY KEY REFERENCES dbo.orders(id),
    sender_company text NOT NULL,
    sender_contact text NOT NULL,
    sender_phone varchar(20) NOT NULL,
    pickup_address text,
    sender_comment text
);

CREATE TABLE dbo.order_recipients (
    order_id bigint PRIMARY KEY REFERENCES dbo.orders(id),
    recipient_name text NOT NULL,
    recipient_phone varchar(20) NOT NULL,
    recipient_alt_phone varchar(20),
    delivery_address text NOT NULL,
    city text NOT NULL,
    entrance text,
    floor text,
    apartment text,
    door_code text,
    landmark text
);

CREATE TABLE dbo.order_parcels (
    order_id bigint PRIMARY KEY REFERENCES dbo.orders(id),
    parcel_type bigint NOT NULL REFERENCES dbo.dictionary(id),
    pieces_count smallint NOT NULL DEFAULT 1,
    weight_kg numeric(7,3),
    length_cm numeric(6,1),
    width_cm numeric(6,1),
    height_cm numeric(6,1),
    description text,
    fragile boolean NOT NULL DEFAULT false,
    declared_value_gel numeric(12,2)
);

CREATE TABLE dbo.order_schedules (
    order_id bigint PRIMARY KEY REFERENCES dbo.orders(id),
    pickup_date date,
    pickup_window varchar(11),
    requested_delivery_date date,
    delivery_window varchar(11)
);

CREATE TABLE dbo.order_payments (
    order_id bigint PRIMARY KEY REFERENCES dbo.orders(id),
    delivery_payer bigint NOT NULL REFERENCES dbo.dictionary(id),
    delivery_fee_gel numeric(12,2) NOT NULL,
    cod_enabled boolean NOT NULL DEFAULT false,
    cod_amount_gel numeric(12,2) NOT NULL DEFAULT 0,
    currency bigint NOT NULL REFERENCES dbo.dictionary(id),
    cod_method bigint REFERENCES dbo.dictionary(id)
);

CREATE TABLE dbo.order_operations (
    order_id bigint PRIMARY KEY REFERENCES dbo.orders(id),
    carrier_id varchar(32),
    manager_id uuid REFERENCES dbo.users(id),
    route_id varchar(32),
    latitude numeric(9,6),
    longitude numeric(9,6),
    internal_comment text
);

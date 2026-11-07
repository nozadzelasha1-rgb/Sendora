CREATE SCHEMA IF NOT EXISTS personal;

CREATE TABLE personal.users (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    username varchar(50),
    phone varchar(16),
    email varchar(255),
    password_hash text NOT NULL,
    birth_date date,
    is_active boolean DEFAULT true,
    created_at timestamptz,
    updated_at timestamptz,
    CONSTRAINT users_username_key UNIQUE (username),
    CONSTRAINT users_phone_key UNIQUE (phone),
    CONSTRAINT users_email_key UNIQUE (email)
);

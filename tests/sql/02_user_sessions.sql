CREATE TABLE dbo.user_sessions (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id uuid NOT NULL REFERENCES dbo.users(id) ON DELETE CASCADE,
    refresh_token_hash bytea NOT NULL UNIQUE CHECK (octet_length(refresh_token_hash) = 32),
    previous_token_hash bytea CHECK (previous_token_hash IS NULL OR octet_length(previous_token_hash) = 32),
    created_at timestamptz NOT NULL DEFAULT now(),
    rotated_at timestamptz,
    expires_at timestamptz NOT NULL,
    revoked_at timestamptz,
    revoked_reason varchar(20),
    CONSTRAINT user_sessions_revoked_reason_check CHECK (revoked_reason IS NULL OR revoked_reason IN ('logout','logout_all','reuse','manual','user_inactive'))
) WITH (fillfactor = 90);

CREATE INDEX user_sessions_user_id_idx ON dbo.user_sessions (user_id);

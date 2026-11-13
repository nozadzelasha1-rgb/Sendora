# Authentication guide

Short operator and frontend guide for JWT access tokens and refresh-token sessions.

## How it works

- **Access token**: short-lived JWT (`JWT_ACCESS_TOKEN_EXPIRE_MINUTES`), sent as `Authorization: Bearer <token>`. It is bound to a session id.
- **Refresh token**: opaque string `<session id>.<secret>`, valid for `JWT_REFRESH_TOKEN_EXPIRE_DAYS`. Only a SHA-256 hash of the secret is stored in `personal.user_sessions`.
- **Rotation**: every `/refresh` invalidates the presented refresh token and returns a new pair. A parallel refresh with the previous token within `REFRESH_TOKEN_REUSE_GRACE_SECONDS` gets 409 and must retry with the tokens from the first response; it does not log the user out.
- **Reuse detection**: presenting the previous (already rotated) token after the grace window revokes the session (`revoked_reason = 'reuse'`). A wrong or random secret for a known session id does not revoke anything, because the session id is not secret.
- Revoking a session (logout, logout-all, manual SQL) makes its access tokens stop working immediately.

## Flow for frontend developers

1. `POST /users/login` returns `access_token`, `refresh_token`, `expires_in` (seconds) and `user` in the body.
2. Keep the access token in memory. Store the refresh token as your security model allows.
3. Send `Authorization: Bearer <access_token>` on protected requests.
4. On a 401 caused by an expired access token, call `POST /users/refresh` with the refresh token, replace both tokens, and retry the original request once.
5. `POST /users/refresh` returning **409**: another refresh is in progress. Wait briefly and retry once.
6. Any other 401 (including a 401 from `/refresh`): the session is over, send the user to the login screen.
7. Logout: `POST /users/logout` with the refresh token (current device) or `POST /users/logout-all` with the Bearer token (all devices).

## Endpoints

All paths are under `API_PREFIX` (default `/v0`).

| Method | Path | Success | Errors |
|--------|------|---------|--------|
| POST | `/users` | 201 | 409 user exists, 422 |
| POST | `/users/login` | 200 (tokens + user) | 401 bad credentials, 422 |
| POST | `/users/refresh` | 200 (new tokens + user) | 401 invalid/expired/revoked, 409 parallel refresh (retry once), 422 bad shape |
| POST | `/users/logout` | 204 | 422 if `refresh_token` is missing or not a string |
| POST | `/users/logout-all` | 204 | 401 |
| GET | `/users/me` | 200 | 401 |
| POST | `/users/delete` | 204 | 401, 422 |

`/users/logout` accepts any string as `refresh_token` and always returns 204 for a well-formed JSON body, without revealing whether the token existed.

## Environment variables

| Variable | Notes |
|----------|-------|
| `ENVIRONMENT` | **Required**, no default. `development` or `production`. The app fails at startup if it is missing. |
| `JWT_SECRET_KEY` | Required outside development: at least 32 bytes and not the default value. |
| `JWT_ACCESS_TOKEN_EXPIRE_MINUTES` | Access token lifetime, positive integer (default 30). |
| `JWT_REFRESH_TOKEN_EXPIRE_DAYS` | Refresh token lifetime, positive integer (default 7). |
| `REFRESH_TOKEN_REUSE_GRACE_SECONDS` | Grace window for parallel refreshes, 0 or more (default 10). |
| `CORS_ORIGINS` | JSON list, for example `["https://app.example.com"]`. `"*"` is rejected when `ENVIRONMENT=production`. |

## Incident response (SQL)

Run manually; the application never runs DDL or these statements itself.

Revoke all sessions of one user by username:

```sql
UPDATE personal.user_sessions SET revoked_at = now(), revoked_reason = 'manual' WHERE user_id = (SELECT id FROM personal.users WHERE username = '<username>') AND revoked_at IS NULL;
```

Revoke all sessions of one user by user uuid:

```sql
UPDATE personal.user_sessions SET revoked_at = now(), revoked_reason = 'manual' WHERE user_id = '<user uuid>' AND revoked_at IS NULL;
```

Revoke everyone's sessions (all users must log in again):

```sql
UPDATE personal.user_sessions SET revoked_at = now(), revoked_reason = 'manual' WHERE revoked_at IS NULL;
```

To invalidate every token regardless of sessions (for example a leaked signing key), also rotate `JWT_SECRET_KEY` and restart.

## Cleanup (SQL)

Old rows are also purged per user on each login. Periodic global cleanup:

```sql
DELETE FROM personal.user_sessions WHERE expires_at < now() - interval '30 days' OR revoked_at < now() - interval '30 days';
```

## Known limits

- No rate limiting on login or refresh.
- Unlimited sessions per user.
- Redis is not installed; sessions live only in PostgreSQL.
- Access tokens issued before this feature carry no session id and stop working; users must log in again.

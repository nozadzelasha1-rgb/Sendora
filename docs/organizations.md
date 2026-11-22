# Organizations guide

Short guide to the organization endpoints. Every endpoint requires `Authorization: Bearer <access_token>` (see `docs/auth.md`); a missing or invalid token returns 401 with `WWW-Authenticate: Bearer`.

## Behaviour

- `DELETE` is a soft delete: it sets `active=false` and is idempotent for an existing organization.
- `GET /organizations` returns only active organizations by default; pass `active=false` to list inactive ones. Results are ordered by `name`, then `id`.
- `GET /organizations/{id}` returns the organization whether it is active or not.
- `PATCH` changes only the sent fields. An empty body is rejected, and `name`, `type` and `active` cannot be null. Send `active=true` to reactivate.
- `type` must be an existing `dbo.dictionary` id; otherwise the API returns 422 `Unknown organization type`.
- Every endpoint requires a token of role `super_admin` (id 28) or `admin_operator` (id 29). Other roles get 403 `Access denied`. A missing or invalid token still gets 401.
- Members: a user joins an organization with `POST .../users` (body `{"user_id": ...}`) and leaves it with `DELETE .../users/{user_id}`. Adding an unknown or inactive user returns 404 `User not found`; adding an existing member returns 409; removing a non-member returns 404.

## Endpoints

All paths are under `API_PREFIX` (default `/v0`).

| Method | Path | Success | Errors |
|--------|------|---------|--------|
| POST | `/organizations` | 201 | 401, 403, 422 validation or unknown type |
| GET | `/organizations` | 200 (list; `limit` 1..100 default 50, `offset` >= 0, `active` default true) | 401, 403, 422 |
| GET | `/organizations/{organization_id}` | 200 | 401, 403, 404, 422 |
| PATCH | `/organizations/{organization_id}` | 200 | 401, 403, 404, 422 validation, empty body or unknown type |
| DELETE | `/organizations/{organization_id}` | 204 | 401, 403, 404, 422 |
| POST | `/organizations/{organization_id}/users` | 201 (`{organization_id, user_id}`) | 401, 403, 404 organization or user, 409 already a member, 422 |
| DELETE | `/organizations/{organization_id}/users/{user_id}` | 204 | 401, 403, 404 not a member |

# Dictionaries guide

Short guide to the dictionary endpoints. Every endpoint requires `Authorization: Bearer <access_token>` (see `docs/auth.md`); a missing or invalid token returns 401 with `WWW-Authenticate: Bearer`.

Dictionaries live in `dbo.dictionary_spec` (named groups such as `order_status`, `user_role`) and `dbo.dictionary` (items of a spec: `id`, `spec_id`, `name`, `description`).

## Behaviour

- Any authenticated user may read specs and items. Writing needs a token of role `super_admin` (id 27) or `admin_operator` (id 28); other roles get 403 `Access denied`.
- Specs cannot be created, changed or deleted through the API. Their names are tied to the code.
- Items are addressed by `spec_id` and `item_id`. An item of another spec is reported as not found.
- `PATCH` changes only the sent fields. `name` cannot be null; `description` may be set to null, and an empty description is stored as null.
- `DELETE` is a hard delete. It returns 409 when other records still reference the item, and 409 for protected items the code depends on: the admin role ids 27 and 28 and the order status ids 1 (created), 9 (delivered) and 15 (cancelled).
- Item names are not unique within a spec: `order_status` may contain duplicate names; the code relies on the ids above, not on names.

## Endpoints

All paths are under `API_PREFIX` (default `/v0`).

| Method | Path | Success | Errors |
|--------|------|---------|--------|
| GET | `/dictionaries` | 200 list of `{id, name}` | 401 |
| GET | `/dictionaries/{spec_id}` | 200 list of items | 401, 404 spec not found |
| GET | `/dictionaries/{spec_id}/{item_id}` | 200 | 401, 404 spec or item not found |
| POST | `/dictionaries/{spec_id}` | 201 | 401, 403, 404 spec not found, 422 validation |
| PATCH | `/dictionaries/{spec_id}/{item_id}` | 200 | 401, 403, 404, 422 validation or empty body |
| DELETE | `/dictionaries/{spec_id}/{item_id}` | 204 | 401, 403, 404, 409 in use or protected |

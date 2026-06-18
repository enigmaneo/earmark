# Design: KOSync credentials at registration

> **Status:** implemented. This document captures the design and rationale; the behaviour it
> describes is live in the codebase.

## 1. Overview & goal

Today the earmark web account (`User`) and the KOReader sync account (`KosyncUser`) are created
through two unrelated flows, and they only get tied together opportunistically. This design makes
**registration the explicit point** where a `KosyncUser` is created and owned by an earmark `User`.

At `POST /auth/register` the user must also supply a **KOSync username** and **KOSync password**
(independent of their earmark email/password — they need not match). Registration then either:

- **creates** a new `KosyncUser` owned by the new earmark user, or
- **adopts** a matching pre-existing *unlinked* `KosyncUser` — which automatically carries its
  existing reading progress, because `ReadingProgress` rows are foreign-keyed to `kosync_user_id`
  (no progress rows need to move).

The KOSync username/password become the credentials the user later enters in KOReader.

## 2. Current state

| Concern | Where |
|---|---|
| `User`, `KosyncUser`, `ReadingProgress` models | [src/earmark/models.py](../src/earmark/models.py) |
| Earmark register (email + bcrypt) | [src/earmark/routers/auth.py](../src/earmark/routers/auth.py) `register` |
| KOSync account create (KOReader) | [src/earmark/routers/users.py](../src/earmark/routers/users.py) `POST /users/create` |
| KOSync header auth (`x-auth-user`/`x-auth-key`) | [src/earmark/auth.py](../src/earmark/auth.py) `get_current_user` |
| Opportunistic linking | [src/earmark/services/progress.py](../src/earmark/services/progress.py) `write_reading_progress`, `link_progress_to_mapping` |

Key facts the design relies on:

- `KosyncUser.user_id` is a **nullable** FK to `users.id` — a KosyncUser can exist unlinked.
- `ReadingProgress.kosync_user_id` FKs the `KosyncUser`, so re-owning a KosyncUser re-owns all of
  its progress.
- Linking is currently only triggered when progress is written for a document that has an
  ABS↔ebook mapping owned by some earmark user (in `services/progress.py`). A web registrant whose
  books are never mapped never gets linked. That gap is what this change closes.

## 3. Decisions

These were confirmed before writing this design.

### Adopt-if-password-matches

When the supplied KOSync username already exists:

| Existing KosyncUser state | Supplied password (MD5) vs stored hash | Result |
|---|---|---|
| unlinked (`user_id is None`) | matches | **Adopt** — set `user_id = new user.id`; its progress is now owned by the new earmark user |
| unlinked (`user_id is None`) | does not match | **Reject** registration → `409` |
| already linked (`user_id` set) | — | **Reject** registration → `409` |
| does not exist | — | **Create** a new `KosyncUser` owned by the new earmark user |

Rejection fails the **entire** registration (atomic) — the earmark `User` is not created either,
so the user can retry with a different KOSync username/password.

### Keep `POST /users/create`

The standalone KOReader self-registration endpoint stays unchanged. KOReader can still create an
unlinked `KosyncUser`; a later earmark registration adopts it via the rule above. This preserves
the legacy/migration path and KOReader's in-app "Register".

### No database migration

Because `KosyncUser.user_id` is already nullable and progress is already keyed by
`kosync_user_id`, adoption requires **no schema change**. This change is logic + schema (Pydantic)
+ UI + docs only.

## 4. Password handling

The two creation paths intentionally differ, mirroring the KOSync protocol (KOReader hashes
passwords client-side and never sends plaintext after registration — see
[docs/KosyncApi.md](KosyncApi.md)):

- **`POST /users/create` (KOReader):** the client sends `MD5(password)`; the server stores it
  verbatim and later compares it constant-time against the `x-auth-key` header.
- **`POST /auth/register` (web form):** the user types a **plaintext** KOSync password; the
  **server** MD5-hashes it before storing/comparing, so the stored value matches the `x-auth-key`
  KOReader will send later.

To avoid duplicating `hashlib.md5(...)`, add a shared helper
`kosync_hash(password: str) -> str` to [src/earmark/earmark_auth.py](../src/earmark/earmark_auth.py)
and have `seed.py` (which currently defines its own `md5()`) reuse it.

## 5. Proposed changes (implementation outline)

### Schema — [src/earmark/schemas.py](../src/earmark/schemas.py)
Add a registration-specific model; keep `UserCreate` for `/auth/login` (still email + password
only):

```python
class UserRegister(BaseModel):
    email: EmailStr
    password: str
    kosync_username: str
    kosync_password: str
```

### Endpoint — [src/earmark/routers/auth.py](../src/earmark/routers/auth.py)
Change `register` to accept `UserRegister` and validate **everything before persisting** (one
atomic transaction):

1. Reject if `email` already registered (existing check).
2. Look up `KosyncUser` by `kosync_username` and apply the decision table in §3 (use
   `secrets.compare_digest(existing.password_hash, kosync_hash(kosync_password))` for the match —
   `secrets` is already used in [auth.py](../src/earmark/auth.py)).
3. Create the earmark `User` with `hash_password(...)`; `flush()` to get `user.id`.
4. Adopt (`existing.user_id = user.id`) or create
   `KosyncUser(username=..., password_hash=kosync_hash(kosync_password), user_id=user.id)`.
5. `commit`, `refresh`, return `UserRead`.

Keep the `10/minute` rate limit. Response stays `UserRead` (no KOSync field needed in it).

### Frontend
- [src/frontend/src/routes/register/+page.svelte](../src/frontend/src/routes/register/+page.svelte) —
  add **KOSync username** and **KOSync password** inputs, with a short hint that these are the
  credentials to enter in KOReader and need not match the earmark email/password.
- [src/frontend/src/routes/register/+page.server.ts](../src/frontend/src/routes/register/+page.server.ts) —
  read and validate the two new fields and include `kosync_username` / `kosync_password`
  (plaintext) in the `POST /auth/register` body. The login flow is unchanged; surface the backend
  `409` `detail` through the existing error path.

### Bruno — `testing/bruno/`
- `auth/register.bru` — add `kosync_username` and `kosync_password` (plaintext) to the JSON body.
- Bruno environment — add a plaintext `kosync_password` var; keep the existing `password_hash`
  (which must equal `md5(kosync_password)`) used by `users/auth.bru`'s `x-auth-key`.
- `users/create-user.bru` and `users/auth.bru` stay as-is (KOReader protocol path).

### Tests — `tests/`
- Register creates a new linked `KosyncUser`; KOReader-style auth then works with the same
  username + `x-auth-key = md5(plaintext password)`.
- Register **adopts** a pre-existing unlinked `KosyncUser` on password match, and its prior
  `ReadingProgress` is reachable via the new earmark user (`user.kosync_users[...].progress`).
- Register **rejects** (`409`) on password mismatch and when the username is already linked to
  another earmark user — and the earmark `User` is **not** created in either case (atomic
  rollback).

Reuse the `md5` / `alice` fixture patterns in `tests/conftest.py`.

### Docs to update when implemented
- [docs/KosyncApi.md](KosyncApi.md) — document the new `/auth/register` body, the
  adopt-if-password-matches rule, and the plaintext-vs-MD5 distinction between `/auth/register`
  and `/users/create`.
- The **User Model** section of [CLAUDE.md](../CLAUDE.md) — note that registration now requires
  KOSync credentials and is the primary way a `KosyncUser` is tied to a `User` (the
  mapping-based linking in `services/progress.py` remains as a fallback for legacy/standalone
  KosyncUsers).

## 6. Out of scope

- Earmark users created **before** this change are unaffected; they keep attaching KOSync accounts
  via `/users/create` (or a future settings page).
- One earmark `User` can still own multiple `KosyncUser`s (relationship unchanged); registration
  simply creates/links the first one.

## 7. Verification (when implemented)

1. Backend: `uv run pytest`, `uv run ruff check .`, `uv run mypy src/earmark`.
2. Manual end-to-end (`uv run fastapi dev ...` + `cd src/frontend && npm run dev`):
   - Register with email + new KOSync username/password → a linked `KosyncUser` exists and a
     KOReader-style `GET /users/auth` succeeds with `x-auth-user=<kosync_username>`,
     `x-auth-key=md5(<kosync_password>)`.
   - Pre-create an unlinked `KosyncUser` via `POST /users/create`, write progress for it, then
     register an earmark user with the same username + matching password → the prior progress is
     now owned by the new user; registering with a wrong password → `409` and no user created.
3. Run the updated Bruno `auth/register` request and confirm the follow-on `users/auth` request
   still authorizes.

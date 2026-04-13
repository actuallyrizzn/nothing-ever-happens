# Admin & authentication

The dashboard can run **without** login (local dev) or with **SQLite-backed admin users**, bcrypt passwords, CSRF tokens, and signed session cookies.

## Signing in {: #signing-in }

When `DASHBOARD_AUTH_SECRET` (≥ 32 characters) is set, the app requires a successful **`POST /login`** before **`/`**, **`/ws`**, **`/admin/*`**, etc.

- **Session cookie** — `neh_session`, HttpOnly, `SameSite=Lax`, **`Secure`** when the request is HTTPS or `X-Forwarded-Proto: https` (reverse proxy).  
- **Login CSRF** — short-lived cookie + hidden field on the login form.

Use **HTTPS** in production so session cookies are not sent in clear over the internet.

## Admin users {: #admin-users }

**Admin → Users** (`/admin/users`):

- Create additional operators (username + password, min length 8).  
- Delete users (cannot delete yourself; cannot delete the last user).

Bootstrap option on first deploy: `DASHBOARD_BOOTSTRAP_USERNAME` / `DASHBOARD_BOOTSTRAP_PASSWORD` or `scripts/dashboard_create_user.py`.

## Change password {: #change-password }

**Admin → Change password** requires the **current** password and matching **new** password fields.

## Runtime settings access {: #settings-access }

**Admin → Settings** reads/writes the **`runtime_settings`** table. Anyone with a valid dashboard session can change trading configuration — protect network access accordingly.

## Documentation (no login) {: #public-help }

**`/help`** and **`/help/...`** are intentionally **public** (no session) so operators can read documentation from the login page or a phone without credentials.

## Related docs

- [Configuration overview — bootstrap env](configuration-overview.md#bootstrap-env)  
- [Runtime settings](runtime-settings.md)

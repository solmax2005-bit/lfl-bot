# Security hardening

Summary of the security model after the 2026-06-27 audit (3 independent
auditors). SQL is fully parameterized, Telegram `initData` HMAC is verified
server-side, and the lfl.ru/afl.ru/f-league.ru parsers are restricted by
anchored regexes (no SSRF).

## Required production environment

Set these in `/opt/lfl-bot/.env` (see `.env.example` for the full list):

| Var | Why |
|-----|-----|
| `ADMIN_SECRET_KEY` | Flask session signing key. No default — without it sessions reset each restart. `python -c "import secrets; print(secrets.token_hex(32))"` |
| `ADMIN_PASSWORD_HASH` *(preferred)* | werkzeug hash. `python -c "from werkzeug.security import generate_password_hash as g; print(g('PASS'))"` |
| `ADMIN_PASSWORD` *(fallback)* | plaintext, compared in constant time. Used only if no hash. If neither is set, admin login is disabled. |
| `CORS_ORIGINS` | allowed Mini App origin(s), default `https://lflagent.ru`. |
| `CF_WORKER_SECRET` | Cloudflare Worker proxy secret (was hardcoded; now env-only). |
| `ADMIN_HTTPS=1` | enable `Secure` cookie when the panel is behind HTTPS. |
| `MSG_RETENTION_DAYS` | logged messages older than this are purged on bot startup (default 30). |

**Rotate** the bot token (@BotFather) and the proxy secret — both appeared in
the audit / earlier source.

## Controls in code

- **Auth:** Mini App write/personal-read endpoints require a verified
  `initData` HMAC; `tg_id` comes from the signature, never the query string.
- **Rate limiting:** in-app middleware in `api.py` — 120 POST/min/IP, 10/min for
  `/photo`, plus a 12 MB body cap. The bot also limits 10 msg/10 s/user.
- **CORS:** restricted to `CORS_ORIGINS`.
- **Headers:** `X-Content-Type-Options: nosniff`, `Referrer-Policy`, and a CSP
  `frame-ancestors` that only lets Telegram clients frame the Mini App.
- **XSS:** all user data is HTML-escaped on the client (`esc()`, incl. single
  quotes); URLs are escaped in `href`; team contacts are sanitized server-side.
- **Photos:** stored under an unguessable random filename (not `/<tg_id>.jpg`).
- **Admin:** no default password/secret, constant-time compare, 5-attempt
  lockout, `HttpOnly`/`SameSite` cookies, 8 h session, binds `127.0.0.1`.

## Recommended: edge rate limiting (defense in depth)

The in-app limiter is per-process and resets on restart. For a persistent limit
in front of the app, add one at the Caddy reverse proxy. With the
[`caddy-ratelimit`](https://github.com/mholt/caddy-ratelimit) plugin:

```caddyfile
lflagent.ru {
    rate_limit {
        zone api {
            match { path /api/* }
            key    {remote_host}
            events 120
            window 1m
        }
    }
    reverse_proxy 127.0.0.1:8000
}
```

For a stricter, shared limit across instances, back the limiter with Redis.

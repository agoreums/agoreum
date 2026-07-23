# infra/nginx

Reverse proxy configuration for the production droplet.

## Files

| File | Purpose |
|---|---|
| `nginx.conf` | Base configuration: workers, timeouts, gzip, JSON access log, rate-limit zones |
| `agoreum.conf` | Site routing, TLS, per-location limits and caching |
| `proxy_headers.conf` | Headers forwarded to every upstream |
| `certs/` | Cloudflare Origin certificate and key — **never committed** |

## Certificates

TLS terminates twice: once at Cloudflare's edge, and again here. Traffic between
the edge and the droplet is therefore encrypted rather than travelling in clear
inside the datacentre.

Generate a Cloudflare Origin certificate for `agoreum.xyz` and `*.agoreum.xyz`
in the Cloudflare dashboard (SSL/TLS → Origin Server), then place it on the
droplet:

```bash
mkdir -p infra/nginx/certs
# paste the certificate and key
vi infra/nginx/certs/origin.pem
vi infra/nginx/certs/origin.key
chmod 600 infra/nginx/certs/origin.key
```

Set the Cloudflare SSL mode to **Full (strict)**. Anything less lets the edge
accept an invalid origin certificate, which defeats the point of having one.

`certs/` is gitignored. A private key in version control is compromised the
moment the repository is cloned.

## Rate limiting

Two layers, deliberately:

- **Nginx** limits per IP address. It is cheap, runs before any application
  code, and absorbs volumetric abuse.
- **The API** limits per identity — user id when authenticated, IP otherwise.
  It understands who is calling, so one abusive account behind a shared NAT
  cannot exhaust everyone else's allowance.

Neither replaces the other. The edge limit stops floods; the application limit
stops a single authenticated actor.

## Verifying a change

```bash
docker compose -f docker-compose.prod.yml exec nginx nginx -t
docker compose -f docker-compose.prod.yml exec nginx nginx -s reload
```

`nginx -t` parses the configuration without applying it. Reloading without
testing first can leave the proxy down.

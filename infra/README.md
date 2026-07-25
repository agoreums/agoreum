# infra — Agoreum Infrastructure

Deployment configuration for the containerised production stack: the Nginx reverse
proxy (`infra/nginx/`) and the production Docker Compose file at the repository
root. The origin sits behind a CDN/edge providing DNS, TLS, caching, and a web
application firewall.

See [docs/deployment.md](../docs/deployment.md) for how it fits together and how to
run it.

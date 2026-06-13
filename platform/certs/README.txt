TLS Certificate Notes
=====================

Ascent Terminal uses Caddy as its reverse proxy, which automatically
obtains and renews TLS certificates from Let's Encrypt via the ACME
HTTP-01 challenge.

You do NOT need to manage certificates manually in most cases.

--------------------------------------------------------------------------
Automatic (default)
--------------------------------------------------------------------------

  - Set DOMAIN=yourdomain.com in .env
  - Make sure port 80 and 443 are open on the VPS
  - Ensure an A record points to the VPS public IP
  - Start the stack: docker compose up -d
  - Caddy will obtain the certificate on first startup

--------------------------------------------------------------------------
Cloudflare proxied domains (orange-cloud)
--------------------------------------------------------------------------

If your domain is proxied through Cloudflare (orange cloud icon), the
HTTP-01 ACME challenge will not work because Cloudflare intercepts port
80 traffic.

Options:

  1. Use Caddyfile.cloudflare with the DNS-01 challenge plugin.
     See platform/Caddyfile.cloudflare for full instructions.

  2. Temporarily disable Cloudflare proxying (grey-cloud), let Caddy
     obtain the certificate, then re-enable proxying.

  3. Use Cloudflare's origin certificate (not Let's Encrypt) and mount
     it manually into the Caddy container.

--------------------------------------------------------------------------
Manual certificate (bring your own)
--------------------------------------------------------------------------

If you have certificates from another CA, mount them into the Caddy
container and reference them in the Caddyfile:

  ascentterminal.com {
      tls /certs/fullchain.pem /certs/privkey.pem
      reverse_proxy app:8000
  }

Add to docker-compose.yml under the caddy service:

  volumes:
    - ./certs:/certs:ro
    - ./Caddyfile:/etc/caddy/Caddyfile:ro
    ...

--------------------------------------------------------------------------
Certificate storage
--------------------------------------------------------------------------

Caddy stores its certificate cache in the named Docker volume `caddy_data`.
This volume is preserved across container restarts and rebuilds, so
certificates are not re-requested unnecessarily.

To inspect stored certificates:

  docker compose exec caddy caddy trust
  docker compose exec caddy ls /data/caddy/certificates/

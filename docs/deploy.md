# Putting the portal on entrylib.org

The whole portal runs on one DigitalOcean Droplet behind Cloudflare (design §13). This is the order of the work; each
step says who does it and what it needs. Nothing here is ever committed: secrets go only into `.env` and the key file
on the server.

## 0. Before you start

You need:

- **The OpenAlex API key** (the classifier's): the same value as the `OPENALEX_API_KEY` repository secret, or a new
  free key from openalex.org/settings/api.
- **The EntryLib GitHub App's ID and private key** (`.pem` file): from the App's settings page on GitHub
  (Settings → Developer settings → GitHub Apps → EntryLib). The App must be installed on `entrylib/registry`.
- **An SSH key** on your computer, added to DigitalOcean (Settings → Security → SSH keys).

## 1. Cloudflare takes over the domain's DNS

1. In Cloudflare, add a site: `entrylib.org`, the Free plan.
2. Cloudflare shows two nameservers. At the registrar where `entrylib.org` is registered, replace its nameservers with
   these two. (Or transfer the domain to Cloudflare Registrar, so the domain and its DNS are in one place.)
3. Wait until Cloudflare marks the site **Active** (minutes to a day).
4. SSL/TLS → Overview: set the encryption mode to **Full (strict)**.
5. SSL/TLS → Edge Certificates: leave **Always Use HTTPS** off. Caddy redirects to HTTPS itself, and it needs plain
   HTTP to reach it to renew its certificate.

## 2. Create the Droplet

In DigitalOcean, Create → Droplets:

- Region **London**; image **Ubuntu 24.04 (LTS) x64**.
- Size: Basic, Regular, **4 GB / 2 CPUs** (or more).
- Authentication: your **SSH key**.
- **Backups: on, Daily.**
- Advanced options → **Add initialization scripts (user data)**: paste the whole of `deploy/cloud-init.yaml`.
- Hostname: `entrylib`.

Note the Droplet's **IPv4 address**. Setup runs by itself for a few minutes after the Droplet starts: it installs
Docker, a firewall, swap and automatic security updates, fetches the portal into `/opt/entrylib/portal`, and writes
`/opt/entrylib/portal/.env` with a generated database password. It does not start the portal.

## 3. Point the domain at the Droplet

In Cloudflare → DNS → Records, add:

| Type | Name | Content | Proxy status |
|---|---|---|---|
| A | `entrylib.org` (`@`) | the Droplet's IPv4 address | **DNS only** (grey cloud), for now |

It stays DNS only until Caddy has its certificate (step 6), then is switched to proxied.

## 4. Register the production ORCID client

Signed in to orcid.org with your own iD: your name → **Developer tools** → register for the free public API.

- Name: `EntryLib`; website: `https://entrylib.org`; description: one sentence on consent for publishing claimsets.
- Redirect URI: `https://entrylib.org/consent/callback`, exactly.

Note the **Client ID** (`APP-…`) and **Client secret**.

## 5. Fill in the settings on the server

From your computer:

```
ssh root@<droplet IP>
tail -f /var/log/cloud-init-output.log      # wait for "entrylib setup: done", then Ctrl-C
nano /opt/entrylib/portal/.env
```

Fill in the empty values: `OPENALEX_API_KEY`, `ORCID_CLIENT_ID`, `ORCID_CLIENT_SECRET`, `GITHUB_APP_ID`. Leave the rest
as written. Save (Ctrl-O, Enter) and exit (Ctrl-X).

Then copy the GitHub App key from your computer (a second terminal, not the SSH session):

```
scp <path to the App's .pem file> root@<droplet IP>:/opt/entrylib/secrets/github-app.pem
```

## 6. Start the portal

On the server:

```
/opt/entrylib/portal/deploy/launch.sh
```

It refuses to start while a setting is missing, and says which. The first start builds the images (several minutes)
and Caddy gets the certificate for entrylib.org. When it says the portal is running, open `https://entrylib.org/healthz`
(it shows the portal, claimset and spec versions and `"database": "ok"`) and `https://entrylib.org/llms.txt`.

Then, in Cloudflare → DNS, switch the `entrylib.org` record to **Proxied** (orange cloud), and check both pages again.

## 7. Check publishing end to end

Submit a test claimset, confirm it with your ORCID iD, and see the registry pull request open, pass its checks, merge,
and the claimset appear at `https://entrylib.org/p/<year>.<number>.txt`. Published claimsets are never withdrawn, so use a
real paper you want published, or skip this until you have one.

## Running it

- **Updates to the portal:** `/opt/entrylib/portal/deploy/launch.sh --update` (fetches the newest code, rebuilds,
  restarts).
- **Claimset updates** need nothing: the app restarts daily at 04:17 UTC and installs the newest claimset (design §10).
- **Logs:** `cd /opt/entrylib/portal && docker compose logs --tail 100 app` (or `caddy`, `db`, `classifier`).
- **Backups:** DigitalOcean's daily Droplet backups hold everything on the Droplet. To restore, create a Droplet from a
  backup image and point the DNS record at it. The published record is also on GitHub (`entrylib/registry`), from
  which `docker compose exec app portal reindex` rebuilds the database.
- **Cloudflare's address ranges** are in `deploy/Caddyfile`; update them if Cloudflare publishes new ones
  (cloudflare.com/ips).

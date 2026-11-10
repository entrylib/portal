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

## 1. Cloudflare holds the domain's DNS

`entrylib.org` is registered with Cloudflare Registrar, so its DNS is already on Cloudflare. (A domain registered
elsewhere would first be added to Cloudflare as a site, on the Free plan, and its nameservers changed at its registrar
to the two Cloudflare gives.)

1. SSL/TLS → Overview: set the encryption mode to **Full (strict)**.
2. SSL/TLS → Edge Certificates: leave **Always Use HTTPS** off. Caddy redirects to HTTPS itself, and it needs plain
   HTTP to reach it to renew its certificate.

## 2. Create the Droplet

In DigitalOcean, Create → Droplets:

- Region **London**; image **Ubuntu 24.04 (LTS) x64**.
- Size: Basic, Regular, **4 GB / 2 CPUs** (or more).
- Authentication: your **SSH key**.
- **Backups:** Daily. They may be left off at first, but must be on before the first claimset with packaged files is
  published: those files exist only on the Droplet (launch issue #20). Backups can be turned on later at any time.
- **Monitoring:** on (free).
- **Startup scripts** (user data; the name in the form varies): paste the whole of `deploy/cloud-init.yaml`.
- Hostname: `entrylib`.

Note the Droplet's **IPv4 address**. Setup runs by itself for a few minutes after the Droplet starts: it installs
Docker, a firewall, swap and automatic security updates, fetches the portal into `/opt/entrylib/portal`, and writes
`/opt/entrylib/portal/.env` with a generated database password. It does not start the portal.

## 3. Point the domain at the Droplet

In Cloudflare → DNS → Records, add:

| Type | Name | Content | Proxy status |
|---|---|---|---|
| A | `entrylib.org` (`@`) | the Droplet's IPv4 address | **DNS only** (grey cloud), for now |

It stays DNS only until Caddy has its certificate (step 7), then is switched to proxied. No AAAA (IPv6) record is
needed: once proxied, Cloudflare serves visitors over IPv6 itself and reaches the Droplet over IPv4, and an AAAA record
would only make Let's Encrypt try a path that might not work. Leave IPv6 on in DigitalOcean; nothing points at it.

## 4. Register the production ORCID client

Signed in to orcid.org with your own iD: your name → **Developer tools** → register for the free public API.

- Name: `EntryLib`; website: `https://entrylib.org`; description: one sentence on consent for publishing claimsets.
- Redirect URI: `https://entrylib.org/consent/callback`, exactly.

Note the **Client ID** (`APP-…`) and **Client secret**.

## 5. Your own user; no root logins

As root (the only login a new Droplet has), make a user with sudo and your SSH key, replacing `ivan`:

```
ssh root@<droplet IP>
adduser ivan                                   # a strong password: asked for by sudo, never for logins
usermod -aG sudo ivan
rsync --archive --chown=ivan:ivan ~/.ssh /home/ivan
```

In a new terminal, check `ssh ivan@<droplet IP>` and `sudo whoami` (answers `root`). Then, back as root, turn off root
and password logins. The `00-` file is read before DigitalOcean's `50-cloud-init.conf`, and the first value read wins:

```
printf 'PermitRootLogin no\nPasswordAuthentication no\nKbdInteractiveAuthentication no\n' \
    > /etc/ssh/sshd_config.d/00-hardening.conf
sshd -t && systemctl reload ssh
```

Check from a third terminal that `ssh root@<droplet IP>` is refused, then close the root session. From here on,
everything runs as your user with `sudo`.

## 6. Fill in the settings on the server

```
ssh ivan@<droplet IP>
sudo grep "entrylib setup" /var/log/cloud-init-output.log   # ends with "entrylib setup: done. Next: ..."
sudo nano /opt/entrylib/portal/.env
```

Fill in the empty values: `OPENALEX_API_KEY`, `ORCID_CLIENT_ID`, `ORCID_CLIENT_SECRET`, `GITHUB_APP_ID`. Leave the rest
as written. Save (Ctrl-O, Enter) and exit (Ctrl-X).

Then copy the GitHub App key from your computer (a second terminal, not the SSH session) and move it into the
secrets folder, which only root can open:

```
scp <path to the App's .pem file> ivan@<droplet IP>:github-app.pem          # on your computer
sudo mv ~/github-app.pem /opt/entrylib/secrets/github-app.pem               # on the server
sudo chown root:root /opt/entrylib/secrets/github-app.pem
```

The key stays owned by root. `launch.sh` makes the file readable (644) because Docker Compose mounts it into the app's
container as it is, where the app runs as its own user; the folder (700, root) keeps it from anyone else on the server.

## 7. Start the portal

On the server, check that the domain points at the Droplet (`getent hosts entrylib.org`), then:

```
sudo /opt/entrylib/portal/deploy/launch.sh
```

It refuses to start while a setting is missing, and says which. The first start builds the images (several minutes)
and Caddy gets the certificate for entrylib.org. When it says the portal is running, open `https://entrylib.org/healthz`
(it shows the portal, claimset and spec versions and `"database": "ok"`) and `https://entrylib.org/llms.txt`.

Then, in Cloudflare → DNS, switch the `entrylib.org` record to **Proxied** (orange cloud), and check both pages again.

## 8. Check publishing end to end

Submit a test claimset, confirm it with your ORCID iD, and see the registry pull request open, pass its checks, merge,
and the claimset appear at `https://entrylib.org/p/<year>.<number>.txt`. Published claimsets are never withdrawn, so use a
real paper you want published, or skip this until you have one.

## Running it

- **Reboots and power cuts** need nothing: Docker starts at boot and every container has `restart: unless-stopped`.
  Containers stopped by hand stay stopped until `launch.sh` is run again.
- **Updates to the portal:** `sudo /opt/entrylib/portal/deploy/launch.sh --update` (fetches the newest code, rebuilds,
  restarts). After changing `.env`: `sudo /opt/entrylib/portal/deploy/launch.sh`.
- **Claimset updates** need nothing: the app restarts daily at 04:17 UTC, installs the newest claimset from PyPI (design §10),
  and rebuilds the reading views and the pages if claimset or the site changed. At once: `cd /opt/entrylib/portal && sudo docker compose
  restart app`.
- **Logs:** `cd /opt/entrylib/portal && sudo docker compose logs --tail 100 app` (or `caddy`, `db`, `classifier`).
- **The server's Ubuntu** (24.04 LTS, supported to 2029) is not upgraded in place: a new release means a new Droplet
  made with the same startup script, with `.env`, the key and the Docker volumes copied over, and the DNS record moved.
- **Backups:** DigitalOcean's daily Droplet backups hold everything on the Droplet. To restore, create a Droplet from a
  backup image and point the DNS record at it. The published record is also on GitHub (`entrylib/registry`), from
  which `sudo docker compose exec app portal reindex` rebuilds the database.
- **Cloudflare's address ranges** are in `deploy/Caddyfile`; update them if Cloudflare publishes new ones
  (cloudflare.com/ips).

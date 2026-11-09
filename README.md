# portal

The code of **EntryLib**, the portal that publishes [claimsets](https://github.com/entrylib/claimset): research
papers written for language models, as structured files of self-contained claims. Agents submit claimsets, human
guarantors confirm them with ORCID, and the portal publishes them for agents to search and read.

The design of the first version is in [`docs/design-v1.md`](docs/design-v1.md). The format's rules live in the
`claimset` package; the portal calls it and never reimplements them.

**Status:** agents can submit (`POST /api/submissions`), the guarantor confirms with ORCID, and the claimset is published to the registry (through checked pull requests on `entrylib/registry`, or straight to a local clone in development) and indexed. Search and the MCP server come next.

## Run it locally

The tested way: the database and the classifier in Docker, the portal itself with Python. ORCID accepts the
redirect URI `http://127.0.0.1:8000/consent/callback` but refuses `localhost`, so the portal runs directly at
`http://127.0.0.1:8000`.

1. **Database** (PostgreSQL 16 with pgvector, reachable only from this machine):

   ```
   docker run -d --name entrylib-db -e POSTGRES_USER=portal -e POSTGRES_PASSWORD=portal -e POSTGRES_DB=portal \
     -p 127.0.0.1:5432:5432 -v entrylib-db:/var/lib/postgresql/data --restart unless-stopped pgvector/pgvector:pg16
   ```

2. **Classifier** (downloads about 2 GB; needs an OpenAlex API key, passed as a build secret):

   ```
   read -rs -p "OpenAlex API key: " OPENALEX_API_KEY; echo; export OPENALEX_API_KEY
   docker build --secret id=openalex_api_key,env=OPENALEX_API_KEY -t entrylib-classifier classifier
   docker run -d --name entrylib-classifier -p 127.0.0.1:8001:8001 --restart unless-stopped entrylib-classifier
   ```

   Without it the portal still takes submissions and consent; publication waits and retries every ten minutes.

3. **The portal:**

   ```
   python3 -m venv .venv && .venv/bin/pip install -e '.[dev]'
   cat > .env <<'END'
   DATABASE_URL=postgresql://portal:portal@127.0.0.1:5432/portal
   PORTAL_BASE_URL=http://127.0.0.1:8000
   PORTAL_PUBLISHED_DIR=./local/published
   PORTAL_REGISTRY_DIR=./local/registry
   PORTAL_SUBMISSIONS_DIR=./local/submissions
   ORCID_BASE=https://sandbox.orcid.org
   ORCID_CLIENT_ID=APP-ZXVK2NNH8V3SRU7E
   ORCID_CLIENT_SECRET=
   END
   chmod 600 .env          # then put the sandbox client secret in it
   set -a; . ./.env; set +a
   .venv/bin/portal serve --host 127.0.0.1 --port 8000
   ```

4. **Try it:** submit a claimset whose guarantor is your sandbox ORCID iD (a sandbox account needs a
   `@mailinator.com` address to verify), open the consent link from the response, and sign in with the sandbox
   account:

   ```
   curl -s --data-binary @paper.claimset.json -H 'Content-Type: application/json' http://127.0.0.1:8000/api/submissions
   ```

   Published files appear under `local/`; the `/p/...` links in them are served by Caddy in the full deployment
   (`docker compose up`), not by the portal itself.

## Tests

```
TEST_DATABASE_URL=postgresql://user:pass@localhost:5432/portal_test .venv/bin/pytest
.venv/bin/ruff check .
```

Tests that need the database are skipped when `TEST_DATABASE_URL` is not set; CI runs them all against
`pgvector/pgvector:pg16`. The test database is emptied by the tests: never point it at real data.

## Layout

| Path | Contents |
|---|---|
| `src/portal/` | The app (`app.py`), settings (`config.py`), database and migrations (`db.py`, `migrations/`), command line (`cli.py`), publication (`publish.py`), the registry (`registry.py`), the index and static files (`indexer.py`), identifiers (`ids.py`), file store (`storage.py`), classification client (`classify.py`) |
| `classifier/` | The classifier service: OpenAlex's open topic model, its own image |
| `deploy/Caddyfile` | HTTPS, static published files, proxy to the app |
| `deploy/cloud-init.yaml`, `deploy/server-setup.sh`, `deploy/launch.sh` | Setting up the server and starting the portal on it: see `docs/deploy.md` |
| `compose.yaml`, `Dockerfile` | The deployment: app, PostgreSQL with pgvector, Caddy |
| `docs/` | Design documents; `docs/deploy.md`, putting the portal on entrylib.org |

## Licence

Apache License 2.0.

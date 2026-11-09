"""The web application: one FastAPI app serving the API, consent pages, the upload page, the search API and the MCP
server (/mcp).

Published files (`/p/...`, `/index.jsonl`, `/llms.txt`, `/files/...`) are static and served by Caddy from the
published directory; the app does not serve them in production.
"""

import asyncio
import contextlib
import ipaddress
import logging
import tempfile
from contextlib import asynccontextmanager
from importlib import resources
from pathlib import Path

import claimset
from fastapi import Body, FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from starlette.concurrency import run_in_threadpool

from . import __version__, consent, fetch, mcp_server, pages, search, submissions, worker
from .config import Settings
from .db import make_pool
from .orcid import OrcidClient, OrcidError

log = logging.getLogger("portal")

#: How often pending submissions past their consent window are deleted.
EXPIRY_INTERVAL_SECONDS = 600

#: The upload page runs only its own script and sends only to this site; nothing submitted is rendered.
UPLOAD_PAGE_CSP = ("default-src 'none'; script-src 'self'; style-src 'unsafe-inline'; connect-src 'self'; "
                   "form-action 'none'; frame-ancestors 'none'; base-uri 'none'")


class UploadTooLarge(Exception):
    pass


async def _save_body(request, directory):
    """Stream the request body to a temporary file, refusing more than MAX_UPLOAD_BYTES."""
    directory.mkdir(parents=True, exist_ok=True)
    fh = tempfile.NamedTemporaryFile(dir=directory, prefix="upload-", delete=False)
    size = 0
    try:
        async for chunk in request.stream():
            size += len(chunk)
            if size > submissions.MAX_UPLOAD_BYTES:
                raise UploadTooLarge
            fh.write(chunk)
    except BaseException:
        fh.close()
        Path(fh.name).unlink(missing_ok=True)
        raise
    fh.close()
    return Path(fh.name), size


def _client_ip(request):
    host = request.client.host if request.client else None
    try:
        return str(ipaddress.ip_address(host)) if host else None
    except ValueError:                                      # not an address (the test client): no per-address cap
        return None


def _static(name):
    return (resources.files("portal") / "static" / name).read_text(encoding="utf-8")


def _error(status, message, errors=(), warnings=()):
    return JSONResponse({"error": message, "errors": list(errors), "warnings": list(warnings)}, status_code=status)


def _publisher(settings):
    """What publication uses: {registry, store, classifier}, and in github mode {remote, archive} (design §5)."""
    from .classify import HttpClassifier
    from .registry import Registry
    from .storage import FileStore
    out = {"store": FileStore(settings.published_dir, settings.base_url),
           "classifier": HttpClassifier(settings.classifier_url)}
    if settings.registry_mode == "github":
        from .github import GitHubApp, RemoteRegistry, ensure_clone, load_private_key
        if not (settings.github_app_id and (settings.github_app_private_key_file or settings.github_app_private_key)):
            raise RuntimeError("PORTAL_REGISTRY_MODE=github needs GITHUB_APP_ID and GITHUB_APP_PRIVATE_KEY_FILE")
        registry = ensure_clone(settings.registry_dir, settings.github_registry,
                                lambda path: Registry(path, settings.git_name, settings.git_email))
        gh = GitHubApp(settings.github_app_id, load_private_key(settings), settings.github_registry,
                       api=settings.github_api)
        out.update(registry=registry, remote=RemoteRegistry(registry, gh), archive=worker.default_archive(settings))
    else:
        registry = Registry(settings.registry_dir, settings.git_name, settings.git_email)
        if not (settings.registry_dir / ".git").exists():
            registry.init()
        out["registry"] = registry
    return out


def create_app(settings=None, pool=None, run_expiry=True, orcid=None, publisher=None):
    """The app. `pool`, `orcid` (an ORCID client) and `publisher` ({registry, store, classifier}) may be given, as
    tests do; otherwise they are made from the settings."""
    settings = settings or Settings.from_env()
    own_pool = pool is None
    pool = pool or make_pool(settings.database_url, min_size=1, max_size=10)
    uploads = settings.submissions_dir / "incoming"
    orcid = orcid or OrcidClient(settings.orcid_base, settings.orcid_client_id, settings.orcid_client_secret,
                                 f"{settings.base_url}/consent/callback")
    publisher_ctx = {}

    def receive(path, client_ip, new_paper=False):
        """Receive a submission file: the same for every route (design §4.4). Raises SubmissionError."""
        with pool.connection() as conn:
            return submissions.receive(conn, path, submissions_dir=settings.submissions_dir,
                                       base_url=settings.base_url, client_ip=client_ip, new_paper=new_paper)

    mcp = mcp_server.build(mcp_server.Portal(settings, pool, receive))
    mcp_app = mcp_server.http_app(mcp)

    def publish_now():
        if not publisher_ctx:
            publisher_ctx.update(publisher or _publisher(settings))
        with pool.connection() as conn:
            return worker.publish_confirmed(conn, settings=settings, **publisher_ctx)

    def expire_now():
        with pool.connection() as conn:
            expired = submissions.expire(conn, settings.submissions_dir)
        publish_now()                                       # confirmed submissions left by a restart or a failure
        return expired

    async def expiry_loop():
        while True:
            try:
                expired = await run_in_threadpool(expire_now)
                if expired:
                    log.info("expired %d submission(s)", len(expired))
            except Exception:  # noqa: BLE001 - keep the loop alive; the next round retries
                log.exception("expiring submissions failed")
            await asyncio.sleep(EXPIRY_INTERVAL_SECONDS)

    @asynccontextmanager
    async def lifespan(app):
        if own_pool:
            pool.open()
        task = asyncio.create_task(expiry_loop()) if run_expiry else None
        try:
            async with mcp.session_manager.run():
                yield
        finally:
            if task:
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await task
            if own_pool:
                pool.close()

    app = FastAPI(title="EntryLib", version=__version__, lifespan=lifespan,
                  docs_url="/api/docs", openapi_url="/api/openapi.json", redoc_url=None)
    app.state.settings = settings
    app.state.pool = pool

    @app.get("/healthz", include_in_schema=False)
    def healthz():
        """Liveness and readiness: the app runs and the database answers."""
        body = {"portal": __version__, "claimset": claimset.__version__, "spec": claimset.SPEC_VERSION}
        try:
            with pool.connection(timeout=2) as conn:
                conn.execute("SELECT 1")
            body["database"] = "ok"
            return body
        except Exception as exc:  # noqa: BLE001 - any failure means not ready
            body["database"] = f"unavailable: {type(exc).__name__}"
            return JSONResponse(body, status_code=503)

    @app.get("/", response_class=HTMLResponse, include_in_schema=False)
    def home():
        return _static("index.html")

    @app.get("/submit", response_class=HTMLResponse, include_in_schema=False)
    def upload_page():
        """The upload page (design §4.4): a file picker whose script posts the file to /api/submissions."""
        return HTMLResponse(_static("submit.html"), headers={"Content-Security-Policy": UPLOAD_PAGE_CSP})

    @app.get("/submit.js", include_in_schema=False)
    def upload_script():
        return Response(_static("submit.js"), media_type="text/javascript",
                        headers={"Content-Security-Policy": UPLOAD_PAGE_CSP})

    @app.post("/api/validate", tags=["submissions"])
    async def validate(request: Request):
        """Check a claimset file (JSON) or a submission package (BagIt zip), sent as the request body, exactly as a
        submission is checked. Nothing is kept. Always 200: `valid` says whether it would be accepted."""
        try:
            path, _ = await _save_body(request, uploads)
        except UploadTooLarge:
            return _error(413, f"larger than {submissions.MAX_UPLOAD_BYTES} bytes")
        try:
            result = await run_in_threadpool(submissions.check, path)
        finally:
            path.unlink(missing_ok=True)
        return result.as_json()

    async def _receive(path, request, new_paper):
        try:
            return await run_in_threadpool(receive, path, _client_ip(request), new_paper)
        except submissions.SubmissionError as exc:
            return _error(exc.status, str(exc), exc.errors, exc.warnings)
        finally:
            path.unlink(missing_ok=True)

    @app.post("/api/submissions", status_code=201, tags=["submissions"])
    async def submit(request: Request, new_paper: bool = False):
        """Submit a claimset file (JSON) or a submission package (BagIt zip, `claimset package`) as the request body:
        `curl --data-binary @paper.zip -H 'Content-Type: application/zip' <portal>/api/submissions`.

        A valid submission is held for 48 hours. The response gives one consent link per guarantor: pass each to
        its guarantor, who signs in with ORCID and confirms. The links are shown only in this response. Once every
        guarantor has confirmed, the claimset is published.

        A new version of a published claimset sets `paper.id` to its identifier. A new claimset with the same title
        and guarantor as one already on EntryLib is refused (409) unless `new_paper=true` says it is a different
        paper."""
        try:
            path, _ = await _save_body(request, uploads)
        except UploadTooLarge:
            return _error(413, f"larger than {submissions.MAX_UPLOAD_BYTES} bytes")
        return await _receive(path, request, new_paper)

    @app.post("/api/submissions/from-url", status_code=201, tags=["submissions"])
    async def submit_from_url(request: Request, url: str = Body(..., embed=True), new_paper: bool = False):
        """Submit a package or a claimset file deposited at a public https URL (Zenodo, GitHub, a repository):
        `{"url": "https://..."}`. The portal fetches it (at most 210 MB, 5 redirects, 120 seconds) and checks it as
        an upload. The response is that of POST /api/submissions."""
        try:
            path = await run_in_threadpool(fetch.download, url, uploads)
        except fetch.FetchError as exc:
            return _error(422, f"cannot fetch the URL: {exc}")
        return await _receive(path, request, new_paper)

    @app.get("/consent/callback", response_class=HTMLResponse, include_in_schema=False)
    async def consent_callback(state: str = "", code: str = "", error: str = ""):
        """ORCID returns here after sign-in."""
        if error or not code or not state:
            return HTMLResponse(pages.message("Sign-in cancelled", "ORCID sign-in was not completed. Open the "
                                              "consent link again to retry."), status_code=400)
        try:
            who, _ = await run_in_threadpool(orcid.exchange, code)
        except OrcidError as exc:
            return HTMLResponse(pages.message("Sign-in failed", str(exc)), status_code=502)

        def work():
            with pool.connection() as conn:
                return consent.complete(conn, state, who)
        outcome = await run_in_threadpool(work)
        status_url = f"{settings.base_url}/api/submissions/{outcome.submission}" if outcome.submission else None
        if outcome.result != "confirmed":
            code_ = {"wrong_person": 403, "limit": 429, "not_pending": 409, "duplicate": 409}.get(outcome.result, 400)
            return HTMLResponse(pages.message("Not confirmed", outcome.message, status_url), status_code=code_)
        try:
            done = dict(await run_in_threadpool(publish_now))
        except Exception:  # noqa: BLE001 - the periodic loop retries; the guarantor has confirmed either way
            log.exception("publishing after consent failed")
            done = {}
        published = done.get(outcome.submission)
        text = (f"Thank you. The claimset is published as {published}." if published else
                "Thank you. You have confirmed the claimset; it will be published shortly.")
        return pages.message("Confirmed", text, status_url)

    @app.get("/consent/{token}", response_class=HTMLResponse, include_in_schema=False)
    def consent_page(token: str):
        """The page a guarantor opens from their consent link."""
        with pool.connection() as conn:
            ctx = consent.page_context(conn, token, settings.submissions_dir)
        if ctx is None:
            return HTMLResponse(pages.message("Unknown link", "This consent link is not valid. Links expire with "
                                              "their submission, after 48 hours."), status_code=404)
        status_url = f"{settings.base_url}/api/submissions/{ctx['submission']}"
        return pages.consent(ctx, f"{settings.base_url}/consent/{token}/start", status_url)

    @app.get("/consent/{token}/start", include_in_schema=False)
    def consent_start(token: str):
        """Begin ORCID sign-in for a consent link."""
        if not orcid.configured:
            return HTMLResponse(pages.message("Not available", "ORCID sign-in is not configured on this server."),
                                status_code=503)
        with pool.connection() as conn:
            state = consent.start(conn, token)
        if state is None:
            return RedirectResponse(f"{settings.base_url}/consent/{token}", status_code=303)
        return RedirectResponse(orcid.authorize_url(state), status_code=303)

    @app.get("/api/submissions/{sub_id}", tags=["submissions"])
    def submission_status(sub_id: str):
        """The state of a submission: pending, confirmed, published (with its identifier), refused or expired."""
        with pool.connection() as conn:
            out = submissions.status(conn, sub_id, settings.base_url,
                                     settings.github_registry if settings.registry_mode == "github" else None)
        if out is None:
            return _error(404, "no such submission (submissions are forgotten 14 days after they close)")
        return out

    @app.get("/api/search/claims", tags=["search"])
    def search_claims(q: str = "", type: str | None = None, role: str | None = None, novelty: str | None = None,
                      planning: str | None = None, support: str | None = None, assumption: str | None = None,
                      licence: str | None = None, guarantor: str | None = None, limit: int = 10, offset: int = 0):
        """Claims of current versions matching the words in q, best match first (full-text search, design §7.2).
        Filters take values of the claimset specification's vocabularies. Each result carries its version, status,
        status notice and validator warnings, and links to the claim's bundle."""
        try:
            with pool.connection() as conn:
                return search.search_claims(conn, settings.base_url, q, limit, offset, type=type, role=role,
                                            novelty=novelty, planning=planning, support=support,
                                            assumption=assumption, licence=licence, guarantor=guarantor)
        except search.SearchError as exc:
            return _error(400, str(exc))

    @app.get("/api/search/papers", tags=["search"])
    def search_papers(q: str = "", licence: str | None = None, guarantor: str | None = None, limit: int = 10,
                      offset: int = 0):
        """Claimsets whose current versions match the words in q, best match first, as paper cards. With `guarantor`
        (an ORCID iD) and no q: that guarantor's claimsets, most recently updated first."""
        try:
            with pool.connection() as conn:
                return search.search_papers(conn, settings.base_url, q, limit, offset, licence=licence,
                                            guarantor=guarantor)
        except search.SearchError as exc:
            return _error(400, str(exc))

    app.router.routes.extend(mcp_app.routes)                # /mcp; its session manager runs in the lifespan
    return app

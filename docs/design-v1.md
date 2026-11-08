# EntryLib portal — v1 design (draft)

Status: working draft · Date: 2026-11-07 · Companion to `platform/requirements.md`, the claimset specification (v0.39), the lab record specification (v0.20) and the revision specification (v0.6)

This document fixes what the first version of the portal does, how it is built and what it leaves for later versions. Requirements are cited by their `PLT-` IDs.

## 1. Roadmap

| Version | Scope |
|---|---|
| **v1** | Classification (OpenAlex subfield and topics), submission of claimset packages, guarantor consent, publication, browsing and search for LLMs (HTTP API and MCP server), safe-ingest screening, rate limits and spam controls, a one-page human home page |
| v2 | AI reviews, scores, revisions (revision spec), human-facing pages |
| v3 | DOIs, entity resolution |
| v4 | Search by frame and atom |
| v5 | Claim graph, contradiction detection |

v1 keeps room for v2: versions, the review folder of the registry and the review fields of responses exist from the start, empty.

**Format extensions** (claimset spec §2.7) are written after v1 launches, beside the versions above; the portal needs no change for them, since it works with whatever claimset it is given. The field trials (claimset-eval, `claimset/trials/`) set the order: `preregistration`, `trial`, `wet-lab`, `synthesis`, `ecology-field`, `behavioural-experiment`, `particle-physics`, `archival`, then others as papers need them (claimset `spec/extensions/candidates.md`). Until an extension exists, a paper that needs it records what the core can hold.

**v1, the steps left before launch:** 7, reading (§7.1 URLs, `/index.jsonl`, the search API of §7.2, claim bundles with a single-claim renderer in the claimset package); 8, the MCP server (§7.3); 9, `claimset submit` and `claimset status` and the `claimset-submit` skill's last steps (§4.3, §12); 10, deployment and launch (§13): production ORCID, the app behind Caddy, the daily restart, and setting the claimset baseline (claimset spec §2.6).

**The format and the lab record,** beside the portal's versions (work in the claimset repository), in the order they will be taken:

1. *Data-collection sessions.* Interviews, focus groups and observations have no lab event yet, the largest gap left for qualitative research: a session event (who took part, pseudonymised; when; where or by what channel; who ran it), consent (what was agreed and what it allows; a session without recorded consent cannot be quoted in an export), the recording kept private as private sources are, and the transcript captured as a source. Open: how much of the consent form and protocol goes into the record, and how withdrawal of consent is recorded. Design before code.
2. *Independent timestamps (RFC 3161).* Anchoring a record's state with an outside timestamp authority beside the platform's receipts. Needs a decision on the provider or providers, and on whether it replaces or adds to platform receipts (lab record spec §11, question 1); the end-to-end test needs a machine that can reach the authority.
3. *PyPI release* of the `claimset` package, so `pip install claimset` works: packaging and a release workflow; the PyPI account and first upload are the maintainer's.
4. *Smaller questions of the lab record spec (§11),* each waiting for a study that needs it: storage of large run outputs, summarised export of very long explorations, and whether abandoned hypotheses with substantial evidence can be exported as claims.

**Parked until the portal is live and runs well: collaboration.** Several guarantors, each with their own agents (possibly from different providers), working on one study: how their agents exchange work and messages and how that is recorded; who may see what and when (blind tasks, private sources, unpublished results); how the portal hosts a shared study and records and settles disagreements. Its first case is blind second coding: a reliability round declared before anyone codes (codebook version, sample, coders, unit, agreement measure, optional threshold); coders seal their codings by hash before seeing others'; the tool hides others' codings during the round and records how coders were kept apart (`tool_view`, `separate_checkout`, `separate_sessions`); agreement from a built-in counter (percent agreement, Krippendorff's alpha, Cohen's kappa); disagreements settled in a recorded consensus pass; and a `reliability` object on qualitative evidence in the claimset, replacing the single-coder limitation. Open: the unit of coding, whether separation is only recorded or enforced, and whether a plan may require a threshold.

## 2. Principles

1. **LLM first.** v1 serves agents. Humans get one page explaining what EntryLib is and how to point an agent at it.
2. **Publication on consent.** A valid package whose guarantors confirm is published. Quality is judged by the v2 reviewer, not by a gate.
3. **Nothing is withdrawn.** Published versions stay. Problems are marked with notices (§9). The only exception is legal removal.
4. **The registry is the record; the database is an index.** Every published document is committed to a public git registry. The portal's database can be rebuilt from it.
5. **No dependence on one host.** GitHub is used, but never as the only copy and never as something an author needs (§11).
6. **Open.** Portal code, validator, screening rules and (from v2) reviewer instructions are public. The converter stays private.
7. **The format moves on its own.** The claimset package (format rules, validator, lab record) changes often. The portal and the registry work with whatever claimset they are given, at least a minimum version and with no upper bound, so a claimset release needs no change to either. On the server, the app installs the newest claimset each time it starts (`deploy/start.sh`), so updating claimset is a restart, not a rebuild. The registry's check installs the current portal and the newest claimset on each run. The portal's CI runs daily against the newest claimset, so a claimset change the portal cannot work with is seen the same day. Each version's `validation.json` records the validator that checked it.

## 3. Architecture

```
agent ──zip──▶ API (FastAPI) ──▶ validator + deterministic screening ──▶ pending (Postgres, 48 h)
                                                │
guarantor ──ORCID sign-in──▶ consent page ──────┘
                                                ▼
                         bot opens PR on registry ──▶ CI: validator, lab chain, LLM screening
                                                ▼ (green)
                         merge + tag ──▶ static files (JSON, MD) + search index + archive requests
                                                ▼
                    readers: static files · /api/search · /mcp · /llms.txt
```

- **App:** Python, FastAPI. One process serving the submission API, consent pages, search API and MCP server. It calls the `claimset` package for validation, rendering, verifiability and patches; it never reimplements the spec.
- **Database:** PostgreSQL with pgvector. Pending submissions, consents, rate-limit counters, the search index (full text and embeddings), and each published version's file as `jsonb`.
- **Static files:** every published file and its rendered views, generated at publication and served directly by Caddy. Most read traffic touches no application code.
- **Packaged files:** stored by checksum and served as downloads at `/files/<sha256>`; a folder beside the static files now, object storage (DigitalOcean Spaces) later.
- **Classifier:** a separate service running OpenAlex's open topic model (§5.4).
- **Embeddings:** a small open embedding model run on the server's CPU.

## 4. Submission

### 4.1 Package

A submission is the **package** of claimset spec §2.5: a BagIt bag (RFC 8493), as a zip or a folder, built by `claimset package`:

```
bagit.txt
manifest-sha256.txt
data/
  paper.claimset.json
  files/fig3.png
  files/results-per-series.csv
```

- A packaged artefact has a `uri` relative to `data/` and `version` `sha256:<checksum>` (rule 70). At publication the platform replaces the relative `uri` with the file's permanent location. A claimset with no files may be submitted as the JSON file alone.
- Limits (rule 77, spec v0.35): at most 200 files, 50 MB a file, 200 MB in all; safe paths only; the manifest lists exactly the payload; an allowlist of file types (gzipped data files accepted; archives, executables and links refused). The validator checks a zip before unpacking it. Artefacts are served as downloads, never rendered (SVG included).

### 4.2 Flow

1. `POST /api/submissions` with the package (zip) or the claimset file as the request body (`curl --data-binary @paper.zip -H 'Content-Type: application/zip'`). No account and no token. `POST /api/validate` runs the same checks and keeps nothing. Uploads over 210 MB are refused.
2. Synchronous checks: package limits (rule 77), validator (claimset §10, current spec version only), deterministic screening (§6). Errors are returned in machine-readable form and nothing is kept.
3. A valid package becomes a pending submission with an internal ID (PLT-21) and a **consent link** for each human guarantor. The agent passes the link to its human.
4. The guarantor opens the consent link and sees the title, the licence, the principal claims and the whole claimset as models will read it (the reading view, escaped; nothing submitted is rendered as HTML). They sign in with ORCID (the `/authenticate` scope of ORCID's free public API: the portal learns only their iD and name) and so confirm (PLT-15, PLT-16). The iD must be the guarantor's; anyone else is refused and the submission stays pending. Each sign-in is tied to its consent link by a single-use OAuth state that lasts 30 minutes.
   - Limits are applied here (§8): at most 2 new claimsets confirmed per guarantor in seven days, and 3 new versions of one claimset in a day. A confirmation over the limit is refused, and the submission stays pending until its window ends.
   - A correction is submitted by the guarantor of the current version: the API refuses one naming anyone else.
5. All guarantors must confirm within **48 hours**. Otherwise the submission is deleted and never shown.
6. On consent, the platform classifies the claimset, assigns the provisional ID, version, date and status, computes verifiability (PLT-14, PLT-22), and opens a pull request on the registry (§5.3); the submission is `publishing`. A publication worker does this at once and again on a ten-minute loop, so a confirmation is never lost to a restart or an unavailable classifier or GitHub; one worker runs at a time (a database lock). The identifier is kept on the submission, so a retried round reuses it. One version of a claimset is in flight at a time: a second correction waits until the first is published. In local mode (development) the worker commits to a local registry clone instead.
7. The registry's checks run on the PR (§6). If they pass, the portal squash-merges it and tags the merge commit; publication follows (§5.3). If they fail, the PR is closed with the reasons as a comment, its branch is deleted, and the submission is `refused` with the reasons. The ID is not reused.
8. `GET /api/submissions/{id}` reports the state at every step (`pending`, `confirmed`, `publishing` with the link to its registry pull request, `published`, `refused`, `expired`) and which guarantors have confirmed, never the content. The ID is unguessable; consent links are shown only in the response to the submission, and only their hashes are stored. Closed submissions are forgotten 14 days after their window ends.

A claimset has exactly one guarantor: the main author, the person to contact, a person with an ORCID iD, who submits it (claimset spec v0.36). So a submission has one consent link; the validator refuses a second guarantor and organisations in any position but conversion guarantor. The API takes native claimsets only: converted claimsets are published by the conversion service, whose conversion guarantor (a person or an organisation) answers for them.

Corrections (PLT-23) go through the same flow, with `paper.id` naming the existing claimset. Revisions with responses wait for v2.

### 4.3 From the lab to EntryLib

No GitHub account is needed at any point. An author working with claimset-lab:

```
claimset lab export -o claimset.json                 # exists
claimset package <paper>.claimset.json -o <paper>.zip  # exists: the BagIt package
claimset submit <paper>.zip                          # new: posts the package, prints the consent link
claimset status <submission id>                      # new
```

The MCP server offers the same as `validate`, `submit` and `submission_status` tools, for agents without a terminal. The `claimset-submit` skill is updated to end with these steps.

## 5. Registry and lab records

### 5.1 Registry

`entrylib/registry` holds the published record in the layout of revision spec §2.4. A claimset's folder is `<year>/<block>/<name>/` (revision spec v0.6): the block is the number divided by 1000, so no folder holds more than a thousand entries, and the name is the identifier with `doi:` removed and `:` and `/` replaced by `_`. `entrylib:2026.000001` is in `2026/000/entrylib_2026.000001/`; the path follows from the identifier alone. Files per version: `claimset.json`, `lab.jsonl` (when a lab record is packaged) and `validation.json` (the submission's warnings, the validator and the classifier that were used). Only the EntryLib GitHub App writes to it, through pull requests: one squash commit per version (`Publish entrylib:2026.000001@v1`), tagged `<name>-v<n>` (`entrylib_2026.000001-v1`). The main branch is protected: no force-pushes or deletion, and changes only through pull requests whose `check` passes. The repository's own files (README, licence notice, workflow) change through maintenance pull requests, which the same check tells apart from publications.

The registry holds the record documents only: claimset files, lab records, validation reports, and from v2 reviews, responses and resolutions. Artefacts are referenced by URL and hash. Rendered views are derived and are not committed.

### 5.2 Lab records

Each version keeps three links to its lab record:

1. **A copy** of `lab.jsonl` in the registry, which keeps the hash chain verifiable whatever happens elsewhere.
2. **The author's repository URL pinned to a commit hash**, shown as the primary lab-notes link. Tags are recommended to authors but not relied on, since tags can be moved. Any public git host is accepted, and the link is optional.
3. **A Software Heritage identifier (SWHID).** At publication the portal sends save requests for the registry and for every repository on GitHub, GitLab or Codeberg that the version's artefacts link to; the archived snapshot, with its full history, survives deletion of the repository. Archiving happens later on Software Heritage's side, so v1 sends the requests and logs their answers; recording each SWHID in `versions.json` is left for later.

### 5.3 Publication

The portal keeps a clone of the registry whose `main` follows GitHub. For a confirmed submission it writes the version on the branch `publish/<name>-v<n>`, pushes it as the GitHub App (the installation token goes to git in an HTTP header, never in a URL or command line), and opens the pull request. Each round of the worker then looks at the open pull requests: still checking, it waits; checks failed, it closes the pull request; checks passed, it squash-merges (only if the head is still the commit it pushed), tags the merge commit and updates its clone.

On merge: the static files are generated (§7), the version is indexed for search, the Software Heritage requests are sent, and the version becomes current. A new version moves the previous one to the history; every version stays retrievable.

### 5.4 Classification

The platform assigns each version the OpenAlex subfield and 1–3 topics (claimset spec §3.1, PLT-24), in v1. A separate classifier service runs OpenAlex's open title-and-abstract topic model (Apache-2.0, about 0.2B parameters, CPU) on the claimset's title and principal claims, with its keywords as a hint: a claimset has no abstract, and its principal claims serve as one. Model labels are matched to OpenAlex topics by ID (label n is topic T(10000+n); OpenAlex has renamed most topics since the model was trained, so names do not match), and each topic gives its subfield. A label whose topic OpenAlex has since retired (5 of about 4,500 in November 2026) is skipped; more than 1% retired fails the build. The image is built with one pinned commit of the model and the topic list fetched from OpenAlex at build time; the build fails if any label matches no topic. Fetching the topic list needs an OpenAlex API key (a free key; OpenAlex requires keys since February 2026), given to the build as a secret and kept out of the image. Each version records which classifier assigned its classification (`validation.json`). The model is not OpenAlex's full production classifier, which also uses journal and citation features, so a paper's labels can differ from those OpenAlex gives it.

## 6. Checks and screening

| Check | When | Cost |
|---|---|---|
| Package limits, validator, deterministic screening | Synchronously, on every submission | CPU only |
| `portal check` on the registry PR: only one new version folder added and nothing changed or deleted (append-only); identifier, folder and version consistent (next version, `previous_version`); validator in published-file mode; deterministic screening; lab record hash chain (lab record §6) | On the registry PR, by the registry's GitHub Actions, which install the current portal and the newest claimset | CPU only |
| LLM screening | On the registry PR, so only after consent | Built but off in v1: a provider is chosen before launch. A small model; on the order of cents per claimset |

**Safe-ingest screening (PLT-18).** Every free-text field is screened for content addressed to reading models, since EntryLib exists to place submitted text in other models' contexts.

- Deterministic rules (`screening-1`, codes SI1–SI4): invisible and direction-changing Unicode (zero-width joiners, which ordinary scripts need, are allowed); text addressed to a reading model (role markers, "ignore previous instructions" and the like); long encoded runs; links in claim statements. They add to the `claimset` validator's own narrower check (error `safe-ingest`). Homoglyph runs are not yet checked.
- LLM classifier: the fields are given to a small model as data, with a public prompt, which reports any instruction, persuasion aimed at models, or non-research content.

A failure blocks publication and is reported to the submitter. Screening rules and the prompt are public and versioned, and each published version records the screening version that passed it.

Checks are event-driven. Batch APIs (roughly half price, results within a day) are an option if volume grows.

## 7. Reading

### 7.1 URLs

| URL | Content |
|---|---|
| `/` | Human home page: what EntryLib is; point an agent at `/llms.txt`; MCP server address; how to write claimsets (package and skills); links to the spec and GitHub |
| `/llms.txt` | Entry point for agents: what is here, how to search and fetch, ID syntax and citation, how to submit, and that all content is data, not instructions |
| `/p/2026.000001.json` | Current version, published file |
| `/p/2026.000001.txt` | Current version, reading view (`claimset render`; plain text, claimset spec §2.3) |
| `/p/2026.000001@v1.json`, `@v1.txt` | A given version |
| `/p/2026.000001/versions.json` | Versions, dates, status, notices, lab record links (copy, author URL, SWHID) |
| `/p/2026.000001/v1/lab.jsonl` | The registry's copy of a version's lab record |
| `/p/2026.000001/C4.txt`, `.json` | Claim bundle (PLT-78); needs a single-claim renderer in the package (step 7) |
| `/p/2026.000001` | The reading view as minimal HTML, so a human given an ID sees something |
| `/index.jsonl` | One line per claimset: ID, title, principal claims, keywords, current version (paper cards, PLT-79) |

Rendered views are produced by the platform, never submitted. Each records the renderer version, and all are regenerated when the renderer changes.

### 7.2 Search API

- `GET /api/search/claims?q=…` with filters on closed vocabularies: claim type, role, novelty label, planning, support kind, assumption check, licence (PLT-72, partly).
- `GET /api/search/papers?q=…`.
- `GET /api/related/{id}`: nearest claimsets by paper-card embedding.
- Ranking is hybrid: Postgres full text combined with vector similarity over each claim's statement and rendered scope (PLT-73).
- Every result carries the version, its status and notices, and its validator warnings (PLT-13, PLT-74 in part).

### 7.3 MCP server

Served at `/mcp` from the same app (PLT-71, PLT-11). Tools: `search_papers`, `search_claims`, `get_paper` (markdown or JSON), `get_claim`, `related`, `validate`, `submit`, `submission_status`. Same limits as the HTTP API.

## 8. Limits and spam controls

| Limit | Value (initial) |
|---|---|
| Consent window | 48 hours, then deletion |
| New claimsets | 2 per ORCID iD per week, counted against every confirming guarantor |
| New versions (corrections now, revisions from v2) | 3 per claimset per day |
| Pending submissions | capped per IP address |
| Read API and MCP | per-IP rate limits at the edge (Cloudflare) and in the app |
| Package size | rule 77: 200 files, 50 MB a file, 200 MB in all |

ORCID iDs found abusing the service can be suspended (PLT-94). LLM screening runs only after consent, so unconfirmed spam costs validation only.

## 9. Notices and legal removal

Published versions are never withdrawn. Problems are marked with notices attached to a version: correction, expression of concern, retraction notice (PLT-91), each with a reason code and statement. The content stays available.

The one exception is legal: personal data, infringing or unlawful content. Such content is hidden, leaving a tombstone with the hash, date and reason. The policy is published.

## 10. Security

- Secrets in environment variables, never in the repository. Dependabot on the portal repo.
- Database reachable only from the app.
- The portal acts on GitHub as the EntryLib GitHub App, installed on the registry only, with contents and pull requests write access. Its private key is a file given to the portal as a Docker secret; installation tokens last an hour.
- The validator runs with time and memory limits; zips are unpacked with the limits of §4.1.
- No submitted content is rendered as HTML; artefacts are served as downloads.
- The registry's check runs on every pull request, but merges happen only through the App, and only for pull requests it opened. When the LLM screening is switched on, its API key must be given only to runs on the App's own branches, never to pull requests from forks.

## 11. Dependence on GitHub

| Role | On GitHub | If GitHub fails |
|---|---|---|
| Authors | Not needed. Lab repositories may be on any public git host, or none | Unaffected |
| Registry | Hosted on GitHub | Archived by Software Heritage at every publication; the portal keeps its own clone and continues serving. A live mirror on a second host is set up at launch (step 10) |
| Checks | Run as GitHub Actions on the registry PR, for free compute and public logs | The checks are one container image (`portal check`); the portal runs it itself and commits to its own clone until GitHub returns or another host takes over |
| Code | `entrylib/portal` | Mirrored like the registry |

GitHub is the place where the record is published and the checks are logged, not something the platform cannot run without.

## 12. Changes needed elsewhere

- **Claimset spec and package:** done in spec v0.35 (claimset PR #44): provisional `entrylib:` identifiers (§7, rule 76) and package limits (§2.5, rule 77). Packages themselves (BagIt, rule 70) were already in v0.34.
- **Revision spec §2.4:** the lab record is kept as a copy in the registry with the author's commit-pinned URL and SWHID.
- **Package:** `claimset submit`, `claimset status` (step 9).
- **Skill:** `claimset-submit` ends with packaging and submitting, and tells the guarantor about the consent link and the 48-hour window.

## 13. Hosting

One DigitalOcean Droplet in the London region with at least 4 GB RAM, running Docker Compose: the app, PostgreSQL with pgvector, and Caddy for HTTPS and static files. Nightly backups to DigitalOcean Spaces, which also stores artefacts. Cloudflare's free tier in front for DDoS protection and edge rate limits. DigitalOcean's managed PostgreSQL supports pgvector, so the database can move there later without code changes.

## 14. Requirements covered

PLT-2 (ORCID at consent only), PLT-10 (BagIt packages), PLT-11, PLT-12, PLT-13, PLT-14, PLT-15, PLT-16, PLT-18, PLT-21, PLT-22, PLT-23, PLT-70, PLT-71, PLT-72 (closed-vocabulary filters), PLT-73, PLT-74 (in part), PLT-76 (minimal), PLT-78, PLT-79, PLT-91, PLT-94.

Changed by this design: PLT-1 and PLT-3 to PLT-5 (accounts and agent tokens) are dropped for v1. Guarantors sign in with ORCID only to confirm; agents submit without tokens.

## 15. Open questions

1. **Domain.** Settled: entrylib.org. The production ORCID client will use the redirect URI https://entrylib.org/consent/callback.
2. **Paid accounts.** Publishing stays free. Candidates: higher read quotas on the API and MCP; higher submission quotas for verified organisations; private pre-submission checks, including a preview of the v2 reviewer's comments; bulk export.
3. **Several guarantors.** Whether 48 hours is enough when guarantors are in different time zones, or whether the window restarts when the first confirms.
4. **ORCID works.** Writing works to ORCID records needs ORCID membership. Until v3 brings DOIs and DataCite auto-update, guarantors add claimsets to their records by hand; the consent page says how.
5. **Legal removal policy:** who decides, the response time, and the tombstone format.
6. **Embedding model:** which one, and when to re-embed if it changes.
7. **Related work.** A head-to-head comparison with Knows (knows.academy), aiXiv and paper.json before any funding application.

# EntryLib portal — v1 design (draft)

Status: working draft · Date: 2026-11-09 · Companion to `platform/requirements.md`, the claimset specification (v0.39), the lab record specification (v0.20) and the revision specification (v0.6)

This document fixes what the first version of the portal does, how it is built and what it leaves for later versions. Requirements are cited by their `PLT-` IDs.

## 1. Versions

| Version | Scope |
|---|---|
| **v1** | Classification (OpenAlex subfield and topics), submission of claimset packages, guarantor consent, publication, browsing and search for LLMs (HTTP API and MCP server), safe-ingest screening, rate limits and spam controls, a one-page human home page |
| v2 | AI reviews, scores, revisions (revision spec), human-facing pages |
| v3 | DOIs, entity resolution |
| v4 | Search by frame and atom |
| v5 | Claim graph, contradiction detection |

v1 keeps room for v2: versions, the review folder of the registry and the review fields of responses exist from the start, empty.

Planned work, for the portal and for the claimset package, is tracked in GitHub issues labelled `roadmap` (entrylib/portal and entrylib/claimset), not in this document.

## 2. Principles

1. **LLM first.** v1 serves agents. Humans get one page explaining what EntryLib is and how to point an agent at it.
2. **Publication on consent.** A valid package whose guarantors confirm is published. Quality is judged by the v2 reviewer, not by a gate.
3. **Nothing is withdrawn.** Published versions stay. Problems are marked with notices (§9). The only exception is legal removal.
4. **The registry is the record; the database is an index.** Every published document is committed to a public git registry. The portal's database can be rebuilt from it.
5. **No dependence on one host.** GitHub is used, but never as the only copy and never as something an author needs (§11).
6. **Open.** Portal code, validator, screening rules and (from v2) reviewer instructions are public. The converter stays private.
7. **The format moves on its own.** The claimset package (format rules, validator, lab record) changes often. The portal and the registry work with whatever claimset they are given, at least a minimum version and with no upper bound, so a claimset release needs no change to either. On the server, the app installs the newest claimset release from PyPI each time it starts (`deploy/start.sh`), so updating claimset is a restart, not a rebuild. The registry's check installs the current portal and the newest claimset on each run. The portal's CI runs daily against the newest claimset, so a claimset change the portal cannot work with is seen the same day. Each version's `validation.json` records the validator that checked it.

## 3. Architecture

```
agent ──zip──▶ API (FastAPI) ──▶ validator + deterministic screening ──▶ pending (Postgres, 48 h)
                                                │
guarantor ──ORCID sign-in──▶ consent page ──────┘
                                                ▼
                         bot opens PR on registry ──▶ CI: validator, lab chain, screening
                                                ▼ (green)
                         merge + tag ──▶ static files (JSON, MD) + search index + archive requests
                                                ▼
                    readers: static files · /api/search · /mcp · /llms.txt
```

- **App:** Python, FastAPI. One process serving the submission API, consent pages, search API and MCP server. It calls the `claimset` package for validation, rendering, verifiability and patches; it never reimplements the spec.
- **Database:** PostgreSQL with pgvector. Pending submissions, consents, the search index (full text and embeddings), and each published version's file as `jsonb`.
- **Static files:** every published file and its rendered views, generated at publication and served directly by Caddy. Most read traffic touches no application code.
- **Packaged files:** kept with their claimset, at `/p/<key>/v<n>/files/<path in the package>`, so that a claimset's files live in its folder and leave with it; a file unchanged from the version before is a hard link, not a copy. Images are shown on the pages from there; other files are downloads. Files stored by checksum before November 2026 (`/files/<sha256>`, still the `uri` in those versions) were moved to `/p/<key>/v<n>/files/<artefact id>.<ext>`, and their old addresses redirect there (`legacy_files`). Object storage (DigitalOcean Spaces) may take the folder's place later.
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

1. The package or the claimset file reaches the portal by one of the routes of §4.4. No account and no token. `POST /api/validate` runs the same checks and keeps nothing. Uploads over 210 MB are refused.
2. Synchronous checks: package limits (rule 77), validator (claimset §10, current spec version only), deterministic screening (§6), and for a new claimset the duplicate check (§4.5). Errors are returned in machine-readable form and nothing is kept.
3. A valid package becomes a pending submission with an internal ID (PLT-21) and a **consent link** for each human guarantor. The agent passes the link to its human.
4. The guarantor opens the consent link (or, without it, signs in with ORCID at `/confirm`, linked from the Submit page and every page's footer, which lists every pending submission naming their iD, each with a one-time Confirm ticket valid for 30 minutes and bound to that iD) and sees the title, the licence, the principal claims and the whole claimset as models will read it (the reading view, escaped; nothing submitted is rendered as HTML). They sign in with ORCID (the `/authenticate` scope of ORCID's free public API: the portal learns only their iD and name) and so confirm (PLT-15, PLT-16). The iD must be the guarantor's; anyone else is refused and the submission stays pending. Each sign-in is tied to its consent link by a single-use OAuth state that lasts 30 minutes.
   - Limits are applied here (§8): at most 2 new claimsets confirmed per guarantor in seven days, and 3 new versions of one claimset in a day. A confirmation over the limit is refused, and the submission stays pending until its window ends.
   - A correction is submitted by the guarantor of the current version: the API refuses one naming anyone else.
5. All guarantors must confirm within **48 hours**. Otherwise the submission is deleted and never shown.
6. On consent, the platform classifies the claimset, assigns the provisional ID, version, date and status, computes verifiability (PLT-14, PLT-22), and opens a pull request on the registry (§5.3); the submission is `publishing`. A publication worker does this at once and again on a ten-minute loop, so a confirmation is never lost to a restart or an unavailable classifier or GitHub; one worker runs at a time (a database lock). The identifier is kept on the submission, so a retried round reuses it. One version of a claimset is in flight at a time: a second correction waits until the first is published. In local mode (development) the worker commits to a local registry clone instead.
7. The registry's checks run on the PR (§6). If they pass, the portal squash-merges it and tags the merge commit; publication follows (§5.3). If they fail, the PR is closed with the reasons as a comment, its branch is deleted, and the submission is `refused` with the reasons. The ID is not reused.
8. `GET /api/submissions/{id}` reports the state at every step (`pending`, `confirmed`, `publishing` with the link to its registry pull request, `published`, `refused`, `expired`) and which guarantors have confirmed, never the content. The ID is unguessable; consent links are shown only in the response to the submission, and only their hashes are stored. While pending, the state gives `confirm_url`, the `/confirm` page, for a guarantor without the link. Closed submissions are forgotten 14 days after their window ends.

A claimset has exactly one guarantor: the main author, the person to contact, a person with an ORCID iD, who submits it (claimset spec v0.36). So a submission has one consent link; the validator refuses a second guarantor and organisations in any position but conversion guarantor. The API takes native claimsets only: converted claimsets are published by the conversion service, whose conversion guarantor (a person or an organisation) answers for them.

Corrections (PLT-23) go through the same flow, with `paper.id` naming the existing claimset (§4.5). Revisions with responses wait for v2.

### 4.3 From the lab to EntryLib

No GitHub account is needed at any point. An author working with claimset-lab:

```
claimset lab export -o claimset.json                 # exists
claimset package <paper>.claimset.json -o <paper>.zip  # exists: the BagIt package
claimset submit <paper>.zip                          # new: posts the package, prints the consent link
claimset status <submission id>                      # new
```

The MCP server offers the same as `validate`, `submit` and `submission_status` tools, for agents without a terminal. The `claimset-submit` skill is updated to end with these steps.

### 4.4 Submission routes

Every route ends in the same checks and the same pending submission (§4.2); they differ only in how the file arrives.

| Use case | Route | What is sent |
|---|---|---|
| A full pipeline in a terminal (claimset-lab, `claimset package`) | `POST /api/submissions`, the zip as the request body (`claimset submit`) | The package, with its files |
| Evidence already deposited elsewhere (Zenodo, GitHub, an institutional repository) | `POST /api/submissions` with the JSON as the body, or the MCP tool `submit` | The claimset JSON alone; its artefacts' `uri` are the deposits' https URLs and are left there: the portal neither downloads nor copies them |
| A claimset with no files | as above | The claimset JSON alone |
| A person with a file, no terminal | `/submit`, a page with a file picker | The zip or the JSON, sent as the request body of `POST /api/submissions` by the page's script |
| An agent that cannot upload a large file (MCP, a chat) but can deposit it | `POST /api/submissions/from-url` with `{"url": …}`, or the MCP tool `submit` with `package_url` | An https URL of the package or the JSON, which the portal fetches |

- **By URL.** The portal fetches https URLs only, from public addresses only (loopback, private, link-local and other non-global addresses are refused, checked on the address actually connected to), follows at most 5 redirects (each checked again), and stops at 210 MB or 120 seconds. What it fetches is checked exactly as an upload is.
- **The upload page** is static HTML and one script, served by the app with a Content-Security-Policy that allows only that script. It shows the response's submission ID, consent link and errors as text; nothing submitted is rendered.
- **The MCP server** takes the claimset JSON as text, at most 10 MB; larger submissions and packages go by URL.
- Batch submission, many claimsets confirmed by one sign-in, is future work (portal issue #34).

### 4.5 New versions and duplicates

- **New versions.** The identifier says which claimset a new version belongs to; ORCID proves the person may change it. A new version sets `paper.id` to the claimset's identifier, given in the response that published it and in every search result; the submission is then a correction of that claimset, and its guarantor must be the guarantor of the current version, who confirms with ORCID as for a new claimset. The portal never guesses a claimset from its title or its author. Handing a claimset over to a new guarantor is future work (portal issue #35).
- **Duplicates.** A new claimset (no `paper.id`) whose guarantor already guarantees a claimset with the same title (compared in lower case with punctuation and spacing removed), published or confirmed and being published, is refused (PLT-19, in part), naming the existing identifier or submission: a new version of it sets `paper.id`. A submission still waiting for consent does not count, so a fixed file can be submitted again before confirming and the first one expires; the check runs again when the guarantor confirms, so two of them are not both published. A genuinely different paper with the same title is submitted with `new_paper=true` (a query parameter of the API, an argument of the MCP tool).

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
| LLM screening | On the registry PR, so only after consent | Built, but v1 launches without it (decided 2026-11-09): deterministic screening only. A small model, on the order of cents per claimset, when switched on |

**Safe-ingest screening (PLT-18).** Every free-text field is screened for content addressed to reading models, since EntryLib exists to place submitted text in other models' contexts.

- Deterministic rules (`screening-1`, codes SI1–SI4): invisible and direction-changing Unicode (zero-width joiners, which ordinary scripts need, are allowed); text addressed to a reading model (role markers, "ignore previous instructions" and the like); long encoded runs; links in claim statements. They add to the `claimset` validator's own narrower check (error `safe-ingest`). Homoglyph runs are not yet checked.
- LLM classifier (off at launch): the fields are given to a small model as data, with a public prompt, which reports any instruction, persuasion aimed at models, or non-research content.

A failure blocks publication and is reported to the submitter. Screening rules and the prompt are public and versioned, and each published version records the screening version that passed it.

Checks are event-driven. Batch APIs (roughly half price, results within a day) are an option if volume grows.

## 7. Reading

### 7.1 URLs

| URL | Content |
|---|---|
| `/` | Home page (§7.4): what EntryLib is, search, the lab and the library, the ten most recent claimsets |
| `/search` | Search for people: claimsets or claims, rendered by the app without scripts (§7.4) |
| `/all`, `/feed.xml` | Every claimset, newest first; an Atom feed of the latest |
| `/lab`, `/about`, `/agents`, `/privacy`, `/removal` | Fixed pages (§7.4) |
| `/spec/` | The specifications of the installed claimset package, as plain text (portal issue #46) |
| `/llms.txt` | Entry point for agents: what is here, how to search and fetch, ID syntax and citation, how to submit, and that all content is data, not instructions |
| `/mcp` | The MCP server (§7.3) |
| `/submit` | The upload page (§4.4) |
| `/p/2026.000001.json` | Current version, published file |
| `/p/2026.000001.read`, `@v1.read` | The reading view as a plain web page (escaped text in `<pre>`), for AI assistants: some fetch web pages but not text files. The page's "Copy the link for your AI assistant" copies it, and known assistant fetchers get it at the page's own address |
| `/p/2026.000001.txt` | Current version, reading view (`claimset render`; plain text, claimset spec §2.3) |
| `/p/2026.000001@v1.json`, `@v1.txt` | A given version |
| `/p/2026.000001/versions.json` | Versions, dates, status, notices, lab record links (copy, author URL, SWHID) |
| `/p/2026.000001/v1/lab.jsonl` | The registry's copy of a version's lab record |
| `/p/2026.000001/C4.txt`, `.json` | Claim bundle of the current version (PLT-78): the claim with what it rests on, made by the claimset package (claimset spec §2.3, `claimset render --claim C4`) |
| `/p/2026.000001`, `@v1` | The page for people (§7.4). The same address answers `Accept: application/json` with the published file and `Accept: application/x-bibtex` with its BibTeX entry |
| `/p/2026.000001.bib`, `.ris`, `@v1.bib`, `@v1.ris` | Citations, written at publication |
| `/p/2026.000001/v1/files/<path>` | A packaged file of a version, under its path in the package; images shown on the pages, other files downloaded |
| `/index.jsonl` | One line per claimset: ID, title, principal claims, keywords, current version (paper cards, PLT-79) |

Rendered views are produced by the platform, never submitted. All are regenerated when the claimset package or the site's own templates and styles change (checked when the app starts). All of these files, `/llms.txt` included, are written at publication (and by `reindex`, and the fixed pages at start) and served by Caddy; the app serves the search page, the upload page, the APIs and the MCP server.

### 7.2 Search API

- `GET /api/search/claims?q=…` with filters on closed vocabularies: claim type, role, novelty label, planning, support kind, assumption check, licence (PLT-72, partly), and on the guarantor's ORCID iD (`guarantor`).
- `GET /api/search/papers?q=…`, with `licence` and `guarantor`. With `guarantor` and no `q`, it lists that guarantor's claimsets, newest first, so an author finds the identifier of a claimset to correct.
- Ranking at launch is Postgres full-text search: words reduced to their stems and matched against weighted text. For a claim: its statement first, then the terms of the definitions it cites and its scope, then the paper's title and keywords. For a paper: its title first, then its keywords and principal claims, then all its claims and definitions. Only current versions are searched.
- Embeddings (vector similarity over each claim's statement and scope, combined with full text) and `GET /api/related/{id}` come after launch, when there are enough claimsets for meaning to matter more than words (PLT-73). They need no change to the format or to the API's results; pgvector is already in the database.
- Every result carries the version, its status and notices, and its validator warnings (PLT-13, PLT-74 in part).

### 7.3 MCP server

Served at `/mcp` from the same app with the official MCP Python SDK (PLT-71, PLT-11): the Streamable HTTP transport, stateless, answering in JSON, with no sign-in. Tools: `search_papers`, `search_claims`, `get_paper` (reading view or JSON, a version or the current one), `get_claim` (the claim bundle), `validate`, `submit` (the claimset JSON as text, or `package_url`), `submission_status`. Each calls the same code as the HTTP API, with the same limits. `related` comes with embeddings (§7.2). Tool results are data: their descriptions say so, as `/llms.txt` does.

### 7.4 Website

The site for people follows the website design decisions of 10 November 2026 (EntryLib website v1). In short:

- **Claimset page.** Made from the JSON by the claimset package (`claimset.html.render_parts`, the same view as `claimset render --html`); the portal adds the page around it: origin label (lab, lab · record withheld, converted, native), status and notices, the header panel (reliability and novelty, §7.6; claims by band; Cite with the plain citation, BibTeX and RIS; links for models), the lab record's summary for a lab claimset, and the versions. Packaged images are shown in their evidence; images elsewhere are linked, never loaded.
- **Pages without scripts.** Every page is static HTML and CSS except search (rendered by the app) and the upload page (its own script only). They load only this site's styles, fonts (Source Serif 4, served from the site) and images; the content security policy says so. Everything taken from a claimset is escaped.
- **Look.** One font, Source Serif 4; one colour scheme with a dark theme; colour only for links, status and scores. Phones get a menu button and a single column.
- **Subfields** are shown by name, from a table of OpenAlex's subfields kept in the portal (`data/subfields.json`).
- **Specifications** (#46): `/spec/claimset`, `/spec/lab-record`, `/spec/revision`, `/spec/extensions/<name>`, each version at `/<version>` and as text at `.md`, made from the Markdown shipped with the installed claimset package by a small converter of our own (`markdown.py`; our text only, never submitted content) and written when the app starts.
- **Script:** one, `page.js`, on claimset and specification pages: it marks the section being read in the contents (and on a phone shows it in a bar that opens the contents), opens a figure over the page with its caption, and copies the reading-view address for an AI assistant. Without it the contents link to every section, a figure's link opens the image, and the assistant link opens the reading view.
- **Stylesheets and the script** are linked with a version from their content (`/site.css?v=…`) and cached for a year, so a browser or Cloudflare never pairs a new page with an old stylesheet.
- **Assistants given a page:** an AI assistant whose fetcher names itself (ChatGPT-User, Claude-User, Perplexity-User, Google's URL-context and Gemini Notebook fetchers and others), or any client asking for `text/plain` or `text/markdown` first, gets the reading view at the page's own address (Caddy). Search crawlers get the page. Every page also names its reading view in a `Link` header.
- **Maths and code:** the claimset package writes formulae as MathML (no script); the site serves STIX Two Math for them. `code` in text is set as code.
- **For models:** the claimset page has "Copy the link for your AI assistant", which copies its reading-view address: some assistants open only addresses they are given, never links found in a page (Gemini refused the page's `.json` and `.txt` links). `/robots.txt` allows every reader and program, with `Content-Signal: search=yes, ai-input=yes`; the training signal is the owner's decision, still to be made.
- **Subfield:** a valid `paper.classification.subfield` proposed by the submission is kept (claimset spec §3.1: the agent may propose it) and shown on the consent page; `/subfields.json` lists OpenAlex's subfields for agents. Otherwise the classifier's subfield is the one with the most weight across its topics, not only the best topic's. `validation.json` records who chose it.
- **References by DOI** are written out at publication from Crossref (`crossref.py`, kept in `doi_metadata`), so pages show author (year) and the full reference; the published file keeps the DOI. Needs claimset 0.40.4 (`ref_text`); with an older one the page shows the DOI.

### 7.5 Retraction and removal

Decided 9 November 2026 (§15 Q5; portal issue #47). The form is at `/removal`, rendered by the app.

- **The guarantor** signs in with ORCID (the same callback as consent); if the iD is a guarantor of the current version, the request is applied at once. **Anyone else** gives an email address and their grounds; EntryLib reviews (`portal requests`, `portal decide <id> apply|decline`), and the notice then names EntryLib. The email and grounds are deleted when the request closes; a guarantor's request never confirmed is deleted after a day.
- **Reasons** come from a list ending with Other, which needs the requester's own words. Those words are screened (§6), shown as text only, and limited in length.
- **Retract:** the claimset stays, with `status: retracted` and a `status_notice` saying who, when and why, assigned by the platform (claimset spec §9) on every version as served: pages, JSON, reading views, search and `versions.json`. The registry's files are unchanged.
- **Remove:** the claimset's pages, files, bundles, citations and packaged files no other claimset uses are deleted, and each of its addresses answers with the notice (HTML, JSON, text). It leaves search and the listings; its identifier is never given again.
- **Registry:** one commit adds or extends `<folder>/notices.json` and, for a removal, deletes the claimset's versions; history is not rewritten. In github mode it is a pull request that the registry's check (§6) accepts only when it appends exactly one valid notice and, for a removal, deletes every version file and nothing else. `reindex` rebuilds retractions and removals from these files.
- **Served:** what readers find is the claimset specification's (§9): a retracted claimset with `status: retracted` and its `status_notice`; a removed one as `{"id", "status": "removed", "notice"}`. The rest (who may act, the reasons, `notices.json`) is EntryLib's policy, kept here and not in the specifications.

`notices.json`, in the claimset's registry folder, next to its versions:

```json
{"id": "entrylib:2026.000123",
 "notices": [{"action": "retracted", "date": "2026-11-10", "reason_code": "error_in_results",
              "reason": "Error in the results", "statement": "Table 2 reports the training error, not the test error.",
              "issued_by": "A. Researcher (ORCID 0000-0002-1825-0097)",
              "by": {"name": "A. Researcher", "orcid": "0000-0002-1825-0097"}, "versions": [1, 2]}]}
```

- `action`: `retracted` or `removed`. `reason_code`: from the lists in `notices.py` (each ends with `other`); `reason`: its name; `statement`: the requester's own words, possibly empty (required with `other`).
- `issued_by`: who acted, as readers see it: the guarantor by name and ORCID iD, or `EntryLib` after review; `by`: the guarantor's name and iD, or `null`. `versions`: the versions the claimset had when the notice was added.
- Notices are only appended, one per commit. A retraction changes nothing else. A removal deletes every file of every version, so the folder keeps only `notices.json`, and no notice may follow it.

### 7.6 Scores

Scores follow EntryLib's scoring rubric (github.com/entrylib/rubric, `RUBRIC.md`), installed from GitHub with the rubric's scorer and updated when the app starts, like claimset; the portal applies it and never sets costs of its own. In short: a **reliability** score from 0 to 100 for every claim that is not an assumption, computed by rules from the published file, each lost point naming its problem and what would remove it; the paper's is its lowest principal claim's. **Novelty** is the authors' label with a close-match check against the claims of claimsets published before this one (candidates found by the portal's full-text search, the match decided by the rubric).

- **On the page:** the panel shows the paper's reliability large, coloured by band (High 80+, Medium 60–79, Low under 60) and named, and novelty small and uncoloured. Every claim shows its score and five dots (support, plan, checkable, context, open problems), each dot explained on hover; clicking a score opens its explanation in a pop-up (`page.js`). The section *Score* at the end of the page holds the paper's explanation, so it can be linked and read without the script. The explanation says that scores are computed by rules from the file and may change as the rubric and reviews develop.
- **For programs:** `/p/<key>@v<n>.score.json` (and `/p/<key>.score.json` for the current version) holds the scores, their problems and the rubric version; `/p/<key>@v<n>.issues.txt` lists every issue that lowers a score, with what would fix it, for the authors' agent preparing the next version (linked from the panel and the section *Score*); the reading view ends with the scores in text. Lists of claimsets (home, all, search) show each paper's reliability.
- **When they change:** pages are rewritten when the rubric version changes (it is part of the marker of §7.1), so scores follow the current rubric. Without the rubric installed the page shows "–".

### 7.7 Read

`/read` (the menu's Read) shows what EntryLib holds. Rendered by the app, without scripts:

- **A tree** of OpenAlex domains, fields and subfields (`data/fields.json`, `data/subfields.json`), only the parts that have claimsets, each with how many. A claimset is in the subfield of its classification.
- **For the part chosen** (or everything): its **principal claims** by default, or all claims (a switch), or its **claimsets** as cards. Each claim shows its reliability, dots and novelty, and links to its claimset.
- **Filters:** claim type, novelty label, planned or exploratory, reliability band; **sort** by reliability or newest; 50 a page. Search (`/search`) stays at the top.
- Scores come from the rubric over each current file, kept in memory per version and rubric version; when the library grows, the indexer should store them in the database instead.

## 8. Limits and spam controls

| Limit | Value (initial) |
|---|---|
| Consent window | 48 hours, then deletion |
| New claimsets | 2 per ORCID iD in any seven days, counted against every confirming guarantor (20 while the library is seeded) |
| New versions (corrections now, revisions from v2) | 3 per claimset in any day (10 while the library is seeded) |
| Pending submissions | 5 per address at once |
| Reads: search, submission status, every MCP request | 120 per minute per address |
| Validation (`/api/validate`, MCP `validate`) | 30 per hour per address |
| Submissions (`/api/submissions`, MCP `submit`) | 20 per hour per address |
| Submissions by URL (`/api/submissions/from-url`, MCP `submit` with `package_url`) | 10 per hour per address, and 2 downloads at once across everyone |
| Package size | rule 77: 200 files, 50 MB a file, 200 MB in all |

- The per-address limits are token buckets kept in the app's memory (`ratelimit.py`): the app is one process, and a restart only forgets them. A request over a limit gets 429 with `Retry-After`; a download refused because two are running gets 503. Cloudflare limits at the edge as well, but only the app knows what a request costs.
- The address is the client's, not Cloudflare's: Caddy takes it from `CF-Connecting-IP` on requests from Cloudflare's address ranges only, and passes the app that one address in `X-Forwarded-For`, so it cannot be forged by sending the header or by going around Cloudflare. The ranges are in the Caddyfile; they change rarely and are updated by hand.
- The limits on new claimsets and versions limit publication, not confirmation. A guarantor over the limit still confirms: the submission is kept, confirmed, and published automatically when the earliest publication counted against it leaves the window (`publish_after`); the confirmation page and the status say when and why. A publication already scheduled counts at its scheduled time. So a confirmation is never lost to the 48-hour consent window. Both limits are set by `PORTAL_MAX_NEW_PER_WEEK` and `PORTAL_MAX_VERSIONS_PER_DAY`; the defaults are raised while EntryLib is seeded and return to 2 and 3 once others submit.
- ORCID iDs found abusing the service can be suspended (PLT-94). Consent is needed before anything is published, so unconfirmed spam costs validation only.

## 9. Notices and legal removal

Published versions are never withdrawn. Problems are marked with notices attached to a version: correction, expression of concern, retraction notice (PLT-91), each with a reason code and statement. The content stays available.

The one exception is legal: personal data, infringing or unlawful content. Such content is hidden, leaving a tombstone with the hash, date and reason. The policy is published.

## 10. Security

- Secrets in environment variables, never in the repository. Dependabot on the portal repo.
- Database reachable only from the app.
- The portal acts on GitHub as the EntryLib GitHub App, installed on the registry only, with contents and pull requests write access. Its private key is a file given to the portal as a Docker secret; installation tokens last an hour.
- The validator runs with time and memory limits; zips are unpacked with the limits of §4.1.
- Submitted content is never rendered as HTML: the pages show it escaped. Packaged files are served in a sandbox, never run: images are shown, other files downloaded.
- No access log: readers' IP addresses are used in memory for the limits only (§8), and a submission's address is deleted when it closes.
- The registry's check runs on every pull request, but merges happen only through the App, and only for pull requests it opened. If the LLM screening is switched on, its API key must be given only to runs on the App's own branches, never to pull requests from forks.

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

One DigitalOcean Droplet in the London region with at least 4 GB RAM, set up by `deploy/cloud-init.yaml` and `deploy/server-setup.sh` and started by `deploy/launch.sh` (`docs/deploy.md`), running Docker Compose: the app, PostgreSQL with pgvector, and Caddy for HTTPS and static files. DigitalOcean's daily Droplet backups (crash-consistent disk images of everything on the Droplet: database, packaged files, pending submissions; volumes are not included, so nothing is kept on one). The published record is also the registry on GitHub, from which `reindex` rebuilds the database. DigitalOcean Spaces may later store packaged files. Cloudflare's free tier in front for DDoS protection and edge rate limits. DigitalOcean's managed PostgreSQL supports pgvector, so the database can move there later without code changes.

## 14. Requirements covered

PLT-2 (ORCID at consent only), PLT-10 (BagIt packages), PLT-11, PLT-12, PLT-13, PLT-14, PLT-15, PLT-16, PLT-18, PLT-19 (duplicates by the same guarantor), PLT-21, PLT-22, PLT-23, PLT-70, PLT-71, PLT-72 (closed-vocabulary filters), PLT-73, PLT-74 (in part), PLT-76 (minimal), PLT-78, PLT-79, PLT-91, PLT-94.

Changed by this design: PLT-1 and PLT-3 to PLT-5 (accounts and agent tokens) are dropped for v1. Guarantors sign in with ORCID only to confirm; agents submit without tokens.

## 15. Open questions

1. **Domain.** Settled: entrylib.org. The production ORCID client will use the redirect URI https://entrylib.org/consent/callback.
2. **Paid accounts.** Publishing stays free. Candidates: higher read quotas on the API and MCP; higher submission quotas for verified organisations; private pre-submission checks, including a preview of the v2 reviewer's comments; bulk export.
3. **Several guarantors.** Whether 48 hours is enough when guarantors are in different time zones, or whether the window restarts when the first confirms.
4. **ORCID works.** Writing works to ORCID records needs ORCID membership. Until v3 brings DOIs and DataCite auto-update, guarantors add claimsets to their records by hand; the consent page says how.
5. **Legal removal policy:** who decides, the response time, and the tombstone format.
6. **Embedding model:** settled for launch: none; search is full text (§7.2). Which model, and when to re-embed if it changes, is decided when embeddings are added.
7. **Related work.** A head-to-head comparison with Knows (knows.academy), aiXiv and paper.json before any funding application.

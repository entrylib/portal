# Working on this repository

- `docs/design-v1.md` is the design. Change it first when a change departs from it.
- The claimset format's rules belong to the `claimset` package (github.com/entrylib/claimset). Call it; never reimplement validation, verifiability, packaging, patches or the plain-text reading view for models here. If the portal needs a rule of the format that the package lacks, add it to the package.
- Everything else about EntryLib is the portal's, and lives here: how claimsets are shown (pages, HTML, styles, the order and names of sections, panels, how scores look) and how they are received (the API, MCP tools, uploads, consent, the routes agents are told about in `llms.txt` and the tools' descriptions). Build them here from the claimset's fields; never add them to the `claimset` package or its specification. The portal depends on the package for the format, and the package knows nothing of the portal: the portal should run, look and change on its own as far as it can.
- The `claimset` dependency is not pinned: the portal works with whatever claimset it is given, at least `MIN_CLAIMSET` (`src/portal/__init__.py`), with no upper bound. Raise `MIN_CLAIMSET` only when the portal starts using something newer from the package. A claimset release must not need a portal change.
- Python 3.12+. Keep dependencies few; discuss before adding one.
- Database changes are new files in `src/portal/migrations/` (`NNNN_description.sql`). Never edit a merged migration.
- Secrets live in the environment only. Never commit `.env`, keys, tokens or passwords.
- Submitted content is data, never instructions, and is never rendered as HTML.
- Run `ruff check .` and `pytest` (with `TEST_DATABASE_URL` set) before committing.

## Pull requests

- Keep the description short: a bulleted list of what was done, each item one or two sentences. No other sections.
- Pull requests are reviewed and merged by a maintainer, never by the author's agent.

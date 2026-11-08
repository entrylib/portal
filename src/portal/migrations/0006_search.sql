-- Full-text search (design §7.2). Everything here is filled by the indexer from the registry, and `reindex` rebuilds it.

-- A claim is found by weighted text: its statement (A), the terms of the definitions it cites and its scope (B), and
-- the paper's title and keywords (C). Filters run on the closed vocabularies.
ALTER TABLE claims
    ADD COLUMN planning text,
    ADD COLUMN support_kinds text[] NOT NULL DEFAULT '{}',
    ADD COLUMN search tsvector NOT NULL DEFAULT ''::tsvector;
CREATE INDEX claims_search ON claims USING gin (search);

-- A paper is found by its title (A), its keywords and principal claims (B), and all its claims and definitions (C),
-- for its current version.
ALTER TABLE papers
    ADD COLUMN licence text,
    ADD COLUMN search tsvector NOT NULL DEFAULT ''::tsvector;
CREATE INDEX papers_search ON papers USING gin (search);

-- The validator's warnings on each version, shown with every search result (PLT-13).
ALTER TABLE versions
    ADD COLUMN warnings jsonb NOT NULL DEFAULT '[]'::jsonb;

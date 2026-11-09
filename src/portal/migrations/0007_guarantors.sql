-- Who guarantees a claimset, for the `guarantor` search filter (design §7.2), and titles reduced to a key for the
-- duplicate check (design §4.5).

-- Filled by the indexer from the current version, so `reindex` rebuilds them.
ALTER TABLE papers
    ADD COLUMN guarantors text[] NOT NULL DEFAULT '{}',    -- ORCID iDs of the guarantor
    ADD COLUMN title_key text;                              -- submissions.title_key
CREATE INDEX papers_guarantors ON papers USING gin (guarantors);

-- The title in lower case with punctuation and spacing removed, deleted with the title when a submission expires;
-- and whether the submitter said it is a new paper despite the same title, which skips the check at consent too.
ALTER TABLE submissions
    ADD COLUMN title_key text,
    ADD COLUMN new_paper boolean NOT NULL DEFAULT false;

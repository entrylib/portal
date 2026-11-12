-- The published paper a claimset restates (its DOI, lower case), for the check that a paper is claimed once and by
-- its authors (design §4.5). Filled by the indexer from the current version, so `reindex` rebuilds it.
ALTER TABLE papers ADD COLUMN source_doi text;
CREATE INDEX papers_source_doi ON papers (source_doi) WHERE source_doi IS NOT NULL;
ALTER TABLE submissions ADD COLUMN source_doi text;

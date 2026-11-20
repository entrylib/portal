-- Read from the index (design §7.7): what Read filters, sorts and counts by, so that it no longer loads every
-- paper's file on each visit. The indexer keeps them (indexer.index_version, indexer._store_scores).
ALTER TABLE papers ADD COLUMN domain text, ADD COLUMN field text, ADD COLUMN subfield text,
    ADD COLUMN score integer, ADD COLUMN band text;
ALTER TABLE claims ADD COLUMN position integer, ADD COLUMN listed boolean NOT NULL DEFAULT true,
    ADD COLUMN score integer, ADD COLUMN band text;
CREATE INDEX papers_area ON papers (domain, field, subfield);

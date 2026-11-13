-- Claim search over the current versions only, through an index of their claims (design §7.2): the claims table
-- holds every version's claims, and joining each to its paper's current version made Postgres read every current
-- claim instead of using the full-text index. The indexer keeps `is_current` (indexer.index_version).
ALTER TABLE claims ADD COLUMN is_current boolean NOT NULL DEFAULT false;
UPDATE claims c SET is_current = true FROM papers p WHERE p.concept_id = c.concept_id AND p.current_version = c.version;
CREATE INDEX claims_search_current ON claims USING gin (search) WHERE is_current;

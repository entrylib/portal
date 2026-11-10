-- Submissions over a publication limit are refused, not scheduled (design §8): the column of 0012 is not used.
ALTER TABLE submissions DROP COLUMN IF EXISTS publish_after;

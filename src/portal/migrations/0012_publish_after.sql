-- A confirmed submission over a guarantor's limit is published when the limit allows, not refused (design §8).
ALTER TABLE submissions ADD COLUMN publish_after timestamptz;

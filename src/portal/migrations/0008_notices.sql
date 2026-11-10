-- Retraction and removal (design §7.5, portal issue #47). A request names a claimset, an action and a reason. The
-- guarantor's request is confirmed by signing in with ORCID and acted on at once; anyone else's waits for review.
--   signin     waiting for the guarantor's ORCID sign-in (deleted after a day if it never comes)
--   review     waiting for EntryLib's decision
--   confirmed  to be applied: written to the registry, then to the site
--   publishing its registry pull request is open (github mode)
--   applied    done; declined: refused on review; failed: the registry refused it
CREATE TABLE notice_requests (
    id text PRIMARY KEY,                    -- rq_<random>
    concept_id text NOT NULL,               -- entrylib:2026.000001
    action text NOT NULL CHECK (action IN ('retract', 'remove')),
    reason_code text NOT NULL,
    statement text NOT NULL DEFAULT '',     -- the requester's own words, shown in the notice as text
    state text NOT NULL CHECK (state IN ('signin', 'review', 'confirmed', 'publishing', 'applied', 'declined',
                                         'failed')),
    by_orcid text,                          -- the guarantor who signed in
    by_name text,
    contact text,                           -- someone else's email, for the review; deleted when the request closes
    grounds text,                           -- someone else's grounds and evidence; deleted when the request closes
    received timestamptz NOT NULL DEFAULT now(),
    decided timestamptz,
    detail text,                            -- why it was declined or failed
    registry_pr integer,
    registry_branch text
);
CREATE INDEX notice_requests_state ON notice_requests (state);

-- ORCID sign-in started from the removal form; the `state` ties ORCID's callback to the request, and is used once.
CREATE TABLE notice_signins (
    state text PRIMARY KEY,
    request_id text NOT NULL REFERENCES notice_requests ON DELETE CASCADE,
    started timestamptz NOT NULL DEFAULT now(),
    used timestamptz
);

-- Removed claimsets: their identifiers keep resolving to the notice. An index of the registry's notices.json files,
-- rebuilt by reindex.
CREATE TABLE removed (
    concept_id text PRIMARY KEY,
    url_key text NOT NULL UNIQUE,
    notice jsonb NOT NULL
);

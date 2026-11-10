-- Confirming without the consent link (design §4.2): the guarantor signs in with ORCID at /confirm and sees the
-- submissions that name them. One row per sign-in started there; the OAuth `state` is used once.
CREATE TABLE confirm_signins (
    state text PRIMARY KEY,
    started timestamptz NOT NULL DEFAULT now(),
    used timestamptz
);

-- After that sign-in, each submission listed gets a ticket: a one-time secret behind its Confirm button, bound to the
-- submission and the ORCID iD that signed in, valid for a short while. Only its hash is kept.
CREATE TABLE confirm_tickets (
    ticket_hash text PRIMARY KEY,
    submission_id text NOT NULL REFERENCES submissions ON DELETE CASCADE,
    orcid text NOT NULL,
    expires timestamptz NOT NULL,
    used timestamptz
);

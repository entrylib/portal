-- Sign-in sessions (design §4.2): after an ORCID sign-in, Your submissions opens without signing in again while the
-- session lasts. Only a hash of the cookie's token is kept; a session names the iD that signed in and nothing else.
CREATE TABLE signin_sessions (
    token_hash text PRIMARY KEY,
    orcid text NOT NULL,
    name text,
    started timestamptz NOT NULL DEFAULT now(),
    expires timestamptz NOT NULL
);
CREATE INDEX signin_sessions_expires ON signin_sessions (expires);

-- Upload addresses (design §4.4): an agent that reaches EntryLib through MCP sends its package to a one-time address,
-- so the file never passes through the model. Only the hash of the address's secret is kept; the file lies under the
-- submissions directory until it is submitted or the address expires.
CREATE TABLE uploads (
    token_hash text PRIMARY KEY,
    created timestamptz NOT NULL DEFAULT now(),
    expires timestamptz NOT NULL,
    client_ip inet,
    file_name text,                     -- under <submissions>/uploads, once received
    size bigint,
    received timestamptz
);
CREATE INDEX uploads_expires ON uploads (expires);

-- A submission sent without the files its artefacts name, for the guarantor to attach with their consent (design
-- §4.4): it cannot be confirmed until the package is attached.
ALTER TABLE submissions ADD COLUMN waiting_package boolean NOT NULL DEFAULT false;

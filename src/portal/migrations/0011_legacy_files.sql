-- Packaged files stored by checksum before November 2026 (`/files/<sha256>`) moved into their claimset's folder
-- (storage.py). Each old address answers with a redirect to where its file now is. Rebuilt by reindex.
CREATE TABLE legacy_files (
    sha256 text PRIMARY KEY,
    path text NOT NULL                     -- /p/2026.000001/v1/files/A3.png
);

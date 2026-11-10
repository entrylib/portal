-- What Crossref says about the DOIs claimsets cite (crossref.py): authors, year, title and where, so that pages show
-- references as author (year). NULL summary: Crossref did not know the DOI when asked (`fetched`).
CREATE TABLE doi_metadata (
    doi text PRIMARY KEY,                  -- lower case, without doi: or https://doi.org/
    summary jsonb,
    fetched timestamptz NOT NULL
);

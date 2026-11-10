#!/bin/sh
# Start the portal with the newest claimset (design §10). Set PORTAL_CLAIMSET_UPDATE=0 to skip the update.
set -u
if [ "${PORTAL_CLAIMSET_UPDATE:-1}" != "0" ]; then
  # From PyPI: a release has a new version number, so --upgrade installs it and leaves an unchanged one alone. Only
  # claimset is updated (--no-deps): a few seconds.
  pip install --user --quiet --upgrade --no-deps "claimset>=0.40.1" \
    || echo "portal: could not update claimset; using the installed one" >&2
fi
exec portal serve --port 8000

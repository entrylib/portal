#!/bin/sh
# Start the portal with the newest claimset and scoring rubric (design §10, §7.6). Set PORTAL_CLAIMSET_UPDATE=0
# to skip the updates.
set -u
if [ "${PORTAL_CLAIMSET_UPDATE:-1}" != "0" ]; then
  # From PyPI: a release has a new version number, so --upgrade installs it and leaves an unchanged one alone. Only
  # claimset is updated (--no-deps): a few seconds.
  pip install --user --quiet --upgrade --no-deps "claimset>=0.41.6" \
    || echo "portal: could not update claimset; using the installed one" >&2
  # The scoring rubric, from PyPI as claimset is (design §7.6): its version, recorded with every score, rebuilds the
  # pages when it changes.
  pip install --user --quiet --upgrade --no-deps "entrylib-rubric>=0.4" \
    || echo "portal: could not update the rubric; using the installed one" >&2
fi
exec portal serve --port 8000

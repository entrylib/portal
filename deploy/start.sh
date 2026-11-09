#!/bin/sh
# Start the portal with the newest claimset (design §10). Set PORTAL_CLAIMSET_UPDATE=0 to skip the update.
set -u
if [ "${PORTAL_CLAIMSET_UPDATE:-1}" != "0" ]; then
  # --force-reinstall: pip decides by version number, so without it a change merged into claimset without a version
  # bump would never be installed. Only claimset is reinstalled (--no-deps): a few seconds.
  pip install --user --quiet --upgrade --force-reinstall --no-deps \
      "claimset @ git+${PORTAL_CLAIMSET_SOURCE:-https://github.com/entrylib/claimset}" \
    || echo "portal: could not update claimset; using the installed one" >&2
fi
exec portal serve --port 8000

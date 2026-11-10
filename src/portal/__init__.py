"""EntryLib: the portal that publishes claimsets."""

__version__ = "0.1.0"

#: The oldest claimset package the portal works with. There is no upper bound: newer releases are expected to
#: accept everything older ones accepted.
MIN_CLAIMSET = "0.40.1"                  # the page view (claimset.html); accepts claimset spec v0.40 and older


def claimset_ok(version):
    """True if the installed claimset package is at least MIN_CLAIMSET."""
    def parts(v):
        return tuple(int(x) for x in v.split("+")[0].split(".")[:3] if x.isdigit())
    return parts(version) >= parts(MIN_CLAIMSET)

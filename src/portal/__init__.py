"""EntryLib: the portal that publishes claimsets."""

__version__ = "0.14.0"

#: The oldest claimset package the portal works with. There is no upper bound: newer releases are expected to
#: accept everything older ones accepted.
MIN_CLAIMSET = "0.44.19"                 # claimset.views: the split views, with each claim's score in the overview


def claimset_ok(version):
    """True if the installed claimset package is at least MIN_CLAIMSET."""
    def parts(v):
        return tuple(int(x) for x in v.split("+")[0].split(".")[:3] if x.isdigit())
    return parts(version) >= parts(MIN_CLAIMSET)

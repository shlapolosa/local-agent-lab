"""Third-party browser assets the lab SERVES rather than fetches — one copy, read by whoever draws.

Vendored, not linked, and that is a measured requirement rather than caution: a page written into the
tenant's SharePoint library runs our inline JavaScript but is REFUSED an external script (probed live on
10 Oct 2026 — inline script and script-drawn SVG both ran; `cdnjs.cloudflare.com` did not load). A view
that reaches for a CDN therefore renders as an empty box in the one place the fabric publishes it, with
no error anybody sees. Every renderer inlines what it needs from here.

It lives in `lab.core` because two tiers draw with it — the use-case views and the fabric's topology
renderer — and a second copy of 280 KB of minified D3 is exactly the duplication that drifts.
"""
from importlib import resources

__all__ = ["d3"]


def d3() -> str:
    """The D3 v7 bundle, as source to inline in a `<script>`. ISC licensed — see `D3_LICENSE.txt`."""
    return resources.files(__name__).joinpath("d3.min.js").read_text()

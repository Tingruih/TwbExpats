"""
Jinja2 environment configuration for static site generation.

URL strategy: all URLs are absolute-path URLs rooted at *base_url*.
For GitHub Pages sub-path deployment, pass base_url="/repo/".
"""

import json
import os
from urllib.parse import urljoin
from decimal import Decimal, ROUND_HALF_UP

from jinja2 import Environment, FileSystemLoader, select_autoescape
from markupsafe import Markup

from .levels import level_display, is_mlb

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_TEMPLATE_DIR = os.path.join(_PROJECT_ROOT, "src", "templates")


# ── Custom Filters ──


def floatformat(value, digits=2):
    """Format a numeric value with fixed decimal places, or '-' for None."""
    if value is None:
        return "-"
    try:
        return f"{float(value):.{int(digits)}f}"
    except Exception:
        return "-"


def default_if_none(value, fallback="-"):
    """Return *fallback* when *value* is None."""
    return fallback if value is None else value


def num_dash(value):
    """Display a number or '-' for None / empty."""
    if value is None or value == "":
        return "-"
    return value


def slice_prefix(value, n):
    """Return the first *n* characters of a string."""
    if not value:
        return ""
    return str(value)[:n]


def _json_html_safe(s: str) -> str:
    # Prevent </script> from closing the enclosing script tag.
    return s.replace("</", "<\\/")


def tojson_safe(value):
    """Serialize to JSON and mark safe for embedding in <script>."""
    return Markup(_json_html_safe(json.dumps(value, ensure_ascii=False)))


def jsonld(value):
    """Serialize compact JSON-LD and mark safe for embedding in <script>."""
    return Markup(_json_html_safe(json.dumps(value, ensure_ascii=False, separators=(",", ":"))))


def pct_fmt(value, digits=1):
    """Format a decimal fraction (e.g. 0.345) as a percentage string (34.5%).

    Returns '-' for None.  Commonly used for Statcast percentages stored as
    0.XXX in the database.
    """
    if value is None:
        return "-"
    try:
        places = Decimal("1").scaleb(-int(digits))
        pct = (Decimal(str(value)) * Decimal("100")).quantize(
            places, rounding=ROUND_HALF_UP
        )
        return f"{pct:.{int(digits)}f}%"
    except Exception:
        return "-"


# ── URL Factories ──

# MLB Photos (Cloudinary-backed) headshot CDN. Photos are split into two
# asset families that don't overlap: "67" is the MLB-roster headshot (set the
# day a player gets an official MLB photo day), "milb" is the MiLB-roster
# headshot (set via MiLB's own media pipeline). A player only ever has one of
# the two until they cross levels for the first time, so callers must try
# both — see `headshot_cdn_urls`.
HEADSHOT_CDN_TEMPLATE_MLB = (
    "https://img.mlbstatic.com/mlb-photos/image/upload/"
    "w_180,q_auto:best/v1/people/{mlb_id}/headshot/67/current"
)
HEADSHOT_CDN_TEMPLATE_MILB = (
    "https://img.mlbstatic.com/mlb-photos/image/upload/"
    "w_180,q_auto:best/v1/people/{mlb_id}/headshot/milb/current"
)


def headshot_cdn_urls(mlb_id, has_reached_mlb):
    """Return (primary, secondary) headshot CDN URLs, ordered by which tier
    is more likely to exist for this player.

    A player who has ever appeared in an MLB game has an MLB-tier photo;
    everyone else only has a MiLB-tier photo. Trying the likely tier first
    means the common case resolves on the first request.
    """
    mlb_url = HEADSHOT_CDN_TEMPLATE_MLB.format(mlb_id=mlb_id)
    milb_url = HEADSHOT_CDN_TEMPLATE_MILB.format(mlb_id=mlb_id)
    return (mlb_url, milb_url) if has_reached_mlb else (milb_url, mlb_url)


def _make_url_helpers(base_url: str):
    base = base_url.rstrip("/")

    def player_url(mlb_id):
        return f"{base}/player/{mlb_id}/"

    def retired_player_url(mlb_id):
        return f"{base}/retired/player/{mlb_id}/"

    def static_url(path):
        return f"{base}/static/{path}"

    return player_url, retired_player_url, static_url


def _make_absolute_url(site_origin: str, base_url: str):
    site_root = urljoin(site_origin.rstrip("/") + "/", base_url.lstrip("/"))

    def absolute_url(path=""):
        return urljoin(site_root, str(path).lstrip("/"))

    return site_root, absolute_url


# ── Environment Factory ──


def create_jinja_env(
    template_dir=None,
    base_url="/",
    site_origin="https://tingruih.github.io",
):
    """Create and return a configured Jinja2 Environment."""
    tpl_dir = template_dir or _TEMPLATE_DIR

    if not base_url.startswith("/"):
        base_url = "/" + base_url
    if not base_url.endswith("/"):
        base_url = base_url + "/"

    player_url, retired_player_url, static_url = _make_url_helpers(base_url)
    site_url, absolute_url = _make_absolute_url(site_origin, base_url)

    env = Environment(
        loader=FileSystemLoader(tpl_dir),
        autoescape=select_autoescape(["html", "j2"]),
        trim_blocks=True,
        lstrip_blocks=True,
    )

    env.filters["floatformat"] = floatformat
    env.filters["default_if_none"] = default_if_none
    env.filters["num_dash"] = num_dash
    env.filters["slice_prefix"] = slice_prefix
    env.filters["tojson_safe"] = tojson_safe
    env.filters["jsonld"] = jsonld
    env.filters["pct_fmt"] = pct_fmt
    env.filters["level_display"] = level_display

    env.globals["is_mlb"] = is_mlb
    env.globals["player_url"] = player_url
    env.globals["retired_player_url"] = retired_player_url
    env.globals["static_url"] = static_url
    env.globals["headshot_cdn_urls"] = headshot_cdn_urls
    env.globals["absolute_url"] = absolute_url
    env.globals["base_url"] = base_url
    env.globals["site_url"] = site_url
    env.globals["site_origin"] = site_origin.rstrip("/")

    return env

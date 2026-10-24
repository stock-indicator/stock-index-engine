"""Reddit retail-buzz velocity from the public Atom feed.

Reddit's JSON endpoints are WAF-blocked for anonymous clients, but the Atom
feed at ``/r/{subs}/new.rss`` is served to an identified User-Agent and needs
no key, no OAuth and no registration.

Why velocity rather than a post count
-------------------------------------
A single feed page is capped at 100 entries, so counting posts saturates the
moment a subreddit is busy — exactly the condition we care about. The
timestamp span of that page does not saturate: 100 posts covering 2 hours is
~1200 posts/day, the same 100 posts covering 12 hours is ~200/day. Measuring
the rate reads the busy end of the range correctly, which a count cannot.

Retail posting velocity is a contrarian signal: it spikes into euphoric tops
and into panic, and goes quiet in the long grind between them.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from typing import Dict, List, Optional

from common.logger import get_logger

from .http import SourceUnavailable, fetch

LOGGER = get_logger("social.reddit")

_FEED = "https://www.reddit.com/r/{subs}/new.rss"
_ATOM_NS = {"atom": "http://www.w3.org/2005/Atom"}

# Ordered roughly by signal density for market chatter. wallstreetbets carries
# the most volume and the most noise, and is the one that actually moves when
# retail gets excited; stocks and investing trend more measured and act as a
# baseline. Combined into one request with Reddit's "+" multireddit syntax.
DEFAULT_SUBREDDITS = ("wallstreetbets", "stocks", "investing")

# Reddit's maximum page size.
_PAGE_LIMIT = 100

# Below this many entries the span is too short to extrapolate a daily rate
# from — a half-empty page means the feed itself was truncated or the
# subreddit is genuinely dead, and neither extrapolates honestly.
_MIN_ENTRIES = 20


def _published_at(entry: ET.Element) -> Optional[datetime]:
    """An entry's ``published`` timestamp as an aware UTC datetime."""
    node = entry.find("atom:published", _ATOM_NS)
    if node is None or not node.text:
        return None
    raw = node.text.strip()
    try:
        normalized = raw[:-1] + "+00:00" if raw.endswith("Z") else raw
        return datetime.fromisoformat(normalized).astimezone(timezone.utc)
    except (TypeError, ValueError):
        return None


def _reject_doctype(body: bytes) -> None:
    """Refuse a feed carrying a DOCTYPE, before it reaches the XML parser.

    ``xml.etree`` expands internal entities, so a hostile feed could ship a
    small body that expands to gigabytes (the "billion laughs" attack) -- the
    byte cap in http.py bounds the download, not the expansion. Entities
    require a DOCTYPE and a legitimate Atom feed never carries one, so
    rejecting it closes the hole without pulling in defusedxml.
    """
    if b"<!DOCTYPE" in body.upper():
        raise SourceUnavailable("Reddit feed carries a DOCTYPE; refusing to parse")


def _parse_entries(body: bytes) -> List[datetime]:
    """Publication timestamps of every parseable entry in the feed."""
    _reject_doctype(body)
    try:
        root = ET.fromstring(body)
    except ET.ParseError as exc:
        raise SourceUnavailable(f"Reddit feed is not valid Atom: {exc}") from exc
    stamps = [_published_at(e) for e in root.findall("atom:entry", _ATOM_NS)]
    return [s for s in stamps if s is not None]


def fetch_reddit_velocity(
    subreddits: tuple = DEFAULT_SUBREDDITS,
    timeout: float = 15.0,
) -> Dict[str, object]:
    """Posting velocity across ``subreddits``, as a snapshot of right now.

    Returns:
        A dict with ``posts_per_hour``, the ``sample_size`` it was derived
        from, the ``span_hours`` that sample covered, and ``as_of``.

    Raises:
        SourceUnavailable: the feed could not be fetched or parsed, or came
            back too short to extrapolate from. Never returns a zero rate to
            stand in for a failed fetch.
    """
    subs = "+".join(subreddits)
    body = fetch(
        _FEED.format(subs=subs),
        params={"limit": _PAGE_LIMIT},
        accept="application/atom+xml",
        timeout=timeout,
        source="Reddit",
    )
    stamps = _parse_entries(body)
    if len(stamps) < _MIN_ENTRIES:
        raise SourceUnavailable(
            f"Reddit feed returned only {len(stamps)} dated entries for r/{subs}; "
            f"need {_MIN_ENTRIES} to estimate a rate"
        )

    newest, oldest = max(stamps), min(stamps)
    span_hours = (newest - oldest).total_seconds() / 3600.0
    if span_hours <= 0:
        raise SourceUnavailable(
            f"Reddit feed for r/{subs} has a zero-length time span"
        )

    # len(stamps) posts span the interval between the first and last, so the
    # rate is over len-1 gaps, not len.
    posts_per_hour = (len(stamps) - 1) / span_hours
    LOGGER.debug(
        "r/%s: %d entries over %.2fh -> %.1f posts/h",
        subs, len(stamps), span_hours, posts_per_hour,
    )
    return {
        "as_of": datetime.now(timezone.utc),
        "subreddits": subs,
        "posts_per_hour": round(posts_per_hour, 2),
        "sample_size": len(stamps),
        "span_hours": round(span_hours, 3),
    }

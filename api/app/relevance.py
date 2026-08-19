"""Deciding which board postings are worth storing at all.

Boards return everything a company is hiring for, worldwide — over a thousand postings across the
seeded watchlist, of which a few dozen are worth a look. Storing the rest costs nothing to fetch
but makes the stored data unreadable, so postings are filtered before they reach storage.

This is applied to a board's postings *before* ``reconcile`` sees them, not inside it. Reconcile
compares a board reading against what was stored last time, and handing it a filtered reading
keeps that comparison honest: everything stored passed the same filter, so an absence still means
the board dropped the posting rather than that the filter changed its mind.

Closure is inferred from absence, so a posting that never gets stored can never be reported as
closed. Every rule here therefore has to earn its place: filtering too hard silently blinds the
signal the tracker exists to produce.

Seniority is judged only where a title states it. "Senior Backend Engineer" is not a role for
someone a year into their career and there is nothing to weigh up. The reverse does not hold — a
title with no marker proves nothing, and plenty of what survives still asks for years of
experience in a body this module never reads. Sorting those out needs the description, which is a
separate step.
"""

import re
from collections.abc import Sequence
from enum import StrEnum

from app.boards import BoardPosting
from app.schemas import Region
from app.stack import tech_match

MIN_TECH_SCORE = 0.8
"""The share of a posting's named technologies that must already be known.

Chosen from the data rather than picked as a round number: across one full sweep, 80% left seven
postings, 70% left twelve and 60% left twenty. Seven is a shortlist a person actually reads.

Lowering it is the first thing to try when a sweep produces nothing — the constant exists to be
turned, and the stored descriptions mean every posting can be rescored without fetching anything.
"""

MAX_YEARS = 3
"""The most years of experience a posting may ask for.

Compared against the *lowest* figure a posting states, so a role wanting "3-5 years" is treated
as wanting three and survives.
"""

ISRAEL_FRAGMENTS = (
    "israel",
    "tel aviv",
    "tel-aviv",
    "tlv",
    "herzliya",
    "herzlia",
    "ramat gan",
    "petah tikva",
    "netanya",
    "ra'anana",
    "raanana",
    "hod hasharon",
    "jerusalem",
    "haifa",
    "rehovot",
    "beer sheva",
    "be'er sheva",
    "yokneam",
    "caesarea",
    "kfar saba",
    "or yehuda",
    "rosh ha'ayin",
)
"""Lower-case fragments that place a posting in Israel.

Cities are listed individually rather than trusting the country name, because the boards write
locations as free text and disagree with each other: the same city arrives as "Tel Aviv", "Tel
Aviv District, Israel", "Tel Aviv-Yafo, Gush Dan, Israel" and "TLV". Across one sweep that was 243
distinct strings, and roughly half the Israeli postings never name the country at all.
"""

REMOTE_FRAGMENTS = ("remote", "work from home", "anywhere")
"""Fragments that make a posting worth keeping regardless of the country attached to it.

A remote role advertised from elsewhere may still be open to Israel. Deciding that needs the
description read, so it is kept here rather than dropped now.
"""

SENIOR = re.compile(
    r"\b(senior|sr\.?|staff|principal|lead|leader|head|director|vp|chief|architect|"
    r"manager|expert|iii|iv)\b",
    re.I,
)
"""Titles that state the role is beyond someone early in their career.

Leadership words count as seniority markers rather than job families: a team lead, an engineering
manager and a principal engineer are all roles the posting itself puts out of reach, whatever
family they otherwise belong to.

Roman numerals are included because levelled titles ("Engineer III") say the same thing in a
different alphabet. Bare "V" is deliberately absent — a single letter matches too much for what it
would buy.
"""


class RoleFamily(StrEnum):
    """The kinds of role worth surfacing, chosen to match the stack actually worked in.

    A whitelist rather than a subtraction. Naming the families that fit is both narrower and more
    honest than matching every title containing "engineer" and then listing exceptions: QA,
    automation, data, security, IT, embedded and game roles are all engineering, none of them are
    a match, and as a whitelist they simply never appear rather than needing to be excluded one
    by one as they are discovered.
    """

    FULLSTACK = "fullstack"
    BACKEND = "backend"
    FRONTEND = "frontend"
    PLATFORM = "platform"
    SOFTWARE = "software"


FAMILY_PATTERNS: dict[RoleFamily, re.Pattern[str]] = {
    RoleFamily.FULLSTACK: re.compile(r"\bfull[ -]?stack\b", re.I),
    RoleFamily.BACKEND: re.compile(
        r"\b(back[ -]?end|server[ -]?side|python (developer|engineer)|"
        r"node(\.js)? (developer|engineer))\b",
        re.I,
    ),
    RoleFamily.FRONTEND: re.compile(r"\b(front[ -]?end|react (developer|engineer))\b", re.I),
    RoleFamily.PLATFORM: re.compile(
        r"\b(devops|dev ?sec ?ops|sre|site reliability|platform engineer|"
        r"infrastructure engineer|cloud engineer)\b",
        re.I,
    ),
    RoleFamily.SOFTWARE: re.compile(
        r"\b(software (engineer|developer)|sw engineer|programmer)\b",
        re.I,
    ),
}
"""How each family is recognised in a title.

Iterated in declaration order and the first match wins, so the order is the tie-break for titles
that answer to more than one pattern: "Full Stack Software Engineer" is reported as full stack,
which describes it better than software does.

Every pattern requires its family word to be doing real work in the title. Bare "engineer" and
bare "developer" are deliberately never enough on their own — they are exactly the words that let
"Solutions Engineer", "Sales Engineer", "Developer Advocate" and "Product Manager, Developer
Experience" through when the filter was a subtraction rather than a whitelist.
"""


def in_scope_location(location: str) -> bool:
    """Whether a location is somewhere worth seeing a job in.

    Args:
        location: The raw location text as the board wrote it.

    Returns:
        True for Israel and for anything advertised as remote.
    """
    text = location.lower()
    return any(fragment in text for fragment in ISRAEL_FRAGMENTS + REMOTE_FRAGMENTS)


def region(location: str) -> Region:
    """Which region a location places a posting in.

    Only ever asked of a stored posting, which has already passed ``in_scope_location``. A
    location naming nowhere in Israel is therefore in storage because it advertised as remote,
    which is why remote is the fallback rather than a case matched in its own right — an
    unrecognised Israeli spelling shows up as a remote role rather than as no answer at all.

    Israel wins where a location says both. "Remote — Tel Aviv" is a role that can be worked from
    home *in Israel*, and calling it remote would drop it out of the count of what is reachable
    locally, which is the count this field exists to make possible.

    Args:
        location: The raw location text as the board wrote it.

    Returns:
        ``Region.ISRAEL`` if the text names anywhere in Israel, ``Region.REMOTE`` otherwise.
    """
    text = location.lower()
    if any(fragment in text for fragment in ISRAEL_FRAGMENTS):
        return Region.ISRAEL
    return Region.REMOTE


def role_family(title: str) -> RoleFamily | None:
    """Which family of role a title describes, if any.

    Args:
        title: The posting's title as the board wrote it.

    Returns:
        The best-fitting family, or None if the title is not a role worth surfacing. None is the
        common answer: most of what a board lists is something else entirely.
    """
    for family, pattern in FAMILY_PATTERNS.items():
        if pattern.search(title):
            return family
    return None


def states_seniority(title: str) -> bool:
    """Whether a title says outright that the role is beyond someone early in their career.

    Args:
        title: The posting's title as the board wrote it.

    Returns:
        True only where the title states it. A title carrying no marker returns False, which means
        the title is silent on the question — not that the role is junior.
    """
    return bool(SENIOR.search(title))


def fits_stack(description: str) -> bool:
    """Whether a posting's body describes work that is actually a match.

    Two questions, both answered from the text: is most of what they name already known, and is
    the experience bar within reach.

    A posting that names no technologies at all fails. Its score is unknown rather than low, and
    keeping the unknown ones would refill the shortlist with exactly the postings nothing can
    vouch for — which is what this gate exists to prevent. They are the minority, and the board
    link is still there for anything that looks worth a second opinion.

    Args:
        description: The posting body as plain text.

    Returns:
        True if the posting clears both bars.
    """
    match = tech_match(description)
    if match.score is None or match.score < MIN_TECH_SCORE:
        return False
    return match.minimum_years is None or match.minimum_years <= MAX_YEARS


def relevant(postings: Sequence[BoardPosting]) -> list[BoardPosting]:
    """Keeps the postings worth storing and discards the rest.

    The title gates run first and the description gate last, because the title tests are a regex
    over a few words while the description test is several dozen patterns over a few thousand.
    Ordering them this way means the expensive test only ever sees the handful that survived the
    cheap ones.

    Args:
        postings: Everything one board returned.

    Returns:
        Those located in reach, belonging to one of the role families, not marked senior, and
        whose description matches the stack, in the order the board listed them.
    """
    return [
        posting
        for posting in postings
        if in_scope_location(posting.location_raw)
        and role_family(posting.title) is not None
        and not states_seniority(posting.title)
        and fits_stack(posting.description)
    ]

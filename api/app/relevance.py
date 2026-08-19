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

What counts as in reach, as the right kind of role, and as too senior are all facts about the
person searching, so every one of them arrives in a ``Profile`` passed to these functions. They
never import the loaded default: a filter that reached for a module-level profile could only ever
answer for one search, and the point of the profile is that the same posting can be judged under
two. As arguments they stay pure functions of their inputs, which is what lets the tests below
run the whole gate under a profile the repository has never seen. ``sweep`` and ``main`` read the
default once and pass it down.
"""

from collections.abc import Sequence

from app.boards import BoardPosting
from app.profile import Profile
from app.schemas import Region
from app.stack import tech_match


def in_scope_location(location: str, profile: Profile) -> bool:
    """Whether a location is somewhere worth seeing a job in.

    Args:
        location: The raw location text as the board wrote it.
        profile: The search being run, supplying the local and remote fragments.

    Returns:
        True for the profile's own region and for anything advertised as remote.
    """
    text = location.lower()
    return any(
        fragment in text for fragment in profile.local_fragments + profile.remote_fragments
    )


def region(location: str, profile: Profile) -> Region:
    """Which region a location places a posting in.

    Only ever asked of a stored posting, which has already passed ``in_scope_location``. A
    location naming nowhere local is therefore in storage because it advertised as remote, which
    is why remote is the fallback rather than a case matched in its own right — an unrecognised
    local spelling shows up as a remote role rather than as no answer at all.

    Local wins where a location says both. "Remote — Tel Aviv" is a role that can be worked from
    home *where the searcher lives*, and calling it remote would drop it out of the count of what
    is reachable locally, which is the count this field exists to make possible.

    ``Region.ISRAEL`` is the profile's local region under whatever name that region has. The
    member keeps its name because those two strings are the API's published contract and the
    dashboard filters on them; renaming it would be a change to the wire, not to this module.

    Args:
        location: The raw location text as the board wrote it.
        profile: The search being run, supplying the local fragments.

    Returns:
        ``Region.ISRAEL`` if the text names anywhere local, ``Region.REMOTE`` otherwise.
    """
    text = location.lower()
    if any(fragment in text for fragment in profile.local_fragments):
        return Region.ISRAEL
    return Region.REMOTE


def role_family(title: str, profile: Profile) -> str | None:
    """Which family of role a title describes, if any.

    Args:
        title: The posting's title as the board wrote it.
        profile: The search being run, supplying the families and how each is recognised.

    Returns:
        The name the profile gives the best-fitting family, or None if the title is not a role
        worth surfacing. None is the common answer: most of what a board lists is something else
        entirely. The families are tried in the order the profile writes them and the first match
        wins, so a title answering to two is reported as the one listed first.
    """
    for family, pattern in profile.role_families.items():
        if pattern.search(title):
            return family
    return None


def states_seniority(title: str, profile: Profile) -> bool:
    """Whether a title says outright that the role is beyond the level being searched for.

    Args:
        title: The posting's title as the board wrote it.
        profile: The search being run, supplying the seniority markers.

    Returns:
        True only where the title states it. A title carrying no marker returns False, which means
        the title is silent on the question — not that the role is junior.
    """
    return bool(profile.seniority_markers.search(title))


def fits_stack(description: str, profile: Profile) -> bool:
    """Whether a posting's body describes work that is actually a match.

    Two questions, both answered from the text: is most of what they name already known, and is
    the experience bar within reach.

    A posting that names no technologies at all fails. Its score is unknown rather than low, and
    keeping the unknown ones would refill the shortlist with exactly the postings nothing can
    vouch for — which is what this gate exists to prevent. They are the minority, and the board
    link is still there for anything that looks worth a second opinion.

    Args:
        description: The posting body as plain text.
        profile: The search being run, supplying both vocabularies and both bars.

    Returns:
        True if the posting clears both bars.
    """
    match = tech_match(description, profile)
    if match.score is None or match.score < profile.min_tech_score:
        return False
    return match.minimum_years is None or match.minimum_years <= profile.max_years


def relevant(postings: Sequence[BoardPosting], profile: Profile) -> list[BoardPosting]:
    """Keeps the postings worth storing and discards the rest.

    The title gates run first and the description gate last, because the title tests are a regex
    over a few words while the description test is several dozen patterns over a few thousand.
    Ordering them this way means the expensive test only ever sees the handful that survived the
    cheap ones.

    Args:
        postings: Everything one board returned.
        profile: The search being run, applied by every gate.

    Returns:
        Those located in reach, belonging to one of the role families, not marked senior, and
        whose description matches the stack, in the order the board listed them.
    """
    return [
        posting
        for posting in postings
        if in_scope_location(posting.location_raw, profile)
        and role_family(posting.title, profile) is not None
        and not states_seniority(posting.title, profile)
        and fits_stack(posting.description, profile)
    ]

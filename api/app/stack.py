"""Scoring a posting's description against the stack a profile says is known.

The title says what a role is called. The description says what it is built with and how much
experience it wants, and those are the two questions that decide whether applying is worth the
time. Both are answered here, from text alone, for free.

A match is expressed as *the share of the technologies a posting names that are already known*.
That direction matters. Scoring the other way round — how much of the known stack the posting
mentions — rewards long postings for listing everything and says nothing about whether the job
is a fit. Measuring the posting's own demands means a role wanting Python, FastAPI and MongoDB
scores full marks, while one wanting Java, Spring and Kafka scores nothing, however many
familiar words appear elsewhere in the text.

The vocabulary therefore has to include technologies that are *not* known. A list of only the
familiar ones would find familiar words in every posting and score them all perfectly.

Which technologies sit on each side is a fact about a person, not about this module, so both
vocabularies arrive in a ``Profile``. It is passed as an argument rather than read from
``app.profile``: reading the loaded default would leave the scoring functions with no honest way
to be asked about a different search, and being able to score the same description under two
profiles is the whole reason the profile exists. Passing it also keeps these functions pure —
same description, same profile, same answer — so a test needs no monkeypatching and no import
order to say what it means. The cost is one argument threaded from ``sweep`` and ``main``, which
are the only places that read the default at all.
"""

import re
from collections.abc import Mapping

from pydantic import BaseModel

from app.profile import Profile

YEARS = re.compile(
    r"(\d+)\s*(?:\+|-|–|to)?\s*(?:\d+)?\s*\+?\s*years?(?:\s+of)?"
    r"(?:\s+(?:relevant|professional|hands[- ]on|industry|proven))?"
    r"\s+(?:experience|exp\b)",
    re.I,
)
"""How a posting states the experience it wants.

Stays in source while the vocabularies moved into the profile, because this is a fact about how
English job adverts are written rather than about any one person's search. What varies between
searches is how many years are too many, and that is ``max_years`` in the profile.

Only the leading number is captured. A posting asking for "3-5 years" is asking for three; the
upper bound is what they hope for, and treating the range as five would discard a role that is
actually open.
"""


class TechMatch(BaseModel):
    """What one description says about its technologies and its experience bar."""

    matched: list[str]
    """Technologies the posting names that are already known, in vocabulary order."""

    missing: list[str]
    """Technologies the posting names that are not."""

    score: float | None
    """Share of named technologies that are known, or None if it names none at all.

    None is not zero. A posting that describes the work in prose without naming a single
    technology has not been judged, and treating that silence as a score of zero would discard
    roles on the strength of how they were written.
    """

    minimum_years: int | None
    """The lowest number of years the posting asks for, or None if it never says."""


def _found(vocabulary: Mapping[str, re.Pattern[str]], text: str) -> list[str]:
    """Returns the vocabulary entries whose pattern appears in the text."""
    return [name for name, pattern in vocabulary.items() if pattern.search(text)]


def minimum_years(description: str) -> int | None:
    """The least experience a posting asks for anywhere in its text.

    A description often states several requirements — three years with one technology, five with
    another. The smallest is the one that decides whether applying is plausible.

    Takes no profile: it reports what the posting says, and whether that is too much is
    ``fits_stack``'s question.

    Args:
        description: The posting body as plain text.

    Returns:
        The lowest number of years stated, or None if the posting never puts a number on it.
    """
    stated = [int(match) for match in YEARS.findall(description)]
    return min(stated) if stated else None


def tech_match(description: str, profile: Profile) -> TechMatch:
    """Scores a description against the stack a profile knows.

    Args:
        description: The posting body as plain text.
        profile: The search being run, supplying both technology vocabularies.

    Returns:
        Which technologies were recognised on each side, the resulting share, and the experience
        bar if the posting states one.
    """
    matched = _found(profile.known, description)
    missing = _found(profile.unknown, description)
    named = len(matched) + len(missing)
    return TechMatch(
        matched=matched,
        missing=missing,
        score=len(matched) / named if named else None,
        minimum_years=minimum_years(description),
    )

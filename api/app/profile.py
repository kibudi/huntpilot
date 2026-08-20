"""The search this tool is being run for, described in a file instead of in the filters.

Every gate the sweep applies — where a job may be, what it may be called, what it may be built
with, how much experience it may ask for — used to be a constant inside ``relevance.py`` or
``stack.py``, tuned for one developer in Israel. That made the tool useless to anyone else, and
made retuning it a source edit for its owner, when retuning is the thing most often wanted: a
sweep that returns nothing is fixed by lowering a threshold, not by changing code.

A profile is one JSON file holding all of it, read and validated once at startup. JSON rather than
YAML because the standard library already reads it and Pydantic already validates it, and a
configuration format is a poor reason to add a dependency. Validation is the point of the model
rather than a formality: a profile is the one input that can fail *quietly*: a misspelt field or a
pattern that matches nothing produces a sweep that stores no postings, which looks exactly like a
quiet week on the boards. Every constraint here exists to turn one of those into a startup error.

The vocabularies stay regular expressions rather than becoming word lists. Postings write one
technology many ways — "Node.js", "NodeJS", "Node", "K8s" — and some words have to be pinned to
the places they name a technology at all, which is why "Go" is only counted before "developer",
"engineer" or "programming". A profile of plain words would score worse than the constants it
replaced. The cost is that a profile can carry a broken pattern, so every pattern is compiled as
the file loads: a typo is a startup failure naming the file, not an exception in the middle of a
sweep six hours later.
"""

import json
import re
from pathlib import Path
from typing import Annotated, Any

from pydantic import (
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)
from pydantic import ValidationError as PydanticValidationError

from app.config import settings


def _compile(value: Any) -> re.Pattern[str]:
    """Compiles one profile pattern, case-insensitively.

    ``re.IGNORECASE`` is applied here rather than being written into each pattern as ``(?i)``,
    because every match in this project is against text a company wrote for humans: titles are
    capitalised inconsistently and a profile author who forgot the flag on one entry would lose
    real postings without anything reporting it.

    An already-compiled pattern is passed through so that a ``Profile`` can be built in code as
    well as read from a file, which is what lets a test state one pattern instead of a whole file.

    Args:
        value: The pattern as the profile wrote it, or an already-compiled pattern.

    Returns:
        The compiled pattern.

    Raises:
        ValueError: If the value is not a string, or is not a usable regular expression. Raised as
            ``ValueError`` so Pydantic reports it against the field it came from, naming the
            technology or family whose pattern is broken.
    """
    if isinstance(value, re.Pattern):
        return value
    if not isinstance(value, str):
        raise ValueError("a pattern must be written as a string")
    try:
        return re.compile(value, re.IGNORECASE)
    except re.error as error:
        raise ValueError(f"{value!r} is not a valid regular expression: {error}") from error


Pattern = Annotated[re.Pattern[str], BeforeValidator(_compile)]
"""A regular expression as a profile states it: a string in the file, compiled in the model."""

FamilyName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, to_lower=True)]
"""What a profile calls one family of role.

Deliberately not a ``StrEnum``, which is what this was before this module existed and what the
rest of the codebase uses wherever a field has a fixed set of values. ``ATS``, ``Status``,
``PostingStatus`` and ``Region`` are all still enums and stay that way: their values are the API's
own contract, fixed by this repository, and a value outside the set is a bug.

Role families are the opposite kind of set. Which families are worth surfacing is the single most
personal decision in the profile — the five that used to be enumerated here were chosen for one
person's career — and an enum is closed at import time, so it cannot hold a set that arrives from
a file at runtime. Keeping it would mean a Berlin Go developer either had their "distributed
systems" family rejected by a model that had never heard of it, or had to file it under one of
five names picked for somebody else. What the enum genuinely bought is bought here instead: the
name is a dict key, so families cannot be duplicated, and the constraints reject a blank or
stray-whitespace name. Lower-casing keeps one family from arriving twice under two capitalisations
in a file a person edits by hand.
"""

TechName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
"""What a profile calls one technology.

The label a match is reported under, so it is whatever its author finds readable — "ci/cd",
"c++" — rather than anything this code interprets.
"""


class Profile(BaseModel):
    """One person's search: where, what it is called, what it is built with, and how senior.

    ``extra="forbid"`` because a misspelt field is the failure this model exists to catch. Ignored
    extras would leave the real field at its default, and every default here is a filter that
    silently changes what a sweep keeps.

    ``frozen=True`` because the profile is read once at startup and shared by every caller. A
    filter that quietly retuned itself mid-sweep would make two postings in the same reading
    incomparable.

    Field order is meaningful in two places and preserved by both JSON and Python dicts:
    ``role_families`` is tried in the order written, and ``known`` and ``unknown`` decide the order
    technologies are reported in.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    local_fragments: tuple[str, ...]
    """Lower-case fragments that place a posting in the region worth working in.

    Cities are listed one by one rather than trusting a country name, because boards write
    locations as free text and disagree with each other: one sweep of the seeded watchlist
    produced 243 distinct location strings, the same city arrived as "Tel Aviv", "Tel Aviv
    District, Israel", "Tel Aviv-Yafo, Gush Dan, Israel" and "TLV", and roughly half of the
    postings in reach never named the country at all.

    Matched as substrings against lower-cased location text, not as patterns: a location is a
    handful of place names, and the spellings that matter are the ones a board actually emits.
    """

    remote_fragments: tuple[str, ...]
    """Fragments that make a posting worth keeping whatever country is attached to it.

    A remote role advertised from elsewhere may still be open to where the profile's owner lives.
    Settling that needs the description read by a person, so it is kept rather than dropped now.
    """

    seniority_markers: Pattern
    """Title words stating outright that a role is beyond the experience level being searched for.

    One pattern rather than a word list because the alternations carry real work: optional full
    stops in "Sr.", word boundaries so short markers do not match inside longer words.

    Leadership words belong here rather than among the families: a team lead, an engineering
    manager and a principal engineer are roles the posting itself puts out of reach, whatever
    family they otherwise belong to. Levelled titles say the same thing in another alphabet, which
    is why the default profile lists roman numerals — and why it stops before bare "V", a single
    letter that matches far more than it would buy.
    """

    role_families: dict[FamilyName, Pattern] = Field(min_length=1)
    """The kinds of role worth surfacing, and how each is recognised in a title.

    A whitelist rather than a subtraction. Naming the families that fit is both narrower and more
    honest than matching every title containing "engineer" and then listing exceptions: QA,
    automation, data, security, IT, embedded and game roles are all engineering, and for the
    default profile none of them is a match. As a whitelist they simply never appear, instead of
    having to be excluded one at a time as they are discovered.

    Tried in the order written, first match winning, so the order is the tie-break for a title
    answering to more than one pattern: with the default profile "Full Stack Software Engineer" is
    reported as full stack, which describes it better than software does.

    At least one family is required. An empty whitelist matches no title ever written, and a sweep
    that stores nothing is indistinguishable from a quiet week on the boards.
    """

    known: dict[TechName, Pattern] = Field(min_length=1)
    """Technologies there is real experience behind, and how each is written about.

    At least one is required, for the same reason as ``role_families``: with none, every posting
    scores zero and the whole sweep is filtered away without a word.
    """

    unknown: dict[TechName, Pattern] = Field(default_factory=dict)
    """Technologies a posting may demand that the profile's owner does not have.

    These exist so that a score means something. A match is scored as the share of the
    technologies a posting names that are already known, so without a vocabulary for the rest,
    every posting that says "Python" once would score full marks however much Java, Kafka and
    Spark surrounded it.

    Allowed to be empty, because a profile is entitled to say it will consider anything — but a
    profile that leaves it empty has turned the score into a constant, and should lift
    ``min_tech_score`` to zero and stop pretending otherwise.
    """

    min_tech_score: float = Field(ge=0.0, le=1.0)
    """The share of a posting's named technologies that must already be known.

    A share, so it is between zero and one; a profile stating 80 rather than 0.8 is rejected
    instead of silently keeping nothing.

    The default profile's 0.8 came from the data rather than from liking round numbers: across one
    full sweep, 80% left seven postings, 70% left twelve and 60% left twenty, and seven is a
    shortlist a person actually reads. Lowering it is the first thing to try when a sweep produces
    nothing — this number exists to be turned, and because descriptions are stored, every posting
    can be rescored without fetching anything.
    """

    max_years: int = Field(ge=0)
    """The most years of experience a posting may ask for.

    Compared against the *lowest* figure a posting states, so a role wanting "3-5 years" is
    treated as wanting three and survives.
    """

    @field_validator("local_fragments", "remote_fragments")
    @classmethod
    def _lower_cased(cls, fragments: tuple[str, ...]) -> tuple[str, ...]:
        """Lower-cases location fragments, because that is what they are matched against.

        Location text is lower-cased before matching, so a fragment written "Tel Aviv" in a
        hand-edited file would match nothing at all and quietly discard every posting in that
        city. Fixing it here rather than rejecting it keeps the file forgiving about the one thing
        a person cannot see going wrong.
        """
        return tuple(fragment.lower() for fragment in fragments)

    @model_validator(mode="after")
    def _somewhere_is_in_scope(self) -> "Profile":
        """Refuses a profile that places no location in scope.

        With both fragment lists empty every posting fails the location gate, so the sweep stores
        nothing and reports no error. That is the exact failure this model exists to make loud.

        Raises:
            ValueError: If neither local nor remote fragments are given.
        """
        if not self.local_fragments and not self.remote_fragments:
            raise ValueError(
                "a profile must name somewhere: local_fragments and remote_fragments "
                "cannot both be empty"
            )
        return self


class ProfileError(Exception):
    """A profile that could not be loaded, wrapping whatever went wrong with the file's name.

    Its own exception type because the three ways this fails — unreadable, not JSON, not a valid
    profile — are one problem to the person hitting it, and because none of the underlying errors
    says which file was being read. The path is the first thing wanted, since the whole point of
    the setting is that the file being read may not be the one in the repository.
    """


def load_profile(path: Path) -> Profile:
    """Reads and validates one profile file.

    Args:
        path: The JSON file to read.

    Returns:
        The validated profile, with every pattern compiled.

    Raises:
        ProfileError: If the file cannot be read, is not JSON, or is not a usable profile.
    """
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as error:
        raise ProfileError(f"cannot read the profile at {path}: {error}") from error

    try:
        data = json.loads(text)
    except json.JSONDecodeError as error:
        raise ProfileError(f"the profile at {path} is not valid JSON: {error}") from error

    try:
        return Profile.model_validate(data)
    except PydanticValidationError as error:
        raise ProfileError(f"the profile at {path} is not usable:\n{error}") from error


profile = load_profile(settings.profile_path)
"""The profile every entry point filters with, loaded once as this module is imported.

Loaded at import, like ``settings``, so that a broken profile stops the API, the worker and a
hand-run sweep at startup with the file named. Deferring the read to the first sweep would make a
typo surface six hours later, inside the one code path where an exception is caught and counted as
a board failure.

Only entry points read this — ``main`` and ``sweep``. The filters themselves take a profile as an
argument and never import it, which is what keeps them testable against a profile other than this
one.
"""

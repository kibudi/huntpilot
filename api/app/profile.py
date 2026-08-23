"""The search this tool is being run for, described in a file instead of in the filters.

Every gate the sweep applies — where a job may be, what it may be called, what it may be built
with, how much experience it may ask for — used to be a constant inside ``relevance.py`` or
``stack.py``, tuned for one developer in Israel. That made the tool useless to anyone else, and
made retuning it a source edit for its owner, when retuning is the thing most often wanted: a
sweep that returns nothing is fixed by lowering a threshold, not by changing code.

A profile is one JSON file holding all of it. JSON rather than
YAML because the standard library already reads it and Pydantic already validates it, and a
configuration format is a poor reason to add a dependency. Validation is the point of the model
rather than a formality: a profile is the one input that can fail *quietly*: a misspelt field or a
pattern that matches nothing produces a sweep that stores no postings, which looks exactly like a
quiet week on the boards. Every constraint here exists to turn one of those into a startup error.

The vocabularies are word lists, not regular expressions. Postings write one technology many ways
— "Node.js", "NodeJS", "Node", "K8s" — so an entry is a list of the spellings rather than one
spelling, and the boundaries that stop a short word matching inside a longer one are added when
the list is compiled instead of being written by hand. This is what lets the dashboard edit a
profile: asking the person searching to write a regular expression, and to get it right, is asking
the wrong thing of them.

They were patterns until the editor existed, and the conversion cost precision in exactly two
places — the entries that pinned a word to the context naming a technology at all, like "Go" only
before "developer" or "engineer". Those are written out as the phrases instead, which is narrower
than the lookahead was and readable by the person maintaining it.

The file is the *default*, not the running search. Once the dashboard can edit the profile, a file
read at startup cannot be the source of truth: an edit would take effect at the next restart, and
the API would be writing into its own package directory to make one. So the file seeds a stored
profile the first time a database is used, and the stored document is read from then on. The rules
do not move with it — everything written is validated by the same ``Profile``, so an edit that
empties the role families or breaks a pattern is refused with a reason rather than saved and
quietly keeping nothing.
"""

import json
import re
from datetime import UTC, datetime
from functools import cached_property
from pathlib import Path
from typing import Annotated, Any

from pydantic import (
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    PlainSerializer,
    StringConstraints,
    field_validator,
    model_validator,
)
from pydantic import ValidationError as PydanticValidationError

from app.config import settings
from app.models import ProfileSlot, SearchProfile


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


def _source(pattern: re.Pattern[str]) -> str:
    """Returns the pattern as its author wrote it, for storing and for sending over the wire.

    The inverse of ``_compile``, and the reason a profile can make the round trip out to a client,
    back through validation and into the database without anyone restating the eight fields it
    holds: dumping a ``Profile`` produces exactly the JSON a profile file contains.

    Args:
        pattern: The compiled pattern.

    Returns:
        Its source text. The ``re.IGNORECASE`` flag ``_compile`` applies is deliberately not
        written back in, because ``_compile`` applies it again on the way in — round-tripping it
        as ``(?i)`` would slowly grow the stored pattern by one prefix per edit.
    """
    return pattern.pattern


Pattern = Annotated[re.Pattern[str], BeforeValidator(_compile), PlainSerializer(_source)]
"""A regular expression as a profile states it: a string in the file, compiled in the model."""

Term = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, to_lower=True)]
"""One word or phrase a profile recognises something by.

Lower-cased because every match this project makes is case-insensitive anyway, so two
capitalisations of one word are the same term and should not be storable as two.
"""


def _bounded(term: str) -> str:
    r"""Wraps one term in the boundaries that keep it from matching inside a longer word.

    ``\`` is not used, because it is defined against the character beside it and half the terms
    here start or end with punctuation. ``\c++\`` never matches, since there is no word boundary
    after ``+``; ``\.net\`` fails to match "ASP.NET", because the boundary before ``.`` requires
    the preceding character to be a word character and ``P`` is one.

    So a boundary is asserted only on the sides where the term itself ends in a word character.
    "python" gets both and cannot match inside "pythonic"; ".net" gets only the trailing one and
    still matches "ASP.NET"; "c++" gets only the leading one and still matches "C++17".

    A trailing "s" is allowed through that boundary, because postings pluralise the things they
    name and a term list is written in the singular a person would type. Without it "large language
    model" misses "Large Language Models" and "snowflake" misses "snowflakes" — both found by
    running the old patterns and the new terms over four hundred live postings and looking at every
    case where they disagreed. It also earns "LLMs", which the pattern this replaced did not match
    either.

    Args:
        term: The term, already stripped and lower-cased.

    Returns:
        The escaped term with the boundaries that apply to it.
    """
    lead = r"(?<!\w)" if term[0].isalnum() or term[0] == "_" else ""
    trail = r"s?(?!\w)" if term[-1].isalnum() or term[-1] == "_" else ""
    return f"{lead}{re.escape(term)}{trail}"


class Terms(BaseModel):
    """The words that recognise one technology, one family of role, or one seniority marker.

    A list of plain words rather than a regular expression, because a profile is edited by the
    person searching and a regular expression is not something they should have to write. Every
    entry in the default profile that used to be a pattern is an alternation of words with word
    boundaries around it — which is exactly what this builds, from a list anyone can extend.

    The cost is precision at the edges. A pattern could say "go, but only when followed by
    developer or engineer"; a term list says "golang", "go developer", "go engineer" instead, which
    is narrower but readable. That trade was taken deliberately: the entries needing a lookahead
    were two, and neither is worth a syntax in the editor.

    Matching lives here rather than at the call sites so that ``relevance`` and ``stack`` ask the
    same question of a family, a known technology and a seniority marker, and none of them knows
    whether a profile stated one word or twenty.
    """

    terms: list[Term] = Field(min_length=1)
    """The words, in the order written. At least one, since none matches nothing."""

    @cached_property
    def pattern(self) -> re.Pattern[str]:
        """The terms as one case-insensitive alternation.

        Compiled once per set rather than per posting: a sweep asks the same sixty vocabularies
        about every description on every board, and recompiling for each would be the work of the
        pass rather than an incidental cost.
        """
        return re.compile("|".join(_bounded(term) for term in self.terms), re.IGNORECASE)

    def search(self, text: str) -> re.Match[str] | None:
        """Returns the first term found in the text, or None if none is.

        Named to match ``re.Pattern`` so that the code doing the filtering reads the same as it did
        when a profile held patterns directly.
        """
        return self.pattern.search(text)


def _as_terms(value: Any) -> Any:
    """Accepts a bare list of words where a term set is expected.

    A profile writes ``["golang", "go developer"]``, not ``{"terms": [...]}``: the wrapper is an
    implementation detail of matching, and making a person type it in every one of sixty entries
    would be noise. A mapping is passed through untouched so a ``Terms`` can still be built the
    ordinary way.
    """
    return {"terms": value} if isinstance(value, list) else value


Vocabulary = Annotated[
    Terms, BeforeValidator(_as_terms), PlainSerializer(lambda terms: terms.terms)
]
"""A set of words as a profile states it: a list of strings in the file, a matcher in the model."""

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

    ``frozen=True`` because a profile is read once and then handed to every filter in that pass. A
    filter that quietly retuned itself mid-sweep would make two postings in the same reading
    incomparable — which matters more now that the profile can be edited while a sweep is running:
    the pass keeps the profile it started with, and the edit applies to the next one.

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

    seniority_markers: Vocabulary
    """Title words stating outright that a role is beyond the experience level being searched for.

    A word list, with both spellings of an abbreviation written out — "sr" and "sr." are two
    terms rather than one pattern with an optional full stop, which is the shape a person editing
    this can extend without knowing what an optional full stop looks like in a regular expression.

    Leadership words belong here rather than among the families: a team lead, an engineering
    manager and a principal engineer are roles the posting itself puts out of reach, whatever
    family they otherwise belong to. Levelled titles say the same thing in another alphabet, which
    is why the default profile lists roman numerals — and why it stops before bare "V", a single
    letter that matches far more than it would buy.
    """

    role_families: dict[FamilyName, Vocabulary] = Field(min_length=1)
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

    known: dict[TechName, Vocabulary] = Field(min_length=1)
    """Technologies there is real experience behind, and how each is written about.

    At least one is required, for the same reason as ``role_families``: with none, every posting
    scores zero and the whole sweep is filtered away without a word.
    """

    unknown: dict[TechName, Vocabulary] = Field(default_factory=dict)
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


default_profile = load_profile(settings.profile_path)
"""The committed profile, loaded once as this module is imported, and what a fresh database gets.

Loaded at import, like ``settings``, so that a broken file stops the API, the worker and a
hand-run sweep at startup with the file named. Deferring the read would make a typo surface six
hours later, inside the one code path where an exception is caught and counted as a board failure.

Nothing filters with this directly any more: it is the seed for ``active_profile``, which is what
the sweep and the postings endpoint read. It stays loaded at import anyway, because the file is
still the shipped default and a checkout whose default profile is broken should say so at startup
rather than at the first sweep against an empty database.
"""


async def active_profile() -> Profile:
    """Returns the stored profile, seeding it from the committed file if there is none yet.

    Read fresh on every sweep and every request that filters, rather than cached at startup, which
    is the entire point of moving the profile into the database: an edit made in the dashboard
    changes what the next sweep keeps and how the next posting list is classified, with nothing
    restarted.

    Seeding on read rather than only at startup means the first sweep on a fresh database works
    whether it was started by the API, by the worker or by hand — none of which share a startup —
    and it costs one extra query exactly once per database.

    Returns:
        The stored profile, validated by the same rules as the file.

    Raises:
        ProfileError: If the stored document is no longer a usable profile. That should be
            unreachable, since every write validates first, but a document edited in the database
            by hand is the one way round that, and serving a silently broken filter is worse than
            failing.
    """
    document = await SearchProfile.find_one(SearchProfile.slot == ProfileSlot.ACTIVE)
    if document is None:
        document = await _seed_profile()
    try:
        return Profile.model_validate(document.search)
    except PydanticValidationError as error:
        raise ProfileError(f"the stored profile is not usable:\n{error}") from error


async def _seed_profile() -> SearchProfile:
    """Writes the committed profile into an empty database and returns the document.

    An upsert with ``$setOnInsert`` rather than a read followed by an insert, so that two processes
    starting against a fresh database at the same moment cannot both seed. The one that arrives
    second matches the existing document and writes nothing, rather than being refused by the
    uniqueness index and having to work out whether that meant a race or a real fault.

    Returns:
        The seeded profile document.

    Raises:
        ProfileError: If the document is gone again by the time it is read back, which can only
            mean something else is deleting profiles as this one starts up.
    """
    now = datetime.now(UTC)
    await SearchProfile.get_pymongo_collection().update_one(
        {"slot": ProfileSlot.ACTIVE.value},
        {
            "$setOnInsert": {
                "search": default_profile.model_dump(mode="json"),
                "created_at": now,
                "updated_at": now,
            }
        },
        upsert=True,
    )
    document = await SearchProfile.find_one(SearchProfile.slot == ProfileSlot.ACTIVE)
    if document is None:
        raise ProfileError("the profile seeded from the committed file disappeared immediately")
    return document


async def store_profile(replacement: Profile) -> None:
    """Replaces the stored profile with one that has already been validated.

    Takes a ``Profile`` rather than the raw JSON so that it is impossible to store something
    unvalidated: the argument cannot be constructed without every pattern compiling and every
    whitelist being non-empty. What is written is the model's own dump, so the stored profile is
    the normalised one — location fragments lower-cased, an omitted ``unknown`` filled in — and a
    client reading back what it just sent sees what the filters will actually use.

    A single upsert rather than a read followed by a write, for the same reason as seeding: it is
    one round trip, and it works whether or not the database has been seeded yet.

    Args:
        replacement: The new search, already validated.
    """
    now = datetime.now(UTC)
    await SearchProfile.get_pymongo_collection().update_one(
        {"slot": ProfileSlot.ACTIVE.value},
        {
            "$set": {"search": replacement.model_dump(mode="json"), "updated_at": now},
            "$setOnInsert": {"created_at": now},
        },
        upsert=True,
    )

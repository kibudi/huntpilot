"""Tests for deciding which board postings are worth storing."""

from app.boards import BoardPosting
from app.relevance import (
    MAX_YEARS,
    RoleFamily,
    fits_stack,
    in_scope_location,
    region,
    relevant,
    role_family,
    states_seniority,
)
from app.schemas import Region

MATCHING_BODY = "Build services in Python with FastAPI and MongoDB. 2 years of experience."
"""A description that clears the stack gate, so title and location tests are not blocked by it."""


def _posting(
    title: str = "Backend Engineer",
    location: str = "Tel Aviv",
    description: str = MATCHING_BODY,
) -> BoardPosting:
    """Builds one board posting to filter."""
    return BoardPosting(
        external_id="1",
        url="https://example.test/jobs/1",
        title=title,
        location_raw=location,
        description=description,
    )


def test_israel_is_recognised_however_it_is_spelled() -> None:
    """The boards disagree on spelling, and a filter that misses one spelling loses real roles."""
    for location in (
        "Tel Aviv",
        "Tel Aviv, Israel",
        "Tel Aviv District, Israel",
        "Tel Aviv-Yafo, Gush Dan, Israel",
        "TLV",
        "Herzliya",
        "tel aviv",
    ):
        assert in_scope_location(location), location


def test_elsewhere_is_out_of_scope() -> None:
    """The bulk of every board is somewhere unreachable, and that is what filtering is for."""
    for location in ("Gurugram, India", "New York City", "Singapore", "Tokyo", "London"):
        assert not in_scope_location(location), location


def test_remote_is_kept_wherever_it_is_advertised_from() -> None:
    """A remote role may still be open to Israel, which only the description can settle."""
    assert in_scope_location("Remote - United States")
    assert in_scope_location("Anywhere")


def test_israeli_cities_are_classified_as_israel() -> None:
    """Named in full rather than looped over ``ISRAEL_FRAGMENTS``, which would prove nothing.

    Regression test: the dashboard kept its own shorter copy of the fragments, and every city
    here was on the backend's list and missing from that one — a role in Kfar Saba was stored and
    then left out of the count of Israeli roles, which is the number the field exists to produce.
    Iterating the constant would drop a city from the assertions the moment it was dropped from
    the constant, which is exactly the change worth catching.
    """
    for location in (
        "Kfar Saba",
        "Tel-Aviv",
        "Herzlia",
        "Or Yehuda",
        "Rosh Ha'ayin",
        "Tel Aviv District, Israel",
        "TLV",
    ):
        assert region(location) is Region.ISRAEL, location


def test_a_remote_posting_from_elsewhere_is_remote() -> None:
    """Anything stored that is not Israeli is there because it advertised as remote."""
    assert region("Remote - United States") is Region.REMOTE
    assert region("Anywhere") is Region.REMOTE


def test_a_remote_israeli_posting_counts_as_israel() -> None:
    """A location saying both is an Israeli role, and the Israeli count must not lose it."""
    assert region("Remote, Tel Aviv") is Region.ISRAEL


def test_each_family_is_recognised() -> None:
    """The five families are the whole point of the whitelist, so each must actually match."""
    assert role_family("Backend Engineer") is RoleFamily.BACKEND
    assert role_family("Full Stack Developer") is RoleFamily.FULLSTACK
    assert role_family("Front-End Engineer") is RoleFamily.FRONTEND
    assert role_family("DevOps Engineer") is RoleFamily.PLATFORM
    assert role_family("Software Engineer") is RoleFamily.SOFTWARE


def test_the_most_descriptive_family_wins() -> None:
    """A title answering to two patterns is reported as the one that describes it best."""
    assert role_family("Full-Stack Software Engineer") is RoleFamily.FULLSTACK


def test_engineering_roles_outside_the_families_are_dropped() -> None:
    """These are real engineering jobs and still not a match, which is why this is a whitelist."""
    for title in (
        "QA Automation Engineer",
        "Automation Engineer",
        "Data Engineer",
        "Algorithm Engineer (RTB)",
        "Application Security Engineer",
        "Game Engineer",
        "Mobile SDK Engineer",
    ):
        assert role_family(title) is None, title


def test_titles_that_borrow_engineering_words_are_dropped() -> None:
    """Bare "engineer" and bare "developer" must never be enough to match on their own."""
    for title in (
        "Solutions Engineer",
        "Sales Engineer",
        "Developer Advocate",
        "Product Manager , Developer Experience",
        "Technical Support Engineer",
    ):
        assert role_family(title) is None, title


def test_stated_seniority_is_recognised() -> None:
    """A title saying senior settles the question without anything having to read the body."""
    for title in (
        "Senior Backend Engineer",
        "Sr. Software Engineer",
        "Staff Software Engineer",
        "Principal Full Stack Engineer",
        "Backend Team Lead",
        "Engineering Manager, AP",
        "Software Engineer III",
    ):
        assert states_seniority(title), title


def test_an_unmarked_title_is_not_called_junior() -> None:
    """Silence is not evidence.

    Most postings that want several years say so only in the description, so a title with no
    marker means the title did not answer the question — it must not be read as junior.
    """
    for title in ("Backend Engineer", "Software Engineer", "Full Stack Developer"):
        assert not states_seniority(title), title


def test_relevant_requires_every_gate_to_pass() -> None:
    """Any one gate failing is enough to discard a posting."""
    assert relevant([_posting()]) != []
    assert relevant([_posting(location="New York City")]) == []
    assert relevant([_posting(title="QA Automation Engineer")]) == []
    assert relevant([_posting(title="Senior Backend Engineer")]) == []
    assert relevant([_posting(description="Java, Spring and Kafka.")]) == []
    assert relevant(
        [_posting(description="Python with FastAPI and MongoDB. 7 years of experience.")]
    ) == []


def test_a_posting_whose_body_names_nothing_is_dropped() -> None:
    """An unscorable posting is not evidence of a match, and keeping it refills the shortlist."""
    assert not fits_stack("You will join a small team and help us grow the product.")


def test_a_posting_at_exactly_the_year_limit_survives() -> None:
    """``MAX_YEARS`` is the most a posting may ask for, not the first figure that is too many.

    "3-5 years" is read at three, and three is the limit itself. Comparing with ``<`` rather than
    ``<=`` would discard every posting that asks for exactly what is on offer.
    """
    assert fits_stack(f"Python, FastAPI and MongoDB. {MAX_YEARS}-5 years of experience.")


def test_relevant_keeps_the_board_order() -> None:
    """Filtering must not reorder, so that what reconcile stores follows the board's own listing.

    The survivors are deliberately in an order alphabetical sorting would change, because a
    fixture that happens to be sorted already cannot tell the two apart.
    """
    postings = [
        _posting(title="Full Stack Developer"),
        _posting(title="QA Automation Engineer"),
        _posting(title="Backend Engineer"),
    ]

    assert [posting.title for posting in relevant(postings)] == [
        "Full Stack Developer",
        "Backend Engineer",
    ]

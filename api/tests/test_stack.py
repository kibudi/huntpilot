"""Tests for scoring a posting's description against a profile's stack.

The scoring assertions use the committed profile, because "Python and FastAPI are known, Java and
Kafka are not" is a statement about that profile and about no other. The last test scores one
description under two profiles, which is what shows the arithmetic belongs to the module and the
verdict belongs to the file.
"""

from app.profile import Profile
from app.profile import default_profile as DEFAULT_PROFILE
from app.stack import minimum_years, tech_match


def test_a_posting_naming_only_known_technologies_scores_full_marks() -> None:
    """The case the whole gate exists to find."""
    match = tech_match(
        "You will build services in Python with FastAPI and MongoDB.", DEFAULT_PROFILE
    )

    assert match.score == 1.0
    assert set(match.matched) == {"python", "fastapi", "mongodb"}
    assert match.missing == []


def test_a_posting_naming_only_unknown_technologies_scores_nothing() -> None:
    """Recognising what is *not* known is what stops every posting scoring perfectly."""
    match = tech_match(
        "Backend work in Java and Spring Boot, with Kafka and Spark.", DEFAULT_PROFILE
    )

    assert match.score == 0.0
    assert match.matched == []
    assert set(match.missing) == {"java", "spring", "kafka", "spark"}


def test_the_score_is_the_share_of_what_the_posting_names() -> None:
    """Scoring against the posting's demands, not against the whole known stack.

    Measuring the other way round would reward a long posting for listing everything, and would
    say nothing about whether the job is a fit.
    """
    match = tech_match("Python, React, Java and Kafka.", DEFAULT_PROFILE)

    assert match.score == 0.5


def test_a_posting_naming_nothing_is_unscored_rather_than_zero() -> None:
    """Silence is not a bad score, and the two must not be confused.

    A posting written entirely in prose has not been judged. Reporting that as zero would make it
    indistinguishable from one demanding a stack with nothing in common.
    """
    match = tech_match("You will join a small team and help us grow the product.", DEFAULT_PROFILE)

    assert match.score is None
    assert match.matched == []
    assert match.missing == []


def test_short_forms_are_recognised() -> None:
    """Postings write these many ways, and missing a spelling costs a real match."""
    assert "kubernetes" in tech_match("Experience with K8s", DEFAULT_PROFILE).matched
    assert "node" in tech_match("Strong Node.js background", DEFAULT_PROFILE).matched


def test_a_short_form_does_not_match_inside_another_word() -> None:
    """Word boundaries carry the weight here, and losing them scores unrelated text as a match."""
    assert tech_match("Manage build artifacts and release trains.", DEFAULT_PROFILE).matched == []


def test_go_is_only_matched_where_it_names_the_language() -> None:
    """The bare word appears in ordinary English in nearly every posting ever written."""
    prose = tech_match("You will go on to own the service end to end.", DEFAULT_PROFILE)
    named = tech_match("We are looking for a Go developer.", DEFAULT_PROFILE)

    assert "go" not in prose.missing
    assert "go" in named.missing


def test_patterns_from_a_profile_are_matched_case_insensitively(berlin_profile: Profile) -> None:
    """Companies capitalise titles and technologies as they please.

    The flag is applied once, as the profile compiles, rather than being written into every entry
    — so a profile author who never thought about case still matches "GOLANG" and "Kubernetes".
    """
    match = tech_match("GOLANG and KUBERNETES.", berlin_profile)

    assert set(match.matched) == {"go", "kubernetes"}


def test_the_same_description_scores_differently_under_a_different_profile(
    berlin_profile: Profile,
) -> None:
    """One text, two searches, opposite scores — which is what makes the score a fact about a fit.

    Python and FastAPI are the committed profile's own stack and the Berlin profile's unknowns, so
    the identical sentence is a perfect match to one reader and a total mismatch to the other.
    """
    description = "Build services in Python with FastAPI."

    assert tech_match(description, DEFAULT_PROFILE).score == 1.0
    assert tech_match(description, berlin_profile).score == 0.0


def test_the_lowest_stated_experience_is_the_one_that_counts() -> None:
    """A posting stating several bars is judged on the smallest, which is what gates entry."""
    assert minimum_years("5 years of experience with Java, 2 years of experience with SQL") == 2


def test_a_range_is_read_at_its_lower_bound() -> None:
    """The upper end of "3-5 years" is what they hope for, not what they require."""
    assert minimum_years("3-5 years of experience") == 3
    assert minimum_years("2+ years of hands-on experience") == 2


def test_a_posting_that_never_states_years_returns_none() -> None:
    """Most do not, and an unstated bar must not be invented as zero or as infinity."""
    assert minimum_years("You will own features end to end.") is None

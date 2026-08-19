"""Tests for scoring a posting's description against the known stack."""

from app.stack import minimum_years, tech_match


def test_a_posting_naming_only_known_technologies_scores_full_marks() -> None:
    """The case the whole gate exists to find."""
    match = tech_match("You will build services in Python with FastAPI and MongoDB.")

    assert match.score == 1.0
    assert set(match.matched) == {"python", "fastapi", "mongodb"}
    assert match.missing == []


def test_a_posting_naming_only_unknown_technologies_scores_nothing() -> None:
    """Recognising what is *not* known is what stops every posting scoring perfectly."""
    match = tech_match("Backend work in Java and Spring Boot, with Kafka and Spark.")

    assert match.score == 0.0
    assert match.matched == []
    assert set(match.missing) == {"java", "spring", "kafka", "spark"}


def test_the_score_is_the_share_of_what_the_posting_names() -> None:
    """Scoring against the posting's demands, not against the whole known stack.

    Measuring the other way round would reward a long posting for listing everything, and would
    say nothing about whether the job is a fit.
    """
    match = tech_match("Python, React, Java and Kafka.")

    assert match.score == 0.5


def test_a_posting_naming_nothing_is_unscored_rather_than_zero() -> None:
    """Silence is not a bad score, and the two must not be confused.

    A posting written entirely in prose has not been judged. Reporting that as zero would make it
    indistinguishable from one demanding a stack with nothing in common.
    """
    match = tech_match("You will join a small team and help us grow the product.")

    assert match.score is None
    assert match.matched == []
    assert match.missing == []


def test_short_forms_are_recognised() -> None:
    """Postings write these many ways, and missing a spelling costs a real match."""
    assert "kubernetes" in tech_match("Experience with K8s").matched
    assert "node" in tech_match("Strong Node.js background").matched


def test_a_short_form_does_not_match_inside_another_word() -> None:
    """Word boundaries carry the weight here, and losing them scores unrelated text as a match."""
    assert tech_match("Manage build artifacts and release trains.").matched == []


def test_go_is_only_matched_where_it_names_the_language() -> None:
    """The bare word appears in ordinary English in nearly every posting ever written."""
    assert "go" not in tech_match("You will go on to own the service end to end.").missing
    assert "go" in tech_match("We are looking for a Go developer.").missing


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

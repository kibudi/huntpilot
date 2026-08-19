"""Tests for loading and validating a profile.

The subject here is failure. A profile is the one input that can go wrong quietly: a mistyped
field name, a pattern with an unclosed bracket or a score written as 80 instead of 0.8 all produce
a sweep that stores nothing, which is indistinguishable from a quiet week on the boards. Each test
below is one of those mistakes, and each asserts that it stops the load with the file named rather
than being absorbed.
"""

import json
from pathlib import Path
from typing import Any

import pytest

from app.config import DEFAULT_PROFILE_FILE, settings
from app.profile import Profile, ProfileError, load_profile

VALID: dict[str, Any] = {
    "local_fragments": ["berlin"],
    "remote_fragments": ["remote"],
    "seniority_markers": r"\b(principal|staff)\b",
    "role_families": {"backend": r"\bback[ -]?end\b"},
    "known": {"go": r"\bgolang\b"},
    "unknown": {"java": r"\bjava\b"},
    "min_tech_score": 0.6,
    "max_years": 5,
}
"""The smallest profile that loads, which every test here breaks in exactly one way.

Deliberately not the committed profile: starting from a valid file and changing one thing is what
makes each failure attributable to the thing changed.
"""


def _write(tmp_path: Path, data: Any) -> Path:
    """Writes a profile file and returns its path.

    Takes the body as-is rather than as overrides, so a test can leave a field out or write
    something that is not an object at all.
    """
    path = tmp_path / "profile.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def test_the_committed_profile_is_the_one_loaded_by_default() -> None:
    """A fresh checkout must filter without anything being configured.

    Also pins the values behaviour was tuned against, so that editing the shipped file is a
    deliberate act with a failing test attached rather than a quiet change to what every sweep
    keeps.
    """
    assert settings.profile_path == DEFAULT_PROFILE_FILE

    shipped = load_profile(DEFAULT_PROFILE_FILE)

    assert shipped.min_tech_score == 0.8
    assert shipped.max_years == 3
    assert list(shipped.role_families) == [
        "fullstack",
        "backend",
        "frontend",
        "platform",
        "software",
    ]
    assert "israel" in shipped.local_fragments
    assert "python" in shipped.known
    assert "java" in shipped.unknown


def test_a_broken_pattern_fails_the_load(tmp_path: Path) -> None:
    """The reason patterns are compiled at load rather than at first use.

    An unclosed bracket is a plausible typo in a file edited by hand. Compiled lazily it would
    raise in the middle of a sweep, inside the one ``except`` that treats an exception as a board
    that could not be read — so a typo in the profile would be reported as several dozen companies
    being down. The error has to name the entry, since a profile holds sixty of them.
    """
    path = _write(tmp_path, VALID | {"known": {"go": r"\bgolang\b", "sql": "[unclosed"}})

    with pytest.raises(ProfileError) as caught:
        load_profile(path)

    assert "sql" in str(caught.value)
    assert "valid regular expression" in str(caught.value)


def test_a_misspelt_field_is_refused(tmp_path: Path) -> None:
    """The quietest failure of all: the real field keeps its default and nothing says so."""
    path = _write(tmp_path, VALID | {"min_tech_scores": 0.6})

    with pytest.raises(ProfileError) as caught:
        load_profile(path)

    assert "min_tech_scores" in str(caught.value)


def test_a_missing_field_is_refused(tmp_path: Path) -> None:
    """Every gate must be stated. A profile that forgets one is not a profile with a default."""
    path = _write(tmp_path, {key: value for key, value in VALID.items() if key != "max_years"})

    with pytest.raises(ProfileError) as caught:
        load_profile(path)

    assert "max_years" in str(caught.value)


def test_a_score_outside_zero_to_one_is_refused(tmp_path: Path) -> None:
    """Writing the share as a percentage is the obvious mistake, and it keeps nothing at all."""
    path = _write(tmp_path, VALID | {"min_tech_score": 80})

    with pytest.raises(ProfileError) as caught:
        load_profile(path)

    assert "min_tech_score" in str(caught.value)


def test_a_profile_that_names_nowhere_is_refused(tmp_path: Path) -> None:
    """With no location in scope every posting fails the first gate and the sweep looks calm."""
    path = _write(tmp_path, VALID | {"local_fragments": [], "remote_fragments": []})

    with pytest.raises(ProfileError) as caught:
        load_profile(path)

    assert "must name somewhere" in str(caught.value)


def test_a_profile_with_no_families_or_no_known_stack_is_refused(tmp_path: Path) -> None:
    """Either empty whitelist matches nothing ever written: a filter that hides its own bug."""
    overrides: tuple[dict[str, Any], ...] = ({"role_families": {}}, {"known": {}})
    for override in overrides:
        with pytest.raises(ProfileError):
            load_profile(_write(tmp_path, VALID | override))


def test_malformed_json_names_the_file(tmp_path: Path) -> None:
    """A trailing comma is what JSON costs, and the message has to point at the file to fix."""
    path = tmp_path / "profile.json"
    path.write_text('{"local_fragments": ["berlin"],}', encoding="utf-8")

    with pytest.raises(ProfileError) as caught:
        load_profile(path)

    assert str(path) in str(caught.value)


def test_a_missing_file_names_the_path(tmp_path: Path) -> None:
    """The likeliest failure once the path is configurable is that it points at nothing."""
    missing = tmp_path / "nowhere.json"

    with pytest.raises(ProfileError) as caught:
        load_profile(missing)

    assert str(missing) in str(caught.value)


def test_location_fragments_are_lower_cased_on_load(tmp_path: Path) -> None:
    """Locations are lower-cased before matching, so a capitalised fragment would match nothing.

    Silently, and only for that one city — which is why the file is fixed rather than rejected.
    """
    path = _write(tmp_path, VALID | {"local_fragments": ["Berlin", "MÜNCHEN"]})

    assert load_profile(path).local_fragments == ("berlin", "münchen")


def test_a_profile_cannot_be_changed_after_loading() -> None:
    """One sweep must judge every board by the same rules, and it holds one profile to do it."""
    loaded = Profile.model_validate(VALID)

    with pytest.raises(ValueError):
        loaded.max_years = 9

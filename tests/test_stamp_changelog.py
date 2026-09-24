"""The CHANGELOG stamp the Release workflow runs after an automatic release."""

import importlib.util
from pathlib import Path

_SCRIPT = Path(__file__).resolve().parents[1] / ".github" / "scripts" / "stamp_changelog.py"
_spec = importlib.util.spec_from_file_location("stamp_changelog", _SCRIPT)
stamp_changelog = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(stamp_changelog)

HEAD = "# Changelog\n\nIntro.\n\n"
OLD = "## [0.1.0] - 2026-01-01\n\n### Added\n- First.\n"


def _log(unreleased: str) -> str:
    return f"{HEAD}## [Unreleased]\n{unreleased}\n{OLD}"


def _release(version, text, previous=""):
    items = stamp_changelog.added(
        stamp_changelog.unreleased_entries(text), stamp_changelog.unreleased_entries(previous)
    )
    return (version, "2026-02-02", items)


def test_moves_shipped_lines_under_a_dated_section_keeping_subsections():
    text = _log("\n### Fixed\n- A fix.\n\n### Added\n- A thing,\n  wrapped.\n")
    out = stamp_changelog.stamp(text, [_release("0.1.1", text)])
    assert out == (
        f"{HEAD}## [Unreleased]\n\n"
        "## [0.1.1] - 2026-02-02\n\n### Fixed\n- A fix.\n\n### Added\n- A thing,\n  wrapped.\n\n"
        f"{OLD}"
    )


def test_a_second_run_changes_nothing():
    text = _log("\n### Fixed\n- A fix.\n")
    once = stamp_changelog.stamp(text, [_release("0.1.1", text)])
    assert stamp_changelog.stamp(once, [_release("0.1.1", text)]) == once


def test_empty_unreleased_is_left_alone():
    text = _log("")
    assert stamp_changelog.stamp(text, [_release("0.1.1", text)]) == text


def test_each_release_takes_only_what_it_added_and_later_lines_stay():
    at_first = _log("\n### Changed\n- One.\n")
    at_second = _log("\n### Changed\n- One.\n- Two.\n")
    main = _log("\n### Fixed\n- Three.\n\n### Changed\n- One.\n- Two.\n")
    out = stamp_changelog.stamp(
        main, [_release("0.1.1", at_first), _release("0.1.2", at_second, at_first)]
    )
    assert out == (
        f"{HEAD}## [Unreleased]\n\n### Fixed\n- Three.\n\n"
        "## [0.1.2] - 2026-02-02\n\n### Changed\n- Two.\n\n"
        "## [0.1.1] - 2026-02-02\n\n### Changed\n- One.\n\n"
        f"{OLD}"
    )


def test_repeated_subsections_merge_and_reworded_lines_stay_unreleased():
    at_release = _log("\n### Changed\n- A.\n\n### Changed\n- B.\n- Old wording.\n")
    main = _log("\n### Changed\n- A.\n\n### Changed\n- B.\n- New wording.\n")
    out = stamp_changelog.stamp(main, [_release("0.1.1", at_release)])
    assert out == (
        f"{HEAD}## [Unreleased]\n\n### Changed\n- New wording.\n\n"
        "## [0.1.1] - 2026-02-02\n\n### Changed\n- A.\n- B.\n\n"
        f"{OLD}"
    )


def test_a_version_that_already_has_a_section_is_skipped():
    text = _log("\n### Fixed\n- A fix.\n")
    assert stamp_changelog.stamp(text, [_release("0.1.0", text)]) == text

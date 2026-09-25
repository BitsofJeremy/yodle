"""
Validation tests for the in-repo Hermes skill (skills/software-development/yodle/SKILL.md).

Enforces the hardline authoring standards from the Hermes skill-authoring docs:
frontmatter shape, description limits, required sections, no machine-local
paths. Standard library + pytest only, no network.
"""

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SKILL_PATH = REPO_ROOT / "skills" / "software-development" / "yodle" / "SKILL.md"

# Sections required by the Hermes authoring standard, in order.
REQUIRED_SECTIONS = [
    "When to Use",
    "Prerequisites",
    "How to Run",
    "Quick Reference",
    "Procedure",
    "Pitfalls",
    "Verification",
]


@pytest.fixture(scope="module")
def skill_content() -> str:
    """Raw SKILL.md text; skip all tests if the skill file is absent."""
    if not SKILL_PATH.is_file():
        pytest.fail(f"skill file missing: {SKILL_PATH.relative_to(REPO_ROOT)}")
    return SKILL_PATH.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def frontmatter(skill_content: str) -> str:
    """Extract the YAML frontmatter block (between the --- fences)."""
    assert skill_content.startswith("---"), "frontmatter must start at byte 0"
    match = re.search(r"\n---\s*\n", skill_content[3:])
    assert match, "frontmatter must close with \\n---\\n before the body"
    return skill_content[3 : 3 + match.start()]


def _fm_field(frontmatter: str, field: str) -> str | None:
    """Read a simple top-level `field: value` scalar from frontmatter."""
    match = re.search(rf"^{re.escape(field)}:\s*(.+)$", frontmatter, re.MULTILINE)
    return match.group(1).strip() if match else None


class TestFrontmatter:
    """Validator-level requirements for the --- block."""

    def test_starts_at_byte_zero(self, skill_content):
        assert skill_content.startswith("---")

    def test_non_empty_body_after_frontmatter(self, skill_content):
        match = re.search(r"\n---\s*\n", skill_content[3:])
        body = skill_content[3 + match.end():]
        assert body.strip(), "body after closing --- must be non-empty"

    @pytest.mark.parametrize(
        "field", ["name", "description", "version", "author", "license", "platforms"]
    )
    def test_required_field_present(self, frontmatter, field):
        assert _fm_field(frontmatter, field) is not None, f"missing frontmatter field: {field}"

    def test_name_is_lowercase_hyphenated(self, frontmatter):
        name = _fm_field(frontmatter, "name")
        assert re.fullmatch(r"[a-z0-9-]{1,64}", name), f"name {name!r} not lowercase-hyphen format"

    def test_description_is_one_sentence_under_60_chars(self, frontmatter):
        desc = _fm_field(frontmatter, "description")
        assert len(desc) <= 60, f"description {len(desc)} chars — hardline is 60"
        assert desc.endswith("."), "description must end with a period"
        # One sentence: no terminal punctuation before the final period.
        assert not re.search(r"[.!?]\s+\S", desc), "description must be one sentence"

    def test_version_is_semver(self, frontmatter):
        version = _fm_field(frontmatter, "version")
        assert re.fullmatch(r"\d+\.\d+\.\d+", version), f"version {version!r} is not semver"

    def test_author_credits_human_first(self, frontmatter):
        author = _fm_field(frontmatter, "author")
        assert author != "Hermes Agent", "human contributor must be credited first"
        assert "Hermes Agent" in author, "author should credit Hermes Agent as collaborator"

    def test_platforms_list_present(self, frontmatter):
        platforms = _fm_field(frontmatter, "platforms")
        assert platforms and platforms.startswith("["), "platforms must be a YAML list"


class TestHermesMetadata:
    """metadata.hermes block requirements."""

    def test_tags_present(self, frontmatter):
        assert re.search(r"^\s+tags:\s*\[.+\]", frontmatter, re.MULTILINE), "metadata.hermes.tags missing"

    def test_related_skills_entries_exist_in_repo(self, frontmatter):
        match = re.search(r"related_skills:\s*\[(.*?)\]", frontmatter)
        assert match, "metadata.hermes.related_skills missing"
        entries = [e.strip() for e in match.group(1).split(",") if e.strip()]
        for entry in entries:
            hits = list((REPO_ROOT / "skills").rglob(f"{entry}/SKILL.md")) + list(
                (REPO_ROOT / "optional-skills").rglob(f"{entry}/SKILL.md")
            ) if (REPO_ROOT / "optional-skills").exists() else list(
                (REPO_ROOT / "skills").rglob(f"{entry}/SKILL.md")
            )
            assert hits, f"related_skills entry {entry!r} does not resolve in-repo"


class TestBodyStructure:
    """Modern section order and content rules."""

    @pytest.mark.parametrize("section", REQUIRED_SECTIONS)
    def test_required_section_present(self, skill_content, section):
        assert re.search(rf"^##\s+{re.escape(section)}\s*$", skill_content, re.MULTILINE), (
            f"missing required section: ## {section}"
        )

    def test_sections_in_documented_order(self, skill_content):
        positions = [
            (m.start(), m.group(1))
            for m in re.finditer(r"^##\s+(.+)$", skill_content, re.MULTILINE)
        ]
        seen = [title for _, title in positions]
        required_in_doc = [s for s in REQUIRED_SECTIONS if s in seen]
        expected = [s for s in REQUIRED_SECTIONS if s in seen]
        assert required_in_doc == expected, "required sections out of order"
        # Verify each required section's heading index increases.
        idx = [seen.index(s) for s in expected]
        assert idx == sorted(idx)

    def test_when_to_use_has_counter_triggers(self, skill_content):
        section = re.search(
            r"^##\s+When to Use\s*$(.*?)(?=^##\s|\Z)", skill_content, re.MULTILINE | re.DOTALL
        ).group(1)
        assert re.search(r"[Dd]on'?t use for|[Cc]ounter-trigger", section), (
            "When to Use must include counter-triggers"
        )

    def test_body_within_size_limit(self, skill_content):
        assert len(skill_content) <= 100_000, "SKILL.md exceeds 100k char limit"
        lines = skill_content.count("\n") + 1
        assert lines <= 300, f"SKILL.md is {lines} lines — target is ~100-200, bulk goes in references/"


class TestPathHygiene:
    """No machine-local paths; repo-relative only."""

    def test_no_machine_local_paths(self, skill_content):
        assert not re.search(r"/Users/|/home/[a-z]|C:\\\\", skill_content), (
            "machine-local absolute path found in skill"
        )

    def test_hermes_tools_referenced_in_backticks(self, skill_content):
        # At least the terminal tool should be invoked via its Hermes name.
        assert re.search(r"`terminal\(", skill_content), (
            'commands should be framed as terminal(command="...")'
        )

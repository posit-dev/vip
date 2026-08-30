from pathlib import Path

import pytest

from vip.traceability import ControlListError, load_controls

FULL = """
[controls.cfr-11-10-e]
description = "Secure, computer-generated, time-stamped audit trails"
reference = "21 CFR 11.10(e)"
risk = "high"
verification = "automated"
responsibility = "shared"
notes = "Retention duration is a customer configuration decision."

[controls.training]
description = "Personnel training records"
verification = "procedural"
responsibility = "customer"
"""


def test_loads_all_fields(tmp_path):
    p = tmp_path / "controls.toml"
    p.write_text(FULL)
    controls = load_controls(p)

    audit = controls["cfr-11-10-e"]
    assert audit.description.startswith("Secure")
    assert audit.reference == "21 CFR 11.10(e)"
    assert audit.risk == "high"
    assert audit.verification == "automated"
    assert audit.responsibility == "shared"
    assert audit.notes


def test_optional_fields_default(tmp_path):
    p = tmp_path / "controls.toml"
    p.write_text('[controls.x]\ndescription = "only required key"\n')
    spec = load_controls(p)["x"]
    assert spec.reference is None
    assert spec.risk is None
    assert spec.responsibility is None
    assert spec.verification == "automated"


def test_missing_description_is_an_error(tmp_path):
    p = tmp_path / "controls.toml"
    p.write_text('[controls.x]\nrisk = "high"\n')
    with pytest.raises(ControlListError, match="description"):
        load_controls(p)


def test_unknown_verification_value_is_an_error(tmp_path):
    p = tmp_path / "controls.toml"
    p.write_text('[controls.x]\ndescription = "d"\nverification = "vibes"\n')
    with pytest.raises(ControlListError, match="verification"):
        load_controls(p)


def test_missing_file_is_an_error(tmp_path):
    with pytest.raises(ControlListError, match="not found"):
        load_controls(tmp_path / "nope.toml")


def test_missing_controls_table_is_an_error(tmp_path):
    p = tmp_path / "controls.toml"
    p.write_text('title = "wrong shape"\n')
    with pytest.raises(ControlListError, match="controls"):
        load_controls(p)


def test_numeric_description_is_an_error(tmp_path):
    p = tmp_path / "controls.toml"
    p.write_text("[controls.x]\ndescription = 5\n")
    with pytest.raises(ControlListError, match="x.*expected a string"):
        load_controls(p)


def test_list_description_is_an_error(tmp_path):
    p = tmp_path / "controls.toml"
    p.write_text('[controls.y]\ndescription = ["a", "b"]\n')
    with pytest.raises(ControlListError, match="y.*expected a string"):
        load_controls(p)


def test_empty_description_is_an_error(tmp_path):
    p = tmp_path / "controls.toml"
    p.write_text('[controls.z]\ndescription = ""\n')
    with pytest.raises(ControlListError, match="empty"):
        load_controls(p)


def test_directory_path_is_an_error(tmp_path):
    with pytest.raises(ControlListError, match="not a file"):
        load_controls(tmp_path)


def test_empty_controls_table_is_an_error(tmp_path):
    p = tmp_path / "controls.toml"
    p.write_text("[controls]\n")
    with pytest.raises(ControlListError, match="empty"):
        load_controls(p)


def test_list_verification_is_an_error(tmp_path):
    p = tmp_path / "controls.toml"
    p.write_text('[controls.x]\ndescription = "d"\nverification = ["automated"]\n')
    with pytest.raises(ControlListError, match="x.*expected a string"):
        load_controls(p)


def test_dict_verification_is_an_error(tmp_path):
    p = tmp_path / "controls.toml"
    p.write_text('[controls.x]\ndescription = "d"\n[controls.x.verification]\nauto = true\n')
    with pytest.raises(ControlListError, match="x.*expected a string"):
        load_controls(p)


def test_numeric_verification_is_an_error(tmp_path):
    p = tmp_path / "controls.toml"
    p.write_text('[controls.x]\ndescription = "d"\nverification = 5\n')
    with pytest.raises(ControlListError, match="verification"):
        load_controls(p)


def test_boolean_verification_is_an_error(tmp_path):
    p = tmp_path / "controls.toml"
    p.write_text('[controls.x]\ndescription = "d"\nverification = true\n')
    with pytest.raises(ControlListError, match="verification"):
        load_controls(p)


def test_whitespace_only_description_is_an_error(tmp_path):
    p = tmp_path / "controls.toml"
    p.write_text('[controls.x]\ndescription = "   "\n')
    with pytest.raises(ControlListError, match="empty"):
        load_controls(p)


class TestUnknownKeysAndExtras:
    """A control list is the regulatory mapping of record, so a key that goes
    nowhere is worse than a rejected one. Before this, `phase = "OQ"` produced
    no error and no column, and so did a typo like `referance`.
    """

    @staticmethod
    def _write(tmp_path, body):
        p = tmp_path / "controls.toml"
        p.write_text(f'[controls.c1]\ndescription = "A control"\n{body}\n', encoding="utf-8")
        return p

    def test_an_unknown_key_is_rejected_and_the_message_points_at_extra(self, tmp_path):
        path = self._write(tmp_path, 'phase = "OQ"')
        with pytest.raises(ControlListError) as exc:
            load_controls(path)
        assert "unknown key phase" in str(exc.value)
        assert "[controls.c1.extra]" in str(exc.value)

    def test_a_misspelled_known_key_is_caught_rather_than_dropped(self, tmp_path):
        """The failure this actually prevents: a reference that silently
        vanishes from the matrix a reviewer reads."""
        path = self._write(tmp_path, 'referance = "21 CFR 11.10(e)"')
        with pytest.raises(ControlListError, match="unknown key referance"):
            load_controls(path)

    def test_several_unknown_keys_are_listed_together(self, tmp_path):
        path = self._write(tmp_path, 'phase = "OQ"\nowner = "QA"')
        with pytest.raises(ControlListError, match="unknown keys owner, phase"):
            load_controls(path)

    def test_an_extra_table_is_carried_through_verbatim(self, tmp_path):
        path = self._write(tmp_path, '[controls.c1.extra]\nphase = "OQ"\nsop = "SOP-QA-014"')
        assert load_controls(path)["c1"].extra == {"phase": "OQ", "sop": "SOP-QA-014"}

    def test_a_control_with_no_extra_table_gets_an_empty_dict(self, tmp_path):
        assert load_controls(self._write(tmp_path, "")).get("c1").extra == {}

    def test_a_non_string_extra_value_is_rejected_like_the_built_ins(self, tmp_path):
        """TOML reads a bare date as datetime.date, which the JSON encoder
        refuses and the CSV writer silently stringifies."""
        path = self._write(tmp_path, "[controls.c1.extra]\nqualified = 2024-01-01")
        with pytest.raises(ControlListError, match="expected a string"):
            load_controls(path)

    def test_an_extra_key_colliding_with_a_column_is_rejected(self, tmp_path):
        """Two `risk` columns in one CSV, and a spreadsheet takes the last."""
        path = self._write(tmp_path, '[controls.c1.extra]\nrisk = "high"')
        with pytest.raises(ControlListError, match="already a column"):
            load_controls(path)

    # As written in the TOML source. The control characters go in as escape
    # sequences because TOML rejects a raw newline or tab inside a key, which
    # is a second gate rather than the one under test here.
    @pytest.mark.parametrize("prefix", ["=", "+", "-", "@", "\\t", "\\r", "\\n"])
    def test_a_formula_leading_extra_key_is_rejected(self, tmp_path, prefix):
        """TOML allows a quoted key, so the column *name* is attacker-reachable
        and lands in the CSV header, which row-value neutralization misses."""
        path = self._write(tmp_path, f'[controls.c1.extra]\n"{prefix}HYPERLINK(1)" = "v"')
        with pytest.raises(ControlListError, match="reads as a formula"):
            load_controls(path)

    def test_a_key_merely_containing_a_formula_character_is_allowed(self):
        """Only the leading character matters to a spreadsheet."""
        import tempfile

        with tempfile.TemporaryDirectory() as d:
            path = self._write(Path(d), '[controls.c1.extra]\n"risk-tier" = "2"')
            assert load_controls(path)["c1"].extra == {"risk-tier": "2"}

    def test_an_extra_that_is_not_a_table_is_rejected(self, tmp_path):
        path = self._write(tmp_path, 'extra = "OQ"')
        with pytest.raises(ControlListError, match=r"\[controls.c1.extra\] must be a table"):
            load_controls(path)

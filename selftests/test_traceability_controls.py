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

import subprocess
import sys
from pathlib import Path

import tomllib

REPO = Path(__file__).resolve().parent.parent
EXAMPLE = REPO / "examples" / "part11_validation"


def test_example_directory_exists():
    assert (EXAMPLE / "test_part11_validation.feature").is_file()
    assert (EXAMPLE / "test_part11_validation.py").is_file()
    assert (EXAMPLE / "controls.toml").is_file()
    assert (EXAMPLE / "README.md").is_file()


def test_template_is_registered():
    from vip.cli import _SCAFFOLD_TEMPLATES

    assert "part11-validation" in _SCAFFOLD_TEMPLATES
    assert _SCAFFOLD_TEMPLATES["part11-validation"][0] == "part11_validation"


def test_template_is_bundled_into_the_wheel():
    """A template missing from force-include works in-repo and breaks when installed."""
    config = tomllib.loads((REPO / "pyproject.toml").read_text())
    includes = config["tool"]["hatch"]["build"]["targets"]["wheel"]["force-include"]
    assert includes["examples/part11_validation"] == "vip/_scaffold/part11_validation"


def test_every_control_tag_is_defined_in_controls_toml():
    feature = (EXAMPLE / "test_part11_validation.feature").read_text()
    tags = {
        tok.lstrip("@")
        for line in feature.splitlines()
        for tok in line.split()
        if tok.startswith("@control-")
    }
    controls = tomllib.loads((EXAMPLE / "controls.toml").read_text())["controls"]
    for tag in tags:
        assert tag.removeprefix("control-") in controls, f"{tag} missing from controls.toml"


def test_controls_toml_shows_the_not_automatable_path():
    """The worked example must demonstrate more than the happy path."""
    controls = tomllib.loads((EXAMPLE / "controls.toml").read_text())["controls"]
    verifications = {c.get("verification", "automated") for c in controls.values()}
    responsibilities = {c.get("responsibility") for c in controls.values()}
    assert verifications & {"manual", "procedural"}
    assert "customer" in responsibilities


def test_readme_states_it_is_not_an_attestation():
    text = (EXAMPLE / "README.md").read_text().lower()
    assert "not a certified" in text or "not an attestation" in text
    assert "electronic signature" in text


def test_scenarios_carry_literal_product_markers():
    """Feature-level Gherkin tags alone do not drive auto-skip in extensions."""
    steps = (EXAMPLE / "test_part11_validation.py").read_text()
    assert steps.count("@pytest.mark.connect") + steps.count("@pytest.mark.workbench") >= 3


def test_example_collects(tmp_path):
    """Collect with Connect "configured" so @connect scenarios aren't deselected.

    Without a config naming Connect, the plugin's product-config gate
    (``_should_deselect_for_product``) deselects every scenario here outright
    -- "no test at all", not "collected but skipped" -- which pytest reports
    as exit code 5. See ``test_workbench_ordering.py`` for the same pattern.
    """
    config_path = tmp_path / "vip.toml"
    config_path.write_text('[connect]\nurl = "https://connect.example.com"\n')
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            str(EXAMPLE),
            "--collect-only",
            "-q",
            f"--vip-config={config_path}",
        ],
        capture_output=True,
        text=True,
        cwd=REPO,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr

import subprocess
import sys
from pathlib import Path

import pytest
from _pytest.outcomes import Skipped

# tomllib is stdlib only from 3.11; tomli backfills it on 3.10, which CI runs.
# Same guard as src/vip/traceability.py.
if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib

REPO = Path(__file__).resolve().parent.parent
EXAMPLE = REPO / "examples" / "21CFR_part11_validation"


PRODUCTS = ("connect", "packagemanager", "workbench")


def test_example_directory_exists():
    for product in PRODUCTS:
        assert (EXAMPLE / f"test_21CFR_part11_{product}.feature").is_file()
        assert (EXAMPLE / f"test_21CFR_part11_{product}.py").is_file()
    assert (EXAMPLE / "part11_refusal.py").is_file()
    assert (EXAMPLE / "controls.toml").is_file()
    assert (EXAMPLE / "README.md").is_file()


def test_template_is_registered():
    from vip.cli import _SCAFFOLD_TEMPLATES

    assert "21cfr-part11-validation" in _SCAFFOLD_TEMPLATES
    assert _SCAFFOLD_TEMPLATES["21cfr-part11-validation"][0] == "21CFR_part11_validation"


def test_template_is_bundled_into_the_wheel():
    """A template missing from force-include works in-repo and breaks when installed."""
    config = tomllib.loads((REPO / "pyproject.toml").read_text())
    includes = config["tool"]["hatch"]["build"]["targets"]["wheel"]["force-include"]
    assert includes["examples/21CFR_part11_validation"] == "vip/_scaffold/21CFR_part11_validation"


def test_every_control_tag_is_defined_in_controls_toml():
    tags = {
        tok.lstrip("@")
        for path in EXAMPLE.glob("test_21CFR_part11_*.feature")
        for line in path.read_text().splitlines()
        for tok in line.split()
        if tok.startswith("@control-")
    }
    assert tags, "no control tags found -- the glob stopped matching the feature files"
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
    """Feature-level Gherkin tags alone do not drive auto-skip in extensions.

    Counts per file so a product whose step file forgot the decorator cannot
    hide behind another product's total.
    """
    for product, marker in (
        ("connect", "@pytest.mark.connect"),
        ("packagemanager", "@pytest.mark.package_manager"),
        ("workbench", "@pytest.mark.workbench"),
    ):
        path = EXAMPLE / f"test_21CFR_part11_{product}.py"
        lines = [line.strip() for line in path.read_text().splitlines()]
        # Decorator lines only -- a docstring naming the marker is not one.
        markers = lines.count(marker)
        scenarios = sum(1 for line in lines if line.startswith("@scenario("))
        assert markers == scenarios, (
            f"{path.name} has {scenarios} scenarios but {markers} {marker} decorators"
        )


def test_all_three_products_are_covered():
    """The example maps controls for the whole of Posit Team, not just Connect."""
    tags = {
        line.split()[0]
        for path in EXAMPLE.glob("test_21CFR_part11_*.feature")
        for line in path.read_text().splitlines()
        if line.startswith("@")
    }
    assert {"@connect", "@package_manager", "@workbench"} <= tags


def test_request_refused_step(pytester):
    """Unit-test ``assert_refused`` directly, no live deployment.

    The logic lives in ``part11_refusal`` rather than a step file because
    Connect and Workbench both use it, and one pytest-bdd step module cannot
    import another (``@scenario`` inspects the caller's frame at import time).

    A correctly-secured deployment fronted by OIDC/SAML or a forward-auth
    gateway answers an unauthenticated call with a redirect (302/307), not a
    bare 401/403 -- that must still count as a refusal. Only a 2xx (access
    actually granted) is a real control failure. A 5xx is a broken
    deployment, not evidence either way, so it fails with its own distinct
    message rather than being silently accepted as a refusal. A 404 is neither:
    it is what both refusal-by-hiding and a mistyped endpoint fixture return,
    so it skips rather than claiming evidence the run does not have.
    """
    (pytester.path / "conftest.py").write_text(
        f"import sys\nsys.path.insert(0, {str(EXAMPLE)!r})\n"
    )
    pytester.makepyfile(
        test_refused="""
import pytest
from part11_refusal import assert_refused


@pytest.mark.parametrize("status", [401, 403, 302, 307])
def test_accepts_refusal_statuses(status):
    assert_refused(status)


def test_fails_when_access_is_granted():
    assert_refused(200)


def test_fails_on_server_error_rather_than_passing():
    assert_refused(500)


def test_skips_on_404_rather_than_passing_or_failing():
    assert_refused(404)
"""
    )
    result = pytester.runpytest_subprocess("-p", "no:cacheprovider", "-rs")
    result.assert_outcomes(passed=4, failed=2, skipped=1)
    output = result.stdout.str()
    assert "access control is not enforced" in output
    assert "not evidence of a working access control" in output


def test_refusal_404_skip_explains_both_readings(monkeypatch):
    """The 404 skip must say why it is not a pass, in-process.

    Asserted here rather than in the subprocess above because VIP's plugin owns
    the terminal reporter, which drops skip reasons from the log even under
    ``-rs``. Importing ``part11_refusal`` directly is safe -- it holds no
    ``@scenario``, which is the whole reason the assertion lives in its own
    module.
    """
    monkeypatch.syspath_prepend(str(EXAMPLE))
    import part11_refusal

    with pytest.raises(Skipped) as excinfo:
        part11_refusal.assert_refused(404)
    message = str(excinfo.value)
    assert "refusal-by-hiding" in message
    assert "cannot tell them apart" in message


def test_example_collects(tmp_path):
    """Collect with all three products "configured" so nothing is deselected.

    Without a config naming a product, the plugin's product-config gate
    (``_should_deselect_for_product``) deselects that product's scenarios outright
    -- "no test at all", not "collected but skipped" -- which pytest reports
    as exit code 5. See ``test_workbench_ordering.py`` for the same pattern.
    """
    config_path = tmp_path / "vip.toml"
    config_path.write_text(
        '[connect]\nurl = "https://connect.example.com"\n'
        '[workbench]\nurl = "https://workbench.example.com"\n'
        '[package_manager]\nurl = "https://pm.example.com"\n'
    )
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

"""VIP Shiny app — graphical front end for running VIP tests."""

from __future__ import annotations

import asyncio
import sys
import tempfile
from pathlib import Path

from shiny import App, reactive, render, ui

from vip.gherkin import parse_feature_file

# ---------------------------------------------------------------------------
# Test categories — mirrors the pytest markers defined in pyproject.toml
# ---------------------------------------------------------------------------

CATEGORIES: dict[str, str] = {
    "prerequisites": "Prerequisites",
    "connect": "Connect",
    "workbench": "Workbench",
    "package_manager": "Package Manager",
    "cross_product": "Cross Product",
    "performance": "Performance",
    "security": "Security",
}

# ---------------------------------------------------------------------------
# Resolve project root and app directory
# ---------------------------------------------------------------------------

APP_DIR = Path(__file__).parent


def _find_project_root() -> Path:
    """Walk up from cwd looking for a directory containing both `tests/` and `pyproject.toml`."""
    candidate = Path.cwd()
    for _ in range(10):
        if (candidate / "tests").is_dir() and (candidate / "pyproject.toml").is_file():
            return candidate
        parent = candidate.parent
        if parent == candidate:
            break
        candidate = parent
    return Path.cwd()


# resolve() avoids symlink mismatches between cwd and Python's import paths
PROJECT_ROOT = _find_project_root().resolve()

# ---------------------------------------------------------------------------
# Parse feature files at startup for the category browser
# ---------------------------------------------------------------------------


def _load_category_features() -> dict[str, list[dict]]:
    """Return {category_key: [parsed_feature, ...]} for all .feature files."""
    tests_dir = PROJECT_ROOT / "tests"
    result: dict[str, list[dict]] = {}
    for key in CATEGORIES:
        cat_dir = tests_dir / key
        if not cat_dir.is_dir():
            continue
        features = []
        for fp in sorted(cat_dir.glob("*.feature")):
            parsed = parse_feature_file(fp, relative_to=PROJECT_ROOT)
            features.append(parsed)
        if features:
            result[key] = features
    return result


CATEGORY_FEATURES = _load_category_features()


def _build_category_accordion() -> ui.TagChild:
    """Build the right sidebar accordion with category checkboxes and feature details."""
    panels = []
    for key, label in CATEGORIES.items():
        features = CATEGORY_FEATURES.get(key, [])
        n_scenarios = sum(len(f.get("scenarios", [])) for f in features)

        # Feature details
        feature_items: list[ui.TagChild] = []
        for feat in features:
            title = feat.get("title", "Untitled")
            desc = feat.get("description", "")
            scenarios = feat.get("scenarios", [])

            scenario_tags: list[ui.TagChild] = []
            for sc in scenarios:
                steps = sc.get("steps", [])
                step_tags = [ui.tags.li(s, class_="vip-step") for s in steps]
                scenario_tags.append(
                    ui.tags.div(
                        ui.tags.div(sc["title"], class_="vip-scenario-title"),
                        ui.tags.ul(*step_tags, class_="vip-step-list") if step_tags else None,
                        class_="vip-scenario",
                    )
                )

            feature_items.append(
                ui.tags.div(
                    ui.tags.div(
                        ui.tags.i(class_="bi bi-file-earmark-text me-1"),
                        title,
                        class_="vip-feature-title",
                    ),
                    ui.tags.div(desc, class_="vip-feature-desc") if desc else None,
                    *scenario_tags,
                    class_="vip-feature-block",
                )
            )

        count_badge = ui.span(
            f"{n_scenarios} test{'s' if n_scenarios != 1 else ''}",
            class_="badge text-bg-secondary ms-1",
            style="font-size: 0.7rem; vertical-align: middle;",
        )

        default_on = key == "prerequisites"
        panels.append(
            ui.accordion_panel(
                ui.span(label, " ", count_badge),
                ui.input_switch(f"cat_{key}", "Include in run", value=default_on),
                *feature_items if feature_items else [ui.tags.small("No feature files found.")],
                value=key,
            )
        )

    return ui.accordion(
        *panels,
        id="cat_accordion",
        open="prerequisites",
        multiple=True,
    )


# ---------------------------------------------------------------------------
# Theme from _brand.yml
# ---------------------------------------------------------------------------

theme = ui.Theme.from_brand(APP_DIR / "_brand.yml")

# ---------------------------------------------------------------------------
# Custom CSS for the category browser
# ---------------------------------------------------------------------------

_app_css = ui.tags.style("""
.vip-feature-block {
    margin-bottom: 0.75rem;
    padding-bottom: 0.75rem;
    border-bottom: 1px solid var(--bs-border-color-translucent);
}
.vip-feature-block:last-child { border-bottom: none; margin-bottom: 0; padding-bottom: 0; }
.vip-feature-title {
    font-weight: 600; font-size: 0.8125rem; color: var(--bs-emphasis-color);
    margin-bottom: 0.125rem;
}
.vip-feature-desc {
    font-size: 0.75rem; color: var(--bs-secondary-color);
    margin-bottom: 0.375rem; line-height: 1.4;
}
.vip-scenario { margin-bottom: 0.375rem; }
.vip-scenario-title {
    font-size: 0.8rem; font-weight: 500; color: var(--bs-body-color);
    padding-left: 0.25rem;
}
.vip-step-list {
    list-style: none; padding-left: 1rem; margin: 0.125rem 0 0 0;
}
.vip-step {
    font-size: 0.75rem; font-family: var(--bs-font-monospace);
    color: var(--bs-secondary-color); line-height: 1.5;
}
.vip-step::before { content: "› "; color: var(--bs-tertiary-color); }
""")

# ---------------------------------------------------------------------------
# UI
# ---------------------------------------------------------------------------

app_ui = ui.page_sidebar(
    ui.sidebar(
        # --- Run / Stop ---
        ui.div(
            ui.output_ui("run_btn_ui", class_="flex-fill"),
            ui.output_ui("stop_btn_ui", class_="flex-fill"),
            class_="d-flex gap-2 mb-2",
        ),
        ui.output_ui("config_validation_msg"),
        # --- Configuration ---
        ui.accordion(
            ui.accordion_panel(
                "Product URLs",
                ui.input_text(
                    "connect_url",
                    "Connect",
                    value="",
                    placeholder="https://connect.example.com",
                    width="100%",
                ),
                ui.input_text(
                    "workbench_url",
                    "Workbench",
                    value="",
                    placeholder="https://workbench.example.com",
                    width="100%",
                ),
                ui.input_text(
                    "pm_url",
                    "Package Manager",
                    value="",
                    placeholder="https://packagemanager.example.com",
                    width="100%",
                ),
                value="urls",
            ),
            ui.accordion_panel(
                "Authentication",
                ui.input_switch(
                    "interactive_auth",
                    "Interactive auth (browser login)",
                    value=True,
                ),
                value="auth",
            ),
            ui.accordion_panel(
                "Advanced",
                ui.input_text(
                    "extra_args",
                    "Extra pytest args",
                    placeholder="-x -k 'login'",
                    width="100%",
                ),
                value="advanced",
            ),
            open="urls",
            multiple=True,
        ),
        width=260,
    ),
    # --- Main content with right sidebar ---
    ui.layout_sidebar(
        ui.sidebar(
            ui.tags.div(
                ui.tags.i(class_="bi bi-list-check me-1"),
                "Test Categories",
                class_="fw-bold",
                style="font-size: 0.9rem;",
            ),
            ui.output_ui("category_summary"),
            _build_category_accordion(),
            position="right",
            width=340,
            open={"desktop": "open", "mobile": "closed"},
            id="right_sidebar",
        ),
        ui.navset_pill(
            ui.nav_panel(
                ui.span(ui.tags.i(class_="bi bi-file-earmark-bar-graph me-1"), "Report"),
                ui.div(
                    ui.output_ui("status_badge"),
                    ui.output_ui("report_view"),
                    class_="pt-3",
                ),
                value="report",
            ),
            ui.nav_panel(
                ui.span(ui.tags.i(class_="bi bi-terminal me-1"), "Test Output"),
                ui.div(
                    ui.output_ui("test_output_area"),
                    class_="pt-3",
                ),
                value="output",
            ),
            id="tabs",
            selected="report",
        ),
    ),
    ui.head_content(
        ui.tags.link(
            rel="stylesheet",
            href="https://cdn.jsdelivr.net/npm/bootstrap-icons@1.11.3/font/bootstrap-icons.min.css",
        ),
        _app_css,
    ),
    title=ui.div(
        ui.img(
            src="logo-vip.svg",
            height="22px",
            style="vertical-align: middle; margin-right: 0.5rem; opacity: 0.9;",
        ),
        ui.span("VIP", style="font-weight:700; letter-spacing:0.04em;"),
        ui.span(
            " — Verified Installation of Posit",
            style="font-weight:400; opacity:0.7;",
        ),
        style="display:inline-flex; align-items:center;",
    ),
    theme=theme,
    fillable=True,
)

# ---------------------------------------------------------------------------
# Server
# ---------------------------------------------------------------------------


def server(input, output, session):
    # Reactive state
    output_lines: reactive.Value[list[str]] = reactive.value([])
    run_status: reactive.Value[str] = reactive.value("idle")  # idle | running | passed | failed
    process_handle: reactive.Value[asyncio.subprocess.Process | None] = reactive.value(None)
    run_counter: reactive.Value[int] = reactive.value(0)

    # --- collect selected categories from individual switches ---
    @reactive.calc
    def selected_categories() -> list[str]:
        return [key for key in CATEGORIES if input[f"cat_{key}"]()]

    # --- category summary strip in right sidebar ---
    @render.ui
    def category_summary():
        pills: list[ui.TagChild] = []
        for key, label in CATEGORIES.items():
            included = input[f"cat_{key}"]()
            if included:
                pills.append(
                    ui.span(
                        label,
                        class_="badge text-bg-success me-1 mb-1",
                        style="font-size: 0.7rem;",
                    )
                )
            else:
                pills.append(
                    ui.span(
                        label,
                        class_="badge text-bg-light text-body-tertiary me-1 mb-1",
                        style="font-size: 0.7rem; text-decoration: line-through;",
                    )
                )
        n = len(selected_categories())
        return ui.div(
            ui.div(*pills, class_="d-flex flex-wrap mb-1"),
            ui.tags.small(
                f"{n} of {len(CATEGORIES)} categories included",
                class_="text-body-secondary",
            ),
            class_="mb-2",
        )

    # --- build pytest command ---
    def _build_command() -> tuple[list[str], str | None]:
        """Return (command_args, temp_config_path_or_None)."""
        # Explicit rootdir + test path avoids stale installs or symlink mismatches
        cmd = [
            sys.executable,
            "-m",
            "pytest",
            f"--rootdir={PROJECT_ROOT}",
            str(PROJECT_ROOT / "tests"),
        ]
        temp_config = None

        connect_url = input.connect_url().strip()
        workbench_url = input.workbench_url().strip()
        pm_url = input.pm_url().strip()

        # Always generate a temp config so pytest never falls back to a stale vip.toml
        lines = ["[general]", 'deployment_name = "Posit Team"', ""]
        if connect_url:
            lines.extend(["[connect]", f'url = "{connect_url}"', ""])
        else:
            lines.extend(["[connect]", "enabled = false", ""])
        if workbench_url:
            lines.extend(["[workbench]", f'url = "{workbench_url}"', ""])
        else:
            lines.extend(["[workbench]", "enabled = false", ""])
        if pm_url:
            lines.extend(["[package_manager]", f'url = "{pm_url}"', ""])
        else:
            lines.extend(["[package_manager]", "enabled = false", ""])

        with tempfile.NamedTemporaryFile(mode="w", suffix=".toml", delete=False) as f:
            f.write("\n".join(lines) + "\n")
            temp_config = f.name
        cmd.append(f"--vip-config={temp_config}")

        if input.interactive_auth() and connect_url:
            cmd.append("--interactive-auth")

        report_path = str(PROJECT_ROOT / "report" / "results.json")
        cmd.append(f"--vip-report={report_path}")

        # Category filter from switches
        selected = selected_categories()
        if selected and len(selected) < len(CATEGORIES):
            marker_expr = " or ".join(selected)
            cmd.extend(["-m", marker_expr])

        # Extra pytest args
        extra = input.extra_args().strip()
        if extra:
            import shlex

            cmd.extend(shlex.split(extra))

        return cmd, temp_config

    # --- run tests ---
    @reactive.effect
    @reactive.event(input.run_btn)
    async def _run_tests():
        # Do not start a new run while tests are running or shutting down
        if run_status() in ("running", "stopping"):
            return

        cmd, temp_config = _build_command()

        # Remove stale results so the report doesn't show old data on failure
        report_json = PROJECT_ROOT / "report" / "results.json"
        report_json.unlink(missing_ok=True)

        output_lines.set([f"$ {' '.join(cmd)}", ""])
        run_status.set("running")
        ui.update_navs("tabs", selected="output")

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                cwd=str(PROJECT_ROOT),
            )
            process_handle.set(proc)

            assert proc.stdout is not None
            while True:
                line = await proc.stdout.readline()
                if not line:
                    break
                decoded = line.decode("utf-8", errors="replace").rstrip("\n")
                current = output_lines()
                current.append(decoded)
                output_lines.set(current)

            await proc.wait()
            process_handle.set(None)

            rc = proc.returncode or 0
            current = output_lines()
            current.append("")
            current.append(f"Process exited with code {rc}")
            output_lines.set(current)
            run_status.set("passed" if rc == 0 else "failed")
            run_counter.set(run_counter() + 1)
        except Exception as exc:
            current = output_lines()
            current.append("")
            current.append(f"Error: {exc}")
            output_lines.set(current)
            run_status.set("failed")
            run_counter.set(run_counter() + 1)
        finally:
            if temp_config:
                Path(temp_config).unlink(missing_ok=True)

    # --- stop tests ---
    @reactive.effect
    @reactive.event(input.stop_btn)
    async def _stop_tests():
        proc = process_handle()
        if proc is not None:
            proc.terminate()
            current = output_lines()
            output_lines.set([*current, "", "--- Tests stopped by user ---"])
            # Mark as stopping so the UI stays disabled until cleanup completes
            run_status.set("stopping")

    # --- auto-switch to report tab when tests finish ---
    @reactive.effect
    def _auto_switch_to_report():
        st = run_status()
        if st in ("passed", "failed"):
            ui.update_navs("tabs", selected="report")

    # --- config validation ---
    @reactive.calc
    def config_error() -> str | None:
        """Return an error message if the current config is invalid, else None."""
        if input.interactive_auth() and not input.connect_url().strip():
            return "Interactive auth requires a Connect URL."
        return None

    # --- run button (disabled when config is invalid or tests are running) ---
    @render.ui
    def run_btn_ui():
        disabled = config_error() is not None or run_status() in ("running", "stopping")
        return ui.input_action_button(
            "run_btn",
            ui.span(ui.tags.i(class_="bi bi-play-fill me-1"), "Run Tests"),
            class_="btn-primary w-100",
            disabled="disabled" if disabled else None,
        )

    @render.ui
    def config_validation_msg():
        err = config_error()
        if err is None:
            return None
        return ui.div(
            ui.tags.i(class_="bi bi-exclamation-triangle-fill me-1"),
            err,
            class_="text-warning-emphasis small mb-2",
            style="font-size: 0.8rem;",
        )

    # --- stop button (disabled unless running) ---
    @render.ui
    def stop_btn_ui():
        disabled = run_status() != "running"
        return ui.input_action_button(
            "stop_btn",
            ui.span(ui.tags.i(class_="bi bi-stop-fill me-1"), "Stop"),
            class_="btn-outline-danger w-100",
            disabled="disabled" if disabled else None,
        )

    # --- status badge ---
    @render.ui
    def status_badge():
        st = run_status()
        badge_class = {
            "idle": "text-bg-secondary",
            "running": "text-bg-primary",
            "passed": "text-bg-success",
            "failed": "text-bg-danger",
        }
        label = st.upper()
        if st == "running":
            label = "RUNNING…"
        cls = badge_class.get(st, "text-bg-secondary")
        return ui.span(
            label,
            class_=f"badge {cls}",
            style="font-size: 0.8rem; letter-spacing: 0.04em; margin-bottom: 0.75rem;",
        )

    # --- test output ---
    @render.ui
    def test_output_area():
        lines = output_lines()
        if not lines:
            return ui.tags.pre(
                "Click 'Run Tests' to start.",
                class_="bg-body-tertiary border rounded p-3",
                style=(
                    "font-family: var(--bs-font-monospace); font-size: 0.8125rem;"
                    " white-space: pre-wrap; max-height: 70vh; overflow-y: auto;"
                    " color: var(--bs-secondary-color);"
                ),
            )
        return ui.tags.pre(
            "\n".join(lines),
            class_="border rounded p-3",
            style=(
                "font-family: var(--bs-font-monospace); font-size: 0.8125rem;"
                " white-space: pre-wrap; max-height: 70vh; overflow-y: auto;"
                " background: #1e293b; color: #e2e8f0;"
            ),
        )

    # --- report view ---
    @render.ui
    def report_view():
        st = run_status()
        run_counter()  # force re-render after every run

        # Always show spinner while running — never fall through to stale file data
        if st == "running":
            return ui.div(
                ui.tags.div(
                    class_="spinner-border spinner-border-sm me-2",
                    role="status",
                ),
                "Tests are running… Report will appear when complete.",
                class_="alert alert-info d-flex align-items-center",
                role="alert",
            )

        report_path = PROJECT_ROOT / "report" / "results.json"
        if not report_path.exists():
            if st in ("passed", "failed"):
                return ui.div(
                    "No report file found at ",
                    ui.tags.code(str(report_path)),
                    class_="alert alert-warning",
                    role="alert",
                )
            return ui.div(
                ui.tags.i(
                    class_="bi bi-info-circle me-2",
                    style="font-size:1.25rem; vertical-align:middle;",
                ),
                "No report available yet. Run tests to generate a report.",
                class_="alert alert-secondary",
                role="alert",
            )

        from vip.report_html import render_report_html
        from vip.reporting import load_results, load_troubleshooting

        data = load_results(report_path)
        troubleshooting_path = PROJECT_ROOT / "tests" / "troubleshooting.toml"
        hints = load_troubleshooting(troubleshooting_path)

        html = render_report_html(
            data,
            troubleshooting=hints,
            project_root=PROJECT_ROOT,
        )

        return ui.HTML(html)


# ---------------------------------------------------------------------------
# App object — serve static assets from the app directory
# ---------------------------------------------------------------------------

app = App(
    app_ui,
    server,
    static_assets=str(APP_DIR),
)

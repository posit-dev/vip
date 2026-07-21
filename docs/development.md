# Development

## Setup

```bash
# Install uv (if you don't have it)
curl -LsSf https://astral.sh/uv/install.sh | sh

# Install all dependencies (including dev tools like ruff)
uv sync

# Or with pip
pip install -e ".[dev]"
```

## Linting and formatting

VIP uses [ruff](https://docs.astral.sh/ruff/) for both linting and code
formatting.  The easiest way to run checks is with [just](https://just.systems/):

```bash
just check          # run both lint and format checks
just fix            # auto-fix lint issues and reformat

# Or individually
just lint           # ruff check
just format-check   # ruff format --check
just lint-fix       # ruff check --fix
just format         # ruff format
```

Without just, run ruff directly:

```bash
uv run ruff check src/ src/vip_tests/        # lint
uv run ruff format --check src/ src/vip_tests/  # format check
uv run ruff check --fix src/ src/vip_tests/  # auto-fix lint
uv run ruff format src/ src/vip_tests/       # reformat
```

## Type checking

```bash
uv run mypy src/
```

## The lockfile

`uv.lock` is committed and must stay reproducible across machines. The uv
version is pinned so relocking always produces the same output:

- `pyproject.toml`'s `[tool.uv] required-version = ">=0.11"` rejects any uv
  older than 0.11 for **every** uv command in this repo. Older uv (e.g. the
  0.6.x still shipped by some package managers) strips the `upload-time` wheel
  annotations and writes an older lockfile revision, which churns ~2000 lines
  on any relock. If uv refuses to run, upgrade it (`uv self update`, or
  `brew upgrade uv`).
- `just relock` regenerates the lockfile with an **exact** pinned uv version
  (`UV_VERSION` in the `justfile`), fetched via `uvx` — so the output is
  identical even when your local uv is a different version. Always relock with
  this recipe rather than a bare `uv lock`:

  ```bash
  just relock
  ```

  When bumping the pin, change both `UV_VERSION` in the `justfile` and the
  `required-version` floor in `pyproject.toml` together.

### Resolving a uv.lock merge conflict

Never hand-edit conflict markers in `uv.lock`. Take either side wholesale, then
regenerate deterministically:

```bash
git checkout --theirs -- uv.lock   # or --ours; the starting point doesn't matter
just relock                     # re-resolves from pyproject.toml with the pinned uv
git add uv.lock
```

Because the uv version is pinned, the regenerated lockfile is identical to what
CI and other contributors produce, so the conflict resolves cleanly.

## Dependency pinning policy

The wheel published to PyPI carries the version constraints declared in
`pyproject.toml`'s `[project.dependencies]`, so `uv tool install posit-vip` and
`pip install posit-vip` resolve against them. To keep a fresh install
predictable (see [#399](https://github.com/posit-dev/vip/issues/399)):

- **Exact `==` pins** for the dependencies that shape a `vip` run's output —
  `pytest`, `pytest-bdd`, `pytest-order`, `pytest-playwright`, `pytest-xdist`,
  and `playwright`. Each pin must equal the version resolved in `uv.lock`;
  `selftests/test_dependency_pins.py` fails if they drift apart.
- **Next-major caps** (e.g. `requests>=2.33.0,<3`) on every other runtime
  dependency, so a breaking major release cannot land on install. The `report`
  and `load` optional groups are capped the same way; the `dev` group is left
  uncapped by this policy (aside from `ruff`'s pre-existing narrow range).

Bumps flow through Dependabot's `uv` job (weekly, 7-day cooldown): it raises the
pin or cap in `pyproject.toml` and updates `uv.lock` in one PR, which CI gates
before merge. The next release then ships the tested set. To bump a pin by hand,
edit the constraint and run `just relock` in the same commit.

## Design principles

- **Non-destructive** — tests create, verify, and clean up their own content.
  They never modify or delete existing customer content.
- **Diagnostic** — tests are sequenced so failures localize problems.
  Prerequisites run first; product tests follow.
- **Loosely coupled** — the suite avoids tight coupling to product client
  libraries.  API calls use plain HTTP where practical.
- **Duplication over coupling** — code duplication with product-internal test
  suites is acceptable if it keeps VIP independent and version-flexible.

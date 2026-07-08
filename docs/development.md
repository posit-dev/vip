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
  (`UV_VERSION` in the `justfile`), fetched via `uvx` so it doesn't matter which
  uv you have installed. Always relock with this recipe rather than a bare
  `uv lock`:

  ```bash
  just relock
  ```

  When bumping the pin, change both `UV_VERSION` in the `justfile` and the
  `required-version` floor in `pyproject.toml` together.

### Resolving a uv.lock merge conflict

Never hand-edit conflict markers in `uv.lock`. Take either side wholesale, then
regenerate deterministically:

```bash
git checkout --theirs uv.lock   # or --ours; the starting point doesn't matter
just relock                     # re-resolves from pyproject.toml with the pinned uv
git add uv.lock
```

Because the uv version is pinned, the regenerated lockfile is identical to what
CI and other contributors produce, so the conflict resolves cleanly.

## Design principles

- **Non-destructive** — tests create, verify, and clean up their own content.
  They never modify or delete existing customer content.
- **Diagnostic** — tests are sequenced so failures localize problems.
  Prerequisites run first; product tests follow.
- **Loosely coupled** — the suite avoids tight coupling to product client
  libraries.  API calls use plain HTTP where practical.
- **Duplication over coupling** — code duplication with product-internal test
  suites is acceptable if it keeps VIP independent and version-flexible.

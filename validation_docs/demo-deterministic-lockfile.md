# Feature: deterministic uv.lock handling (#425 part 2)

*2026-07-08T16:21:01Z by Showboat 0.6.1*
<!-- showboat-id: 6c558e25-212d-40cf-88f3-48535733826c -->

Local uv 0.6.3 strips the `upload-time` wheel annotations and writes an older lockfile revision, churning ~2000 lines on any relock and driving constant merge conflicts. This change pins the uv version used for locking so `uv.lock` is byte-reproducible everywhere: a `required-version` floor in pyproject.toml, a pinned `just relock` recipe, and contributor docs for deterministic conflict resolution.

```bash
sed -n '/^\[tool.uv\]/,/^$/p' pyproject.toml
```

```output
[tool.uv]
# Pin the uv version used in this repo so `uv.lock` is reproducible across
# machines. Older uv (< 0.11) strips the `upload-time` wheel annotations and
# uses an older lockfile revision, which churns ~2000 lines on any relock. The
# floor rejects those versions for every uv command; `just relock` pins an exact
# version on top of it. See docs/development.md ("The lockfile").
required-version = ">=0.11"

```

```bash
grep -A1 '^UV_VERSION' justfile; echo; grep -A7 '^# Regenerate uv.lock' justfile
```

```output
UV_VERSION := "0.11.28"


# Regenerate uv.lock with the pinned uv version (see UV_VERSION above).
# Use this instead of a bare `uv lock` so the lockfile is byte-reproducible
# regardless of the uv installed locally — `uvx` fetches the exact pin. This is
# also how you resolve a uv.lock merge conflict: take either side, then relock.
#   git checkout --theirs uv.lock && just relock
relock:
    uvx --from uv=={{ UV_VERSION }} uv lock

```

**Proof 1 — determinism.** Regenerating with the pinned uv leaves the committed `uv.lock` byte-identical (no churn), so a fresh relock never fights the lockfile:

```bash
just relock >/dev/null 2>&1; if [ -z "$(git status --porcelain uv.lock)" ]; then echo "just relock -> uv.lock unchanged (byte-identical to committed)"; else echo "CHANGED:"; git --no-pager diff --stat uv.lock; fi
```

```output
just relock -> uv.lock unchanged (byte-identical to committed)
```

**Proof 2 — the floor guards against a stray relock.** `uv lock --check` confirms the committed lockfile matches the pinned uv's output, and `required-version` refuses any uv below 0.11 for every command in the repo:

```bash
uvx --from uv==0.11.28 uv lock --check >/dev/null 2>&1 && echo "uv lock --check: committed uv.lock matches pinned-uv (0.11.28) output"
```

```output
uv lock --check: committed uv.lock matches pinned-uv (0.11.28) output
```

**Lint and format** stay green (this change touches config, the justfile, and docs — no Python):

```bash
env -u VIRTUAL_ENV just check 2>&1 | sed "s/ in [0-9.]*s//"
```

```output
uv run ruff check src/ selftests/ examples/ docker/
All checks passed!
uv run ruff format --check src/ selftests/ examples/ docker/
149 files already formatted
```

**Docs.** `docs/development.md` gains a "The lockfile" section explaining the pin, the `just relock` recipe, and deterministic merge-conflict resolution (`git checkout --theirs uv.lock && just relock` — take either side, then regenerate).

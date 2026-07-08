# Fix: Workbench git-ops clone reuses stale directory (#438)

*2026-07-08T15:46:55Z by Showboat 0.6.1*
<!-- showboat-id: 74ec94bb-ee79-49c2-9bfa-0b395cf9760d -->

Every Workbench git-ops clone scenario clones into the fixed path /tmp/jumpstart_examples,
and nothing ever removes it. On long-lived QA VMs (Workbench scenarios run serially against
one VM), a leftover clone directory from a prior IDE scenario or a previous day's run makes
git clone fail with "destination path already exists and is not an empty directory".

Fix: _do_clone (src/vip_tests/workbench/test_git_ops.py) now removes any pre-existing
destination directory before cloning, so each clone scenario is self-contained regardless
of what a prior run left behind. New selftests in selftests/test_workbench_git_ops.py pin
down the command construction by monkeypatching terminal_run and asserting the built
shell command runs "rm -rf <clone_dir>" before "git clone".

```bash
uv run pytest selftests/test_workbench_git_ops.py -q 2>&1 | grep -E 'passed|failed|error' | sed 's/ in [0-9.]*s//'
```

```output
2 passed
```

```bash
uv run pytest selftests/ -q 2>&1 | grep -E 'passed|failed|error' | sed 's/ in [0-9.]*s//'
```

```output
890 passed, 26 warnings
```

```bash
just check
```

```output
uv run ruff check src/ selftests/ examples/ docker/
All checks passed!
uv run ruff format --check src/ selftests/ examples/ docker/
150 files already formatted
```

```bash
sed -n '372,393p' src/vip_tests/workbench/test_git_ops.py
```

```output
def _do_clone(
    page: Page,
    git_session_ctx: dict,
    git_cfg,
    readback_lang: str,
    *,
    workdir: str = "/tmp",
) -> str:
    """Run ``git clone`` in the IDE terminal and return the cloned directory path."""
    auth_url = _inject_token_into_url(git_cfg.clone_url, git_cfg.token)
    repo_dir = _repo_dir_from_url(git_cfg.clone_url)
    clone_dir = f"{workdir}/{repo_dir}"

    terminal_run(
        page,
        f"rm -rf {shlex.quote(clone_dir)} && cd {shlex.quote(workdir)} && "
        f"GIT_TERMINAL_PROMPT=0 git clone {shlex.quote(auth_url)}",
        timeout=_TIMEOUT_GIT_NETWORK,
        readback_lang=readback_lang,
    )
    git_session_ctx["clone_dir"] = clone_dir
    return clone_dir
```

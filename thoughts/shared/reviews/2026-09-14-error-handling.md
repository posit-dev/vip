# Review: error-handling

## Summary

The design doc's premise that VIP has "no custom exception classes" is wrong: `src/vip/auth.py` already defines `AuthConfigError(ValueError)` and `AuthTimeoutError(AuthConfigError)`, and three separate sites (`cli.py:1364`, `plugin.py:341`, `plugin.py:399`) each independently catch and translate it. Wave 2 is not building a hierarchy from scratch, it is deciding whether the new `VipError` tree replaces, wraps, or coexists with this one, and that decision belongs in the design doc before any PR is written. Second, `cli.py` uses `argparse`, not Typer, so the design's "single top-level handler... maps `VipError` to an exit code" needs a concrete target: the single `args.func(args)` dispatch at `cli.py:2050` is that target, and every reference to `typer.Exit` in the plan should be corrected. Third, of the 120 `BLE001` sites, roughly 47 are a bare `except Exception: pass/continue/return` with zero explanatory comment (severity class a) and roughly 34 convert to an undocumented sentinel return (class c) — several of those sentinels actively hide a real failure behind a value that also means "nothing to do" (`clients/connect.py:269` returns `[]` on any exception, used by content cleanup; `clients/workbench.py` mixes `-1`/`False`/bare `return` for the same "API call failed" case with no shared convention). The auth.py polling loops that most need narrowing already import and use the concrete Playwright/httpx exception types elsewhere in the same file, so the narrowing work is mechanical, not exploratory.

## Findings

### Design doc's error-hierarchy premise ignores an existing exception class
Severity: high
Evidence: src/vip/auth.py:53 `class AuthConfigError(ValueError):`
Evidence: src/vip/auth.py:57 `class AuthTimeoutError(AuthConfigError):`
Evidence: src/vip/cli.py:1364 `    except AuthConfigError as exc:`
Evidence: src/vip/plugin.py:341 `            except AuthConfigError as exc:`
Evidence: src/vip/plugin.py:399 `            except AuthConfigError as exc:`
Why it matters to a newcomer: the design doc states "no custom exception classes" as a fact about the codebase. A newcomer implementing wave 2 from the doc alone will build a parallel `AuthError` without realizing `AuthConfigError` already carries this responsibility across `auth.py`, `idp.py`, `totp.py`, `cli.py`, and `plugin.py`, and has fifteen selftests (`selftests/test_auth.py`, `test_idp.py`, `test_totp.py`, `test_cli_cleanup.py`) pinned to its name and subclass relationship.
Proposed fix: before any wave-2 PR, amend the design doc's hierarchy to either (a) make `AuthError(VipError)` a compatibility alias / re-export of `AuthConfigError` so existing selftests keep passing, or (b) explicitly deprecate `AuthConfigError` and migrate every raise/except site and every selftest in the same PR. Pick (a) unless the coordinator wants a bigger single PR — (b) touches five modules and five selftest files at once.
Proposed PR: vip-error-hierarchy (files: src/vip/errors.py, src/vip/auth.py, src/vip/cli.py, src/vip/plugin.py)

### `cli.py` is argparse, not Typer — the design's exit-path grep and "single handler" target need correcting
Severity: medium
Evidence: src/vip/cli.py:2050 `    args.func(args)`
Evidence: (zero hits) `git grep -n 'typer\.Exit' -- '*.py'`
Evidence: src/vip/cli.py:1573 `def main() -> None:` (builds an `argparse.ArgumentParser`, not a Typer `app`)
Why it matters to a newcomer: the design doc's error-handling rules and structure design both say the target is "`cli.py`'s single top-level handler" reached via a Typer `app.py`. A newcomer following the doc literally will look for a Typer app that does not exist, or introduce one as an unplanned migration. The good news is a single handler is still cheap: there is already exactly one dispatch call.
Proposed fix: correct the design doc to say the handler wraps `args.func(args)` at cli.py:2050 in a `try/except VipError` that prints the message and calls `sys.exit(exc.exit_code)`, with no framework migration implied.
Proposed PR: vip-error-hierarchy (files: src/vip/cli.py) — same PR as the hierarchy, since the handler has nothing to wrap until `VipError` exists.

### No single exit handler exists yet: 37 `sys.exit` calls and three duplicated `AuthConfigError` translations
Severity: high
Evidence: src/vip/cli.py:164 `        print(f"Error: {exc}", file=sys.stderr)` (followed by `sys.exit(1)` at cli.py:165)
Evidence: src/vip/cli.py:1364 `    except AuthConfigError as exc:` / cli.py:1365 `        print(f"Error: could not authenticate to Workbench: {exc}", file=sys.stderr)` / cli.py:1366 `        sys.exit(1)`
Evidence: src/vip/cli.py:1495 `        sys.exit(1)`
Evidence: src/vip/cli.py:2049 `        sys.exit(1)`
Evidence: full list — `git grep -n -E 'sys\.exit|typer\.Exit|raise SystemExit|os\._exit' -- 'src/**/*.py'` (37 sites, all `sys.exit`, all in `cli.py`; zero `typer.Exit`)
Why it matters to a newcomer: every command function prints its own `Error:` string and calls `sys.exit(1)` directly, so there is no single place that decides exit codes or message formatting. `plugin.py:341` and `plugin.py:399` each convert the same `AuthConfigError` to `pytest.UsageError` independently of `cli.py`'s conversion, so a message wording change has to be made in three places to stay consistent.
Proposed fix: introduce the `VipError` hierarchy with an `exit_code` attribute, replace the 37 `print(...); sys.exit(1)` pairs with `raise <SubclassError>(...)`, and let the single handler at cli.py:2050 do the printing and exiting. `plugin.py`'s two `except AuthConfigError: raise pytest.UsageError(...)` sites stay as-is (pytest's own exit mechanism), but reference the same `VipError` base going forward.
Proposed PR: vip-cli-single-handler (files: src/vip/cli.py) — depends on vip-error-hierarchy.

### `auth.py` cache-metadata parse silently swallows more than its sibling three lines away
Severity: high
Evidence: src/vip/auth.py:255 `        except (OSError, ValueError):` (narrow, three lines after the equivalent `json.loads` call at auth.py:253-254)
Evidence: src/vip/auth.py:528 `        except Exception:` (same file, same operation: parsing `.meta.json`, no comment)
Why it matters to a newcomer: two functions in the same file parse the identical cache metadata file. One already narrows to `(OSError, ValueError)` — proof the concrete exception set is known. The other catches everything and continues with stale/empty variables, which would also mask a `meta.get(...)` call raising `AttributeError` if the JSON root were ever a list instead of a dict (a corrupt-cache case this file explicitly worries about at line 251-253 for the sibling function).
Proposed fix: narrow `auth.py:528` to `except (OSError, ValueError, AttributeError):` matching the sibling's reasoning, and add the one-line comment the design's `BLE001` policy requires.
Proposed PR: vip-narrow-auth-except (files: src/vip/auth.py)

### `clients/connect.py` returns an empty list on any failure, indistinguishable from "nothing to clean up"
Severity: high
Evidence: src/vip/clients/connect.py:266 `            resp = self._client.get(f"/v1/tags/{tag_id}/content")`
Evidence: src/vip/clients/connect.py:269 `        except Exception:` / connect.py:270 `            return []`
Why it matters to a newcomer: this method feeds `cleanup_vip_content()` (connect.py:271 onward). If the Connect API is unreachable or the tag lookup 500s, the caller sees the same `[]` it would see if there really were zero tagged VIP items, and cleanup silently no-ops. A newcomer debugging "why didn't cleanup remove my test content" has no signal that the lookup itself failed.
Proposed fix: raise a `ConnectUnreachableError` (or the eventual `ProductUnreachableError` subclass) instead of returning `[]`, and let `cleanup_vip_content` decide whether a failed lookup should abort cleanup or log and continue — but that decision should be explicit, not hidden in a sentinel.
Proposed PR: vip-narrow-clients-except (files: src/vip/clients/connect.py, src/vip/clients/workbench.py, src/vip/clients/packagemanager.py)

### `clients/workbench.py` uses three different undocumented sentinels for the same failure mode
Severity: medium
Evidence: src/vip/clients/workbench.py:254 `        except Exception:` / workbench.py:255 `            return -1`
Evidence: src/vip/clients/workbench.py:277 `        except Exception:` / workbench.py:278 `            return False`
Evidence: src/vip/clients/workbench.py:332 `            except Exception:` / workbench.py:333 `                # Connection error, non-JSON body, etc. — give up this run.` (documented)
Evidence: src/vip/clients/workbench.py:363 `        except Exception:` / workbench.py:364 `            return` (bare, no comment, no return value — different shape again)
Why it matters to a newcomer: four sibling methods on the same client class fail the same way (an unreachable API or a non-JSON body) and each signals it differently — `-1`, `False`, a documented early `break`, and a bare `return` with no value. A newcomer adding a fifth method has no single pattern to copy and will likely invent a sixth sentinel.
Proposed fix: pick one convention (raise `ProductUnreachableError` and let callers decide, per the design's stated rule that "test code does not catch `VipError`") or, if sentinels are kept for framework-internal callers, document each one's meaning next to the `except` the way workbench.py:332-333 already does.
Proposed PR: vip-narrow-clients-except (same PR as above; one file, one theme)

### `fixtures.py` collapses a Kubernetes client construction error into "not configured"
Severity: medium
Evidence: src/vip/fixtures.py:217 `        return KubernetesClient(namespace=k8s_cfg.namespace)`
Evidence: src/vip/fixtures.py:219 `    except Exception:` / fixtures.py:220 `        return None`
Why it matters to a newcomer: the fixture already checks `k8s_cfg.is_configured` before this try block (fixtures.py:215-216), so this `except Exception` is not catching "k8s isn't configured" — it is catching a real construction failure (bad kubeconfig, missing credentials, SDK import error) and making it look identical to the unconfigured case. Tests that depend on this fixture will silently skip instead of failing loudly on a broken k8s setup.
Proposed fix: narrow to the exception types `KubernetesClient.__init__` can actually raise (check `clients/kubernetes.py`), or raise a `ConfigError` so the misconfiguration surfaces instead of masquerading as "not configured."
Proposed PR: vip-narrow-plugin-fixtures (files: src/vip/fixtures.py, src/vip/plugin.py)

### `auth.py` polling and cleanup loops swallow silently despite the concrete exception type being imported in the same file
Severity: medium
Evidence: src/vip/auth.py:322 `            except Exception:` (context.close() in a finally block, no comment)
Evidence: src/vip/auth.py:1233 `    except Exception:` (page URL wait, no comment)
Evidence: src/vip/auth.py:1415 `        except Exception:` (page.click selector loop, no comment)
Evidence: src/vip/auth.py:1429 `        except Exception:` (page.wait_for_load_state, no comment)
Evidence: src/vip/auth.py:1440 `        except Exception:` (page.wait_for_timeout, no comment)
Evidence: full list of ~30 similar auth.py sites — `uv run ruff check --select BLE001 --output-format concise --exit-zero src/vip/auth.py`
Why it matters to a newcomer: `auth.py` already imports `Error as PlaywrightError` and `TimeoutError as PlaywrightTimeoutError` (auth.py:23-33) and uses them correctly at lines 146, 463, 1124, 1130, 1325, 1388, 1636, 2077, 2093, 2194. The ~30 sites above catch the same Playwright calls (`page.url`, `page.click`, `page.wait_for_timeout`, `browser.close`, `pw.stop`) with a bare `except Exception`, right next to sites that already know the concrete type. A newcomer cannot tell whether the broad catch is deliberate (tolerating an unknown Playwright edge case) or just unfinished.
Proposed fix: narrow each to `PlaywrightError` (a driver-teardown or navigation call) and add the one-line "why" comment the design's `BLE001` policy requires; `workbench_ui.py`'s equivalent sweep (see "not findings" below) is the model to copy — it already logs every one of its broad excepts.
Proposed PR: vip-narrow-auth-except (same PR as the cache-metadata finding above; one file, one theme)

### Cleanup helpers in `src/vip_tests` are inconsistently commented for the identical pattern
Severity: medium
Evidence: src/vip_tests/workbench/test_ide_launch.py:105-108 `    except Exception:\n        # Best-effort cleanup — don't mask the original failure/skip.\n        pass`
Evidence: src/vip_tests/workbench/test_ide_extensions.py:127-130 `    except Exception:\n        pass` (identical quit-button cleanup, no comment)
Evidence: src/vip_tests/workbench/test_jobs.py:88-91 `    except Exception:\n        pass` (same pattern, no comment)
Evidence: src/vip_tests/workbench/test_runtime_versions.py:170-173 `    except Exception:\n        pass` (same pattern, no comment)
Evidence: src/vip_tests/workbench/test_git_ops.py:174-177 `        except Exception:\n            pass` (subprocess cleanup, no comment)
Why it matters to a newcomer: five files implement the same "best-effort session-quit cleanup, don't mask the test's real outcome" pattern. Only `test_ide_launch.py` (and `test_chronicle.py:139-142`, `test_publish_to_connect.py:565-567`) say so. A newcomer editing `test_ide_extensions.py` has no way to know the missing comment is an oversight rather than a sign that the exception is actually unhandled.
Proposed fix: add the same one-line comment used in `test_ide_launch.py`/`test_chronicle.py` to the other four sites. This is copy-paste, not a design decision, so it can be one small PR across `src/vip_tests/workbench`.
Proposed PR: vip-tests-workbench-comments (files: src/vip_tests/workbench/test_ide_extensions.py, test_jobs.py, test_runtime_versions.py, test_git_ops.py, test_session_capacity.py, test_session_capacity_k8s.py, conftest.py, exec.py)

### `test_publish_to_connect.py` uses a bare `pytest.skip` where sibling files already use `attest`
Severity: low
Evidence: src/vip_tests/workbench/test_publish_to_connect.py:320-321 `    except Exception:\n        pytest.skip(\n            "VS Code did not load within timeout -- ...`
Evidence: selftests/test_skip_triage.py:24-32 `TRIAGED_FILES = [\n    ...\n    "workbench/test_ide_launch.py",\n    "workbench/test_jobs.py",\n    "workbench/test_session_capacity.py",\n    "workbench/test_session_capacity_k8s.py",\n    ...]` — `test_publish_to_connect.py` is not in this list
Why it matters to a newcomer: `AGENTS.md`'s own "Common mistakes" section says a bare `pytest.skip()` should become `attest.not_applicable()`/`attest.unproven()`, and the sibling Workbench test files in the same directory have already been migrated and added to `TRIAGED_FILES`. This file was not, so it is not a rule violation (the guard's docstring says an untriaged bare skip is the accepted default) but it is the visible gap in an otherwise-complete migration.
Proposed fix: classify as `attest.unproven("VS Code did not load...")` (VIP was asked to check the IDE and could not) and add `workbench/test_publish_to_connect.py` to `TRIAGED_FILES`.
Proposed PR: vip-tests-workbench-attest (files: src/vip_tests/workbench/test_publish_to_connect.py, selftests/test_skip_triage.py)

### `install/runner.py` carries a `noqa: BLE001` for a rule that is not enabled yet
Severity: low
Evidence: src/vip/install/runner.py:180 `        except Exception as exc:  # noqa: BLE001`
Evidence: pyproject.toml:217 `select = ["E", "F", "I", "UP"]` (no `BLE001`/`BLE` family selected)
Why it matters to a newcomer: this is the only `noqa: BLE001` in the repository, and it is currently inert since the rule is not selected. It reads as if someone already ran the ratchet and marked this one site deliberate, which could confuse whoever writes the wave-1 `BLE001` PR into thinking triage is partially done.
Proposed fix: no code change needed; when wave 1 enables `BLE001`, verify this site still needs the marker (it does — it's a documented best-effort chained-cleanup warning) and treat it as the one pre-existing example of the policy the rest of the codebase should follow.
Proposed PR: vip-ratchet-ble001 (files: pyproject.toml) — wave 1, not wave 2; listed here only because the site itself lives in scope.

### Failure vocabulary has no mapping to the design's proposed `VipError` subclasses
Severity: medium
Evidence: src/vip/cli.py:164 `        print(f"Error: {exc}", file=sys.stderr)` (generic, wraps a caught exception of unknown type)
Evidence: src/vip/cli.py:228 `            f"\033[1mError: {products} tests selected but no credentials provided.\033[0m\n"` (ANSI-bold, config validation)
Evidence: src/vip/cli.py:800 `            "Error: could not locate the VIP report templates. "` (report/install-adjacent failure)
Evidence: src/vip/auth.py:272 `                print(f">>> Warning: Could not delete API key: {exc}")` (`>>>` prefix, non-fatal)
Evidence: src/vip/cli.py:865 `    except FileNotFoundError:` / cli.py:867 `            "Error: quarto was not found on PATH. Install Quarto "` (a real `ReportError` candidate, currently a bare `FileNotFoundError` catch)
Why it matters to a newcomer: the design's hierarchy proposes `ConfigError`, `AuthError`, `ProductUnreachableError`, `InstallError`, `ReportError`, but today every one of these failure modes is expressed as a plain `print(f"Error: ...")` string with no underlying type, an ANSI-bold variant for CLI-flag validation, or a `>>>`-prefixed non-fatal warning. There is no single grep that finds "every `ConfigError`-shaped failure" the way `BLE001` finds every broad except, so the wave-2 implementer will need to read each `Error:`/`\033[1mError:` site by hand to decide its subclass.
Proposed fix: before wave 2 starts, have each per-module PR include a short table (in the PR body, not the code) mapping the `Error:` strings it touches to the `VipError` subclass they become, so the mapping is reviewable once instead of re-derived by every implementer.
Proposed PR: vip-error-hierarchy (files: src/vip/errors.py) — the mapping itself is documentation, not code, so it doesn't need its own PR.

## Proposed PRs

| slug | theme | files | estimated changed lines | depends on |
|---|---|---|---|---|
| vip-error-hierarchy | Introduce `VipError`/`ConfigError`/`AuthError`/`ProductUnreachableError`/`InstallError`/`ReportError`, reconcile with existing `AuthConfigError`, add selftests | src/vip/errors.py, src/vip/auth.py, src/vip/cli.py, src/vip/plugin.py, selftests/test_errors.py | ~250 | none |
| vip-cli-single-handler | Route the 37 `sys.exit` sites through one handler at the `args.func(args)` dispatch | src/vip/cli.py | ~200 | vip-error-hierarchy |
| vip-narrow-auth-except | Narrow `auth.py`'s ~40 `BLE001` sites to `PlaywrightError`/`OSError`/`ValueError` per the pattern the file already uses elsewhere | src/vip/auth.py | ~350 | vip-error-hierarchy |
| vip-narrow-clients-except | Narrow `clients/connect.py` and `clients/workbench.py`, replace silent sentinels that mask real API failures with a raised `ProductUnreachableError` | src/vip/clients/connect.py, src/vip/clients/workbench.py, src/vip/clients/packagemanager.py | ~150 | vip-error-hierarchy |
| vip-narrow-proxy-except | Narrow `proxy.py`'s five `httpx.URL(...)` parse sites to the concrete `httpx` exception | src/vip/proxy.py | ~60 | vip-error-hierarchy |
| vip-narrow-install-except | Confirm and document `install/playwright.py`, `install/runner.py`'s existing documented sentinels; no behavior change expected | src/vip/install/playwright.py, src/vip/install/runner.py | ~40 | vip-error-hierarchy |
| vip-narrow-plugin-fixtures | Narrow `plugin.py:1123` and `fixtures.py:219`, raise instead of silently downgrading to "not configured" | src/vip/plugin.py, src/vip/fixtures.py | ~60 | vip-error-hierarchy |
| vip-narrow-workbench-ui-except | Add the one-line comment the design requires to `workbench_ui.py`'s remaining undocumented sites (128, 155, 121, 99) | src/vip/workbench_ui.py | ~40 | vip-error-hierarchy |
| vip-tests-workbench-comments | Add the "best-effort cleanup" comment to the four undocumented cleanup sites and narrow the `exec.py`/`conftest.py` Playwright polling loops | src/vip_tests/workbench/test_ide_extensions.py, test_jobs.py, test_runtime_versions.py, test_git_ops.py, test_session_capacity.py, test_session_capacity_k8s.py, conftest.py, exec.py | ~200 | vip-narrow-auth-except (shares the Playwright-narrowing pattern, not files) |
| vip-tests-workbench-attest | Migrate `test_publish_to_connect.py`'s bare skip to `attest.unproven` and add it to `TRIAGED_FILES` | src/vip_tests/workbench/test_publish_to_connect.py, selftests/test_skip_triage.py | ~15 | none |
| vip-narrow-vip-tests-other | Narrow the remaining `BLE001` sites outside Workbench: connect, cross_product, performance, helpers.py, load_engine.py, load_users.py | src/vip_tests/connect/test_content_deploy.py, src/vip_tests/cross_product/test_resources.py, test_ssl.py, src/vip_tests/helpers.py, src/vip_tests/performance/test_concurrency.py, test_resource_usage.py, src/vip/load_engine.py, src/vip/load_users.py | ~150 | none |

## Not findings

- `workbench_ui.py`'s `quit_vip_sessions_via_ui` (lines 190-253) already logs every broad except with `logger.warning` and ends with an always-visible summary — this is the model the rest of the codebase should copy, not a problem.
- `install/playwright.py:55`'s `except Exception: return None` is fully explained by the function's own docstring ("Returns None if playwright cannot be imported... callers should treat that as revision unknown").
- `auth.py:670`'s `refresh_auth_cache_from_storage_state` documents "Never raises: this runs on a cleanup path, where failing loudly would mask the test's own result" and logs via `logger.debug` before returning — a deliberate, well-explained sentinel.
- `cli.py:349` and `cli.py:636` are both commented "best-effort" config-load fallbacks for URL-driven commands that don't depend on the config file; narrowing them is low value since the fallback (ambient environment / defaults) is correct either way.
- `test_jobs.py:145` and `test_jobs.py:159` already use `attest.not_applicable`/`attest.unproven` correctly after their cleanup `except Exception: pass` — the right pattern, not a gap.
- `clients/workbench.py:332`'s `except Exception: break` already carries the exact one-line comment the design's `BLE001` policy asks for ("Connection error, non-JSON body, etc. — give up this run.") — a good example to point implementers at.
- The `Kubernetes` client (`clients/kubernetes.py`) uses the `kubernetes` SDK, not httpx, and was out of scope for the proxy-support work per `AGENTS.md`; its exceptions are a separate, undocumented surface but narrowing it is a `structure`/`typing-lint` lens concern, not core to this lens's findings beyond the `fixtures.py:219` call site already flagged.
- `AuthTimeoutError`'s current design (subclassing `AuthConfigError` rather than a new base) is deliberate and selftest-pinned (`selftests/test_auth.py:1365-1383`); it is not a finding, but it is the reason the `vip-error-hierarchy` PR needs to reconcile rather than replace.

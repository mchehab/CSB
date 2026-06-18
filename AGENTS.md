# AGENTS.md

Project-wide instructions for agents working in this repository.

## Documentation First

Do not duplicate project facts in this file. Use the project documentation as the
source of truth, and update the relevant documentation when behavior, public
configuration, workflows, or supported commands change.

- Project overview and directory map: [README.md](README.md)
- Runner setup, benchmark execution, external benchmark workflow, and bulk
  config generation: [doc/bm-runner.md](doc/bm-runner.md)
- JSON schema, config defaults, monitors, plugins, plots, execution types, CPU
  policy, NICs, and environment variables: [doc/bm-config.md](doc/bm-config.md)
- Builtin benchmark build/test flow, target interface, arguments, operation
  distributions, and output format: [doc/bench.md](doc/bench.md)
- Strace-to-syzkaller-to-CSB generation workflow, generator scripts, Go
  requirements, benchmark selection, and excluded syscalls:
  [doc/bm-generator.md](doc/bm-generator.md)
- Development commands, internal file map, common change patterns, and coding
  style: [doc/development.md](doc/development.md)
- External benchmark notes: [doc/bm-external/](doc/bm-external)
- Application-specific notes: [doc/org-apps/](doc/org-apps)

If project information is needed and is not documented there, add it to the
appropriate document instead of expanding this file.

## Working Tree Discipline

This checkout often contains generated benchmark headers, configs, result
directories, CMake build files, perf outputs, and temporary trace/debug
artifacts. Do not clean, delete, or regenerate them unless the user explicitly
asks.

Before changing files, check both repositories:

```bash
git status --short
git -C deps/syzkaller status --short
```

Treat `deps/syzkaller` as its own git repository/submodule. Check status and
history inside it with `git -C deps/syzkaller ...`; do not mix its changes with
the CSB root repository.

Preserve user changes. If unrelated files are dirty, leave them alone. Avoid
destructive commands such as `git reset --hard`, `git checkout --`, or broad
cleanup unless explicitly requested.

## Change Hygiene

- Keep edits scoped to the area under change.
- Prefer existing helper scripts and local patterns over new tooling.
- Use `rg` for searches.
- Do not add generated build/results artifacts to commits unless the user
  explicitly asks.
- If Docker, perf, sysstat, cgroups, NIC setup, network access, or host
  permissions are unavailable, report the exact requirement instead of changing
  code to hide the failure.
- Try to avoid code duplication by reusing existing code, even if it implies a
  small refactor.

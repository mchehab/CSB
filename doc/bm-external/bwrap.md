# Bubblewrap Benchmark

The bubblewrap benchmark measures the cost of repeatedly launching a short-lived
command through common bwrap isolation profiles.

## Requirements

Install `bwrap` and make it available in `$PATH`:

```bash
bwrap --version
```

The benchmark command defaults to `/usr/bin/true`. The bwrap scenarios bind the
host runtime directories required to execute that command inside the sandbox.

## Scenarios

- `baseline`: runs the command without bwrap, useful for launch overhead comparison.
- `namespaces`: uses bwrap with user, IPC, PID, UTS, and cgroup namespace isolation, while read-only binding `/`.
- `filesystem`: uses a small read-only runtime file system binds, new proc/dev mounts, and tmpfs mounts for writable paths.
- `max`: combines namespace isolation, minimal read-only runtime binds, tmpfs writable paths, clear environment, new session, `--die-with-parent`, and `--disable-userns`.

The network namespace is probed once per execution unit for the `namespaces` and
`max` scenarios. If the installed bwrap cannot create it without extra
privilege, the benchmark omits only `--unshare-net` and reports
`network_namespace=0`; pass `--require-netns` in a config if that should be a
hard failure. The cgroup namespace uses `--unshare-cgroup-try` so the benchmark
can still run on kernels or installations where cgroup namespace creation is not
available.

## Configs

Run one of:

```bash
./scripts/run-single.sh config/bm-external/bwrap/baseline.json
./scripts/run-single.sh config/bm-external/bwrap/namespaces.json
./scripts/run-single.sh config/bm-external/bwrap/filesystem.json
./scripts/run-single.sh config/bm-external/bwrap/max-isolation.json
```

For kernel performance investigation, the configs enable `perf` and `mpstat`
only.

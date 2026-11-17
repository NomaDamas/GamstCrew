# Runtime manager

`RuntimeManager` registers explicit adapters with descriptors, starts them, queues bounded packets, drops oldest work with visible counters, isolates adapter errors and exposes health. Provider environments are not merged into one virtualenv.

Submission failures are recorded in bounded error history and exposed as
`crash_count`. Deployments may opt into a bounded restart policy with
`RuntimeManager(restart_limit=N, restart_backoff_s=...)`; the default is zero
automatic restarts so a failed provider remains visible for operator action.

Applications that own more than one provider can use `await manager.close_all()`
at shutdown, or use `RuntimeManager` as an async context manager.  Both paths
close each registered runtime through the same cancellation and reservation
release path as `close(name)`, and leave the manager registry empty.  This is
the lifecycle boundary used by launchers and test fixtures; it does not claim
that a host-specific provider process passed hardware acceptance.
Subprocess stderr is drained continuously and its bounded tail is included in
process health diagnostics, preventing a noisy provider from blocking its IPC
pipe. These signals are diagnostics, not host acceptance evidence.

Pass a `ResourceAllocator` to the manager to reserve declared CPU cores, RAM,
GPU count and VRAM before a provider starts. A registration that would overcommit
any dimension is rejected atomically; startup failure and normal close release
the exact reservation token. `resource_telemetry()` exposes bounded reservation
and rejection counters. This is accounting evidence supplied by deployment
discovery. Host enforcement is separate and explicit: pass a
`HostLimitController` to `register_process`; the default `accounting` mode is
non-mutating, Linux cgroup-v2 strict mode fails closed when it cannot attach
CPU/RAM limits, and unsupported macOS/Windows/GPU cases are surfaced in the
health report rather than claimed as enforced. Real host acceptance remains a
separate gate.

## Core provider runtime

`CoreProviderRuntime` gives Crew explicit ownership of a real GAMST
`ProcessProvider`. GAMST retains capability validation, provider wire framing,
timeouts and observation validation; Crew owns startup, shutdown and health.
The worker runs in the selected Python environment. The caller must have
`gamst-sdk` importable, while model dependencies remain in the worker
environment. The adapter exposes provider `spec`, `clock_id` and `clock_epoch`
so `SensorStreams` preserves worker identity in temporal observations.

## Unix transport

`gamstcrew.transport.JsonlUnixServer` provides a bounded newline-delimited JSON
Unix-domain socket seam. Requests and responses are size-checked; provider
payloads remain validated by the packet contract. Handler and caller timeouts
(`handler_timeout_s` and `timeout_s`) bound stalled providers. `SharedPacket`
provides an optional bounded local CPU transport with descriptor and packet
checksum verification before dispatch; the JSONL socket path remains an
explicit fallback. GPU/CUDA zero-copy and target-host performance are not
claimed by this contract.

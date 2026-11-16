# Runtime manager

`RuntimeManager` registers explicit adapters with descriptors, starts them, queues bounded packets, drops oldest work with visible counters, isolates adapter errors and exposes health. Provider environments are not merged into one virtualenv.

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
payloads remain validated by the packet contract. Shared memory is a later
Linux/CUDA optimization and is not assumed by the core contract.

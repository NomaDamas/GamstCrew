# Runtime manager

`RuntimeManager` registers explicit adapters with descriptors, starts them, queues bounded packets, drops oldest work with visible counters, isolates adapter errors and exposes health. Provider environments are not merged into one virtualenv.

## Unix transport

`gamstcrew.transport.JsonlUnixServer` provides a bounded newline-delimited JSON
Unix-domain socket seam. Requests and responses are size-checked; provider
payloads remain validated by the packet contract. Shared memory is a later
Linux/CUDA optimization and is not assumed by the core contract.

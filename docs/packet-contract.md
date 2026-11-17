# Packet contract

`EventPacket` preserves event/stream/subject identity, modality/type, source and monotonic clocks, capture/receive/process times, event intervals, sequence/gap, revision/supersedes, provider/model revision, uncertainty, freshness, evidence IDs/source spans and query cutoff. Packets are JSON-safe and bounded at 128 KiB. Evidence after a query cutoff is rejected.

Serialized packets include a versioned SHA-256 checksum envelope. The digest
covers canonical UTF-8 JSON of the packet body (`ensure_ascii=false`, sorted
keys, compact separators); the `checksum` member is excluded from the covered
body. `EventPacket.from_bytes()` and `ProcessRuntime.submit()` verify the
envelope before dispatch and reject mismatches. Rejections are bounded in the
runtime health `integrity_rejected` counter. Pre-checksum packets require the
explicit `allow_legacy=True` compatibility switch and are re-emitted with the
current checksum when serialized.

## Optional shared-memory transport

`SharedPacket` provides a bounded local CPU transport for one canonical
`EventPacket`. The control-plane descriptor carries segment name, exact length
and a SHA-256 digest; the receiver checks the digest and packet checksum before
dispatch. Ownership is explicit: the creator closes and unlinks the segment
after acknowledgement or timeout. `make_packet_transfer(...,
prefer_shared_memory=False)` returns the identical packet bytes as a socket
fallback. GPU/CUDA zero-copy and target-host performance remain separate
acceptance work.

# Packet contract

`EventPacket` preserves event/stream/subject identity, modality/type, source and monotonic clocks, capture/receive/process times, event intervals, sequence/gap, revision/supersedes, provider/model revision, uncertainty, freshness, evidence IDs/source spans and query cutoff. Packets are JSON-safe and bounded at 128 KiB. Evidence after a query cutoff is rejected.

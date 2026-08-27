# Recall search performance

SessionSifu 3.5.4 removes repeated vault-wide work from both Recall capture and
interactive search. The optimization does not create a persistent plaintext
database and does not move compositor APIs onto worker threads.

## Bottlenecks addressed

Before 3.5.0, each debounced query decrypted every metadata record, parsed its
JSON and rebuilt two SQLite FTS5 tables. A missing or misspelled term could then
scan up to 2 MiB of raw OCR and repeat edit-distance comparisons for the same
words. Optional semantic search encoded every document again. The viewers also
decoded several full screenshots for every result before those cards were
visible.

The current design:

- rejects unchanged GNOME captures before OCR and reuses encrypted OCR for
  byte-identical portable images;
- caps CPU-heavy OCR and thumbnail decoding at two workers;
- keeps only the short native pixel grab on the GUI/compositor thread, then
  compresses, recognizes, encrypts and prunes in background work;
- snapshots process metadata once per PID and Linux accessibility applications
  once per capture;
- batches KDE KWin discovery and restore, with the previous compatible tools as
  a fallback;
- makes GNOME window tracking event-driven instead of waking every 500 ms;
- caches at most 128 MiB of decrypted record JSON in an in-process LRU;
- reuses one memory-only FTS5 index until a record name, size or modification
  time changes;
- bounds database candidates and selects the top result set before validating
  file targets or computing highlights;
- caches immutable record inventories and prunes the encrypted vault in one
  storage pass;
- compares typo queries with a dictionary bounded to 100,000 unique OCR terms
  and 500,000 window references;
- caches up to 4,096 offline semantic document vectors by key and content
  digest;
- runs GTK and Qt retrieval on a worker and ignores stale query generations;
- renders 24 results at a time; and
- decrypts one downscaled thumbnail per visible Visual result, none in Compact
  mode, and a full image only when selected.

`clear_search_cache()` closes the FTS connection and drops decrypted records on
security-sensitive lifecycle paths. Process exit always releases the same
memory. Exclusions are still applied to every result: an index hit never makes
an excluded window or shared preview visible.

## Reproducible synthetic check

The development benchmark uses 500 encrypted metadata records containing 4,000
synthetic windows. After the 3.5.4 changes, repeated exact search measured about
9.7 ms mean (9.4 ms median, 11.9 ms p95) in the portable store and about 7.9 ms
mean (7.4 ms median, 9.2 ms p95) in the GNOME store. Earlier 3.5.0 engineering
checks on the same corpus class measured about 19 ms for portable warm exact
search, while the pre-index design repeatedly took 78–411 ms depending on the
query. Fixture generation and hardware vary, so only orders of magnitude are
meaningful across runs.

These figures are engineering measurements, not hardware guarantees. OCR model
execution, screenshot capture and first-vault indexing remain proportional to
the selected quality, image count and device. Automated regressions verify
cross-worker index reuse, cache clearing, semantic vector reuse, exclusion
redaction and current search behavior rather than enforcing fragile wall-clock
thresholds in CI.

# Recall search performance

SessionSifu 3.5.0 removes repeated vault-wide work from the interactive Recall
search path. The optimization does not create a persistent plaintext database.

## Bottlenecks addressed

Before 3.5.0, each debounced query decrypted every metadata record, parsed its
JSON and rebuilt two SQLite FTS5 tables. A missing or misspelled term could then
scan up to 2 MiB of raw OCR and repeat edit-distance comparisons for the same
words. Optional semantic search encoded every document again. The viewers also
decoded several full screenshots for every result before those cards were
visible.

The current design:

- caches at most 128 MiB of decrypted record JSON in an in-process LRU;
- reuses one memory-only FTS5 index until a record name, size or modification
  time changes;
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
synthetic windows. On the development machine, the initial empty query took
about 187 ms to decrypt and index the corpus. A repeated empty query took about
9 ms; a warm exact query about 19 ms; and a warm missing-term query about 7 ms.
The former implementation measured roughly 78 ms for every empty query, 106 ms
for a common exact query and 259–411 ms for missing/fuzzy queries on the same
fixture.

These figures are engineering measurements, not hardware guarantees. OCR model
execution, screenshot capture and first-vault indexing remain proportional to
the selected quality, image count and device. Automated regressions verify
cross-worker index reuse, cache clearing, semantic vector reuse, exclusion
redaction and current search behavior rather than enforcing fragile wall-clock
thresholds in CI.

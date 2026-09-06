# Stability and performance audit — 3.5.24

Baseline: 3.5.23 (7df2806). Tests use temporary encrypted records, mock platform
adapters and offscreen Qt—not a production desktop or its real Recall vault.

## Findings and implementation

| Priority | Finding | Response in 3.5.24 |
| --- | --- | --- |
| P0 | Credential outage could silently change the encryption key | Cross-process initialization lock, private nonsecret key fingerprint/backend descriptor, per-vault accounts for new keys; existing ciphertext fails closed if its key is unavailable |
| P1 | Damaged record could leave search busy forever | Preserve damaged ciphertext, skip isolated record authentication failures, always complete failed workers |
| P1 | KDE returned after any successful batch item | Return applied IDs; match remaining windows to unique current IDs |
| P1 | Portable restore guessed readiness and success | Serial app groups, bounded readiness, document aggregation, instance reuse, per-window results, cancellation and unfinished-only retry |
| P1 | Restore/OCR/detail reads blocked Qt | Bounded workers, GUI-thread completion, stale selection checks and cancellable selected-record OCR |
| P1 | Capture buffered dozens of raw screenshots | One image at a time with compression backpressure and explicit byte budgets |
| P2 | Warm search repeatedly decrypted large histories | Compact metadata cache, changed-record FTS updates, full OCR coordinates loaded for candidate results |
| P2 | GNOME staging blocked Shell on disk I/O | Cancellable asynchronous preview I/O and asynchronous session reads, private creation and lifecycle checks |
| P1 | Missing native callback blocked the queue forever | Two-minute active-operation watchdog cancels waiting requests but preserves native ownership until callback completion |

## Recovery and limits

- Unlock an unavailable OS credential store and retry. Do not delete
  `.vault-key`, `.key-identity.json` or encrypted records to repair the vault.
  Existing fallback formats remain readable. Older mixed-key histories are
  preserved but not automatically recovered or re-encrypted; retain every key
  and ciphertext before manual recovery.
- Authentication is never bypassed. Damaged files remain intact and are logged;
  healthy records remain searchable.
- Portable restore reports completed/deferred/failed/cancelled window outcomes.
  Counts reflect completed layout actions, not saved-window totals. Cancel
  stops remaining actions, not an app already launched or an active OS call.
  Default readiness is 15 seconds per app, capped internally at 30 seconds;
  backend calls have their own timeouts. GNOME pacing remains unchanged.
- OCR cancellation and a two-minute budget are checked between images.
  An active OCR job can take up to its existing 20-second timeout to return.
  Finished image results are saved; remaining images are deferred.
- Capture retains selected quality. The decoded-image budget and compressed
  capture-set budget are each 128 MiB. Missing/deferred images are counted.
  These are not total-process RSS limits: temporary screen copies, one encoder,
  Qt, encrypted output and search structures use additional memory.
- The metadata cache is bounded to 32 MiB compressed, separate from the
  128 MiB serialized-detail LRU. SQLite/Python/fuzzy-index overhead is additional.
  Everything stays memory-only and is dropped by `clear_search_cache()`.
  Very large metadata corpora can still evict entries; cold indexing and
  optional semantic ranking are not constant-time.
- A compositor timeout does not overlap or reset native rendering. Pending
  requests are cancelled and new work fails clearly until the native callback
  returns. If it never returns, preserve diagnostics and saved sessions; a normal
  logout/login may be necessary after saving your work.

## Verification

Run from the repository root:

```sh
python3 tests/test_audit_regressions.py
python3 tests/test_portable.py
python3 tests/test_recall_engine.py
node --experimental-vm-modules tests/compositor-operations-smoke.mjs
# Install portable[gui] in an isolated environment for offscreen Qt coverage:
python3 tests/test_qt_background.py
./packaging/build-deb.sh
```

Fault injection covers key outage/recovery/missing/mismatch, concurrent creation,
legacy formats, corrupt records, warm cache eviction, incremental additions and
deletions, KDE mixed IDs, absent/slow windows, document aggregation and cancellation.
Qt checks cover GUI heartbeat during slow work, search error recovery, stale
image suppression and sequential 16-window compression. The watchdog test
withholds a callback and confirms no overlapping operation starts on timeout.

Real Windows/macOS/KWin permissions, delayed applications and multi-monitor RSS
still need native validation. These fixes do not prove the cause of historical
hardware-specific Wayland black-screen crashes. Do not stress-test restoration
on an unsaved production desktop.

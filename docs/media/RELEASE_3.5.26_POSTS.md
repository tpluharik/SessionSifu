# SessionSifu 3.5.26 release posts

Canonical release: <https://github.com/tpluharik/SessionSifu/releases/tag/v3.5.26>

These posts describe tested 3.5.26 behavior. The screenshots and video use only
synthetic content; do not attach real Recall history or desktop captures.

## GitHub release notes

SessionSifu 3.5.26 reduces background battery and electricity use across GNOME,
Windows, macOS, KDE Plasma and other supported Linux desktops.

- Automatic snapshots now default to 10 minutes, use at least 15 minutes on
  battery and skip unchanged desktop state.
- Privacy Recall uses at least 15 minutes on battery and 30 minutes at 20%
  charge or below. At 10% or below, new Recall moments pause.
- Screenshot capture stops at 20% or below and in power-saver mode. OCR is
  deferred on battery and resumes one newest deferred record in a bounded job
  after AC power returns.
- GNOME caches only focus-affected windows, rate-limits cache passes and reuses
  fresh encrypted preview/OCR data before requesting more compositor work.
- Portable builds use coarse timers and avoid capsule polling or UI rebuilding
  while the relevant view is hidden or unchanged.

Manual saves remain available, stored preferences are preserved, and the power
policy does not change retention or upload data. Session and Recall data remain
local; visual Recall is still disabled by default.

Downloads and checksums: <https://github.com/tpluharik/SessionSifu/releases/tag/v3.5.26>

## Reddit update

**Update — SessionSifu 3.5.26:** the background capture path is now adaptive to
battery and power-saver state. Automatic snapshots skip unchanged state and run
less often on battery; Recall reduces its cadence, withholds screenshots on low
charge, defers OCR until AC power returns, and limits GNOME preview-cache work
to focus-affected windows. Portable builds also use coarse timers and stop
hidden capsule-view polling.

Manual saves still work, user retention settings are unchanged, and Recall
remains local, encrypted and off by default.

Release and downloads: <https://github.com/tpluharik/SessionSifu/releases/tag/v3.5.26>

## Short social post

SessionSifu 3.5.26 is out. Automatic session snapshots and optional encrypted
Recall now adapt to battery and power-saver state, skip unchanged work, reuse
fresh previews/OCR, and resume deferred OCR safely after AC returns. Manual
saves and retention settings stay unchanged.

<https://github.com/tpluharik/SessionSifu/releases/tag/v3.5.26>

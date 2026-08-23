# Bundled OCR language data

SessionSifu includes the Czech (`ces`) and English (`eng`) fast Tesseract
models so mixed Czech/English desktop text works immediately after a normal
installation, a user-local in-app update, or a portable installation. OCR is
performed locally and does not download language data at runtime.

See the [Recall workflow](../docs/RECALL_GUIDE.md) for enabling OCR and the
[privacy guide](../docs/PRIVACY.md) for storage and processing boundaries.

The models come from the official
[`tesseract-ocr/tessdata_fast`](https://github.com/tesseract-ocr/tessdata_fast)
repository at commit `87416418657359cb625c412a48b6e1d6d41c29bd`.
The `configs/tsv` file comes from the official `tesseract-ocr/tessconfigs`
repository at commit `3decf1c8252ba6dbeef0bf908f4b0aab7f18d113`.
The data and configuration are distributed under Apache-2.0; see `LICENSE`.

Verified SHA-256 digests:

- `ces.traineddata`: `934bcaf97ef3348413263331131c9fa7f55f30db333c711929c124fb635f7e1b`
- `eng.traineddata`: `7d4322bd2a7749724879683fc3912cb542f19906c83bcc1a52132556427170b2`
- `configs/tsv`: `59d079bb75d8b3d7c839a3564580cb559e362c93a9d70f234e421c0c3e767e04`
- `LICENSE`: `cfc7749b96f63bd31c3c42b5c471bf756814053e847c10f3eb003417bc523d30`

The fast models require Tesseract 4 or newer and use its LSTM engine. The
SessionSifu Debian package therefore depends on the Tesseract executable but
does not depend on a distribution-specific Czech language package.

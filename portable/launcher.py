"""PyInstaller entry point for SessionSifu Portable."""

import multiprocessing

if __name__ == "__main__":
    multiprocessing.freeze_support()

from sessionsifu_portable.__main__ import main


if __name__ == "__main__":
    raise SystemExit(main())

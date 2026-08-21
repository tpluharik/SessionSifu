"""SessionSifu Portable command line and GUI entry point."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from . import VERSION
from .controller import SessionController


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description="Cross-platform SessionSifu session manager")
    result.add_argument("--version", action="version", version=VERSION)
    result.add_argument("--save", metavar="NAME", help="save a named session")
    result.add_argument("--restore", metavar="NAME", help="restore a named session")
    result.add_argument("--delete", metavar="NAME", help="delete a named session")
    result.add_argument("--list", action="store_true", help="list named sessions")
    result.add_argument("--save-history", action="store_true", help="create a rolling snapshot")
    result.add_argument("--history", action="store_true", help="list rolling snapshots")
    result.add_argument("--restore-file", type=Path, help="restore a SessionSifu JSON file")
    result.add_argument("--diagnostics", action="store_true", help="print adapter capabilities")
    result.add_argument("--no-gui", action="store_true", help="do not launch the desktop interface")
    return result


def main() -> int:
    args = parser().parse_args()
    controller = SessionController()
    handled = False
    if args.save:
        print(controller.save_named(args.save))
        handled = True
    if args.restore:
        print(json.dumps(controller.restore_named(args.restore)))
        handled = True
    if args.delete:
        controller.store.delete_named(args.delete)
        handled = True
    if args.list:
        print("\n".join(path.stem for path in controller.named_sessions()))
        handled = True
    if args.save_history:
        print(controller.save_history())
        handled = True
    if args.history:
        print("\n".join(str(path) for path in controller.history()))
        handled = True
    if args.restore_file:
        print(json.dumps(controller.restore_path(args.restore_file)))
        handled = True
    if args.diagnostics:
        print(json.dumps(controller.diagnostics(), indent=2))
        handled = True
    if handled or args.no_gui:
        return 0
    try:
        from .ui import run_gui
    except ImportError as error:
        raise SystemExit("The GUI requires PySide6. Install sessionsifu-portable[gui].") from error
    return run_gui(controller)


if __name__ == "__main__":
    raise SystemExit(main())

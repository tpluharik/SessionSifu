"""SessionSifu Portable command line and GUI entry point."""

from __future__ import annotations

import argparse
import getpass
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
    result.add_argument("--capsule-create", metavar="NAME", help="create an encrypted workspace capsule")
    result.add_argument(
        "--capsule-backend",
        choices=["profile", "flatpak", "windows-sandbox"],
        default="profile",
    )
    result.add_argument("--capsule-app", action="append", default=[], help="application or Flatpak ID")
    result.add_argument("--capsule-folder", action="append", default=[], help="read-only Windows Sandbox folder")
    result.add_argument("--capsule-offline", action="store_true", help="request an enforceable offline backend")
    result.add_argument("--capsule-list", action="store_true", help="list workspace capsules")
    result.add_argument("--capsule-plan", metavar="NAME", help="print the effective capsule permission plan")
    result.add_argument("--capsule-launch", metavar="NAME", help="launch a capsule after fail-closed preflight")
    result.add_argument("--capsule-delete", metavar="NAME", help="delete a capsule manifest")
    result.add_argument("--capsule-delete-data", metavar="NAME", help="delete a capsule's separate profile data")
    result.add_argument("--capsule-export-wsb", metavar="NAME", help="export a Windows Sandbox capsule")
    result.add_argument("--capsule-output", type=Path, help="destination for --capsule-export-wsb")
    result.add_argument(
        "--recall-search", action="store_true", help="open the dedicated Privacy Recall search popup"
    )
    result.add_argument("--mcp-stdio", action="store_true", help="serve the opt-in read-only MCP adapter")
    result.add_argument("--export-archive", type=Path, help="export sessions and Recall to an encrypted archive")
    result.add_argument("--import-archive", type=Path, help="import an encrypted SessionSifu archive")
    result.add_argument("--recall-reindex", metavar="RECORD", help="re-run OCR for one Recall record")
    result.add_argument("--recall-ask", metavar="QUESTION", help="ask local history and print cited evidence")
    result.add_argument(
        "--local-api-stdio",
        action="store_true",
        help="serve the read-only local JSON API on stdin/stdout",
    )
    result.add_argument("--no-gui", action="store_true", help="do not launch the desktop interface")
    return result


def main() -> int:
    args = parser().parse_args()
    controller = SessionController()
    handled = False
    if args.local_api_stdio:
        from .api import serve_stdio

        return serve_stdio(controller)
    if args.mcp_stdio:
        from .mcp import serve_mcp

        return serve_mcp(controller)
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
    if args.capsule_create:
        print(controller.create_capsule(
            args.capsule_create,
            args.capsule_backend,
            args.capsule_app,
            offline=args.capsule_offline,
            mapped_folders=args.capsule_folder,
        ))
        handled = True
    if args.capsule_list:
        print(json.dumps(controller.list_capsules(), indent=2))
        handled = True
    if args.capsule_plan:
        print(json.dumps(controller.preflight_capsule(args.capsule_plan), indent=2))
        handled = True
    if args.capsule_launch:
        print(json.dumps(controller.launch_capsule(args.capsule_launch), indent=2))
        handled = True
    if args.capsule_delete:
        controller.delete_capsule(args.capsule_delete)
        handled = True
    if args.capsule_delete_data:
        print(json.dumps({"deleted": controller.delete_capsule_data(args.capsule_delete_data)}))
        handled = True
    if args.capsule_export_wsb:
        if not args.capsule_output:
            raise SystemExit("--capsule-output is required with --capsule-export-wsb")
        print(controller.export_windows_capsule(args.capsule_export_wsb, args.capsule_output))
        handled = True
    if args.recall_reindex:
        print(json.dumps(controller.reindex_recall(args.recall_reindex), indent=2))
        handled = True
    if args.recall_ask:
        print(json.dumps(controller.ask_recall(args.recall_ask), indent=2))
        handled = True
    if args.export_archive:
        passphrase = getpass.getpass("Archive passphrase: ")
        print(json.dumps(controller.export_archive(args.export_archive, passphrase)))
        handled = True
    if args.import_archive:
        passphrase = getpass.getpass("Archive passphrase: ")
        print(json.dumps(controller.import_archive(args.import_archive, passphrase)))
        handled = True
    if handled or args.no_gui:
        return 0
    try:
        from .ui import run_gui
    except ImportError as error:
        raise SystemExit("The GUI requires PySide6. Install sessionsifu-portable[gui].") from error
    return run_gui(controller, open_recall_search=args.recall_search)


if __name__ == "__main__":
    raise SystemExit(main())

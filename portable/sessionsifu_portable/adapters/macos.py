"""macOS adapter using System Events and the public `open` command."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from .base import AdapterCapabilities, PlatformAdapter, process_details, process_files
from ..model import SessionSnapshot, WindowSnapshot

CAPTURE_SCRIPT = r"""
function run() {
  const systemEvents = Application('System Events');
  const result = [];
  const processes = systemEvents.applicationProcesses.whose({backgroundOnly: false})();
  processes.forEach(function (process) {
    let name = '', bundle = '', pid = 0, windows = [];
    try { name = process.name(); } catch (_) {}
    try { bundle = process.bundleIdentifier(); } catch (_) {}
    try { pid = process.unixId(); } catch (_) {}
    try { windows = process.windows(); } catch (_) { windows = []; }
    windows.forEach(function (window, index) {
      try {
        const position = window.position();
        const size = window.size();
        let title = '';
        try { title = window.name(); } catch (_) {}
        result.push({
          window_id: String(pid) + ':' + String(index),
          app_id: bundle || name,
          app_name: name,
          title: title,
          pid: pid,
          geometry: [position[0], position[1], size[0], size[1]]
        });
      } catch (_) {}
    });
  });
  return JSON.stringify(result);
}
"""

RESTORE_SCRIPT = r"""
function run(argv) {
  const payload = JSON.parse(argv[0]);
  const systemEvents = Application('System Events');
  const processes = systemEvents.applicationProcesses();
  payload.windows.forEach(function (saved) {
    for (let p = 0; p < processes.length; p++) {
      let name = '', bundle = '';
      try { name = processes[p].name(); } catch (_) {}
      try { bundle = processes[p].bundleIdentifier(); } catch (_) {}
      if ((bundle || name) !== saved.app_id) continue;
      let windows = [];
      try { windows = processes[p].windows(); } catch (_) {}
      let selected = null;
      for (let w = 0; w < windows.length; w++) {
        let title = '';
        try { title = windows[w].name(); } catch (_) {}
        if (title === saved.title) { selected = windows[w]; break; }
      }
      if (!selected && windows.length) selected = windows[0];
      if (selected) {
        try { selected.position = [saved.geometry[0], saved.geometry[1]]; } catch (_) {}
        try { selected.size = [saved.geometry[2], saved.geometry[3]]; } catch (_) {}
      }
      break;
    }
  });
  return 'ok';
}
"""


class MacOSAdapter(PlatformAdapter):
    key = "macos"
    desktop = "macOS"
    capabilities = AdapterCapabilities(
        applications=True,
        documents=True,
        geometry=True,
        monitors=False,
        workspaces=False,
    )

    @staticmethod
    def _jxa(script: str, *arguments: str) -> str:
        completed = subprocess.run(
            ["osascript", "-l", "JavaScript", "-e", script, *arguments],
            check=False,
            capture_output=True,
            text=True,
            timeout=20,
        )
        if completed.returncode:
            raise RuntimeError(
                "macOS window access failed. Allow SessionSifu under Privacy & Security → Accessibility. "
                + completed.stderr.strip()
            )
        return completed.stdout.strip()

    def capture_windows(self) -> list[WindowSnapshot]:
        raw = json.loads(self._jxa(CAPTURE_SCRIPT) or "[]")
        windows: list[WindowSnapshot] = []
        for item in raw:
            pid = int(item.get("pid") or 0)
            if str(item.get("app_name") or "").casefold() in {"sessionsifu", "finder", "dock"}:
                continue
            executable, command = process_details(pid)
            windows.append(
                WindowSnapshot.from_dict(
                    {
                        **item,
                        "executable": executable,
                        "command": command,
                        "open_files": process_files(pid),
                    }
                )
            )
        return windows

    def launch_window(self, window: WindowSnapshot) -> None:
        command = ["open"]
        if window.app_id and "." in window.app_id:
            command.extend(["-b", window.app_id])
        elif window.app_name:
            command.extend(["-a", window.app_name])
        else:
            return
        files = [path for path in window.open_files if Path(path).is_file()]
        subprocess.Popen([*command, *files], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def apply_layout(self, session: SessionSnapshot) -> None:
        payload = json.dumps({"windows": [window.to_dict() for window in session.windows]})
        self._jxa(RESTORE_SCRIPT, payload)

"""Windows desktop adapter using public Win32 window-management APIs."""

from __future__ import annotations

import ctypes
from ctypes import wintypes
import os
import subprocess
from collections import defaultdict
from pathlib import Path

from .base import AdapterCapabilities, PlatformAdapter, cached_process_snapshot
from ..model import MonitorSnapshot, SessionSnapshot, WindowSnapshot


class MONITORINFOEXW(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD), ("rcMonitor", wintypes.RECT),
        ("rcWork", wintypes.RECT), ("dwFlags", wintypes.DWORD),
        ("szDevice", wintypes.WCHAR * 32),
    ]


class WindowsAdapter(PlatformAdapter):
    key = "windows"
    desktop = "Windows Desktop"
    capabilities = AdapterCapabilities(
        applications=True,
        documents=True,
        geometry=True,
        monitors=True,
        workspaces=False,
    )

    def __init__(self) -> None:
        self.user32 = ctypes.WinDLL("user32", use_last_error=True)
        self.kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        self._callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
        self.user32.EnumWindows.argtypes = [self._callback_type, wintypes.LPARAM]
        self.user32.EnumWindows.restype = wintypes.BOOL
        self.user32.IsWindowVisible.argtypes = [wintypes.HWND]
        self.user32.IsWindowVisible.restype = wintypes.BOOL
        self.user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
        self.user32.GetWindowTextLengthW.restype = ctypes.c_int
        self.user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
        self.user32.GetWindowTextW.restype = ctypes.c_int
        self.user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
        self.user32.GetWindowRect.restype = wintypes.BOOL
        self.user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
        self.user32.GetWindowThreadProcessId.restype = wintypes.DWORD
        self.user32.IsIconic.argtypes = [wintypes.HWND]
        self.user32.IsZoomed.argtypes = [wintypes.HWND]
        self.user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
        self.user32.MoveWindow.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, wintypes.BOOL]

    def capture_monitors(self, windows=None) -> list[MonitorSnapshot]:
        monitors: list[MonitorSnapshot] = []
        callback_type = ctypes.WINFUNCTYPE(
            wintypes.BOOL, wintypes.HANDLE, wintypes.HDC,
            ctypes.POINTER(wintypes.RECT), wintypes.LPARAM,
        )

        def visit(handle, _device, _rect, _data):
            info = MONITORINFOEXW()
            info.cbSize = ctypes.sizeof(info)
            if self.user32.GetMonitorInfoW(handle, ctypes.byref(info)):
                rect = info.rcWork
                monitors.append(MonitorSnapshot(
                    monitor_id=str(info.szDevice), name=str(info.szDevice),
                    geometry=[rect.left, rect.top, rect.right - rect.left, rect.bottom - rect.top],
                    primary=bool(info.dwFlags & 1),
                ))
            return True

        callback = callback_type(visit)
        if not self.user32.EnumDisplayMonitors(0, 0, callback, 0):
            return super().capture_monitors(windows)
        return monitors or super().capture_monitors(windows)

    def _window_text(self, hwnd: int) -> str:
        length = self.user32.GetWindowTextLengthW(hwnd)
        if length <= 0:
            return ""
        buffer = ctypes.create_unicode_buffer(min(length + 1, 4097))
        self.user32.GetWindowTextW(hwnd, buffer, len(buffer))
        return buffer.value

    def _enumerate(self, include_files: bool = True) -> list[WindowSnapshot]:
        windows: list[WindowSnapshot] = []
        process_cache: dict[int, tuple[str, list[str], list[str]]] = {}

        def visit(hwnd: int, _data: int) -> bool:
            if not self.user32.IsWindowVisible(hwnd):
                return True
            title = self._window_text(hwnd)
            if not title:
                return True
            rect = wintypes.RECT()
            if not self.user32.GetWindowRect(hwnd, ctypes.byref(rect)):
                return True
            width, height = rect.right - rect.left, rect.bottom - rect.top
            if width < 32 or height < 32:
                return True
            pid = ctypes.c_ulong()
            self.user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            executable, command, open_files = cached_process_snapshot(
                process_cache, pid.value, include_files=include_files
            )
            if not executable:
                return True
            app_name = Path(executable).stem
            if app_name.casefold() in {
                "sessionsifu",
                "explorer",
                "searchhost",
                "shellexperiencehost",
                "startmenuexperiencehost",
            }:
                return True
            windows.append(
                WindowSnapshot(
                    window_id=str(int(hwnd)),
                    app_id=os.path.normcase(executable),
                    app_name=app_name,
                    title=title,
                    executable=executable,
                    command=command,
                    pid=pid.value,
                    geometry=[rect.left, rect.top, width, height],
                    minimized=bool(self.user32.IsIconic(hwnd)),
                    maximized=bool(self.user32.IsZoomed(hwnd)),
                    open_files=open_files,
                )
            )
            return True

        callback = self._callback_type(visit)
        if not self.user32.EnumWindows(callback, 0):
            error = ctypes.get_last_error()
            if error:
                raise OSError(error, "EnumWindows failed")
        return windows

    def capture_windows(self, include_files: bool = True) -> list[WindowSnapshot]:
        return self._enumerate(include_files=include_files)

    def launch_window(self, window: WindowSnapshot) -> bool:
        executable = Path(window.executable)
        if not executable.is_file():
            return False
        arguments = [path for path in window.open_files if Path(path).is_file()]
        subprocess.Popen(
            [str(executable), *arguments],
            cwd=str(Path.home()),
            creationflags=getattr(subprocess, "DETACHED_PROCESS", 0),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return True

    def apply_layout(self, session: SessionSnapshot) -> None:
        session = self.reconciled_session(session)
        available: dict[str, list[WindowSnapshot]] = defaultdict(list)
        for current in self._enumerate(include_files=False):
            available[current.app_id].append(current)
        used: set[str] = set()
        for saved in session.windows:
            choices = [item for item in available.get(saved.app_id, []) if item.window_id not in used]
            if not choices:
                continue
            current = next((item for item in choices if item.title == saved.title), choices[0])
            used.add(current.window_id)
            hwnd = wintypes.HWND(int(current.window_id))
            x, y, width, height = saved.geometry
            self.user32.ShowWindow(hwnd, 9)  # SW_RESTORE before geometry changes
            self.user32.MoveWindow(hwnd, x, y, width, height, True)
            if saved.maximized:
                self.user32.ShowWindow(hwnd, 3)
            elif saved.minimized:
                self.user32.ShowWindow(hwnd, 6)

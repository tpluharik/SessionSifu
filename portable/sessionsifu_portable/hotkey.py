"""Native, privacy-preserving Recall search shortcut integration.

The shortcut opens SessionSifu's own search window; it never reads key text.
Windows uses RegisterHotKey, macOS uses an NSEvent modifier/key match, and
Linux asks the compositor through the XDG GlobalShortcuts portal.
"""

from __future__ import annotations

import asyncio
import ctypes
import sys
import threading
import uuid

from PySide6.QtCore import QObject, Signal


SHORTCUT_LABEL = "Ctrl+Alt+Space"
PORTAL_TRIGGER = "<Control><Alt>space"


class RecallHotkey(QObject):
    """Register one OS-level shortcut without capturing arbitrary keystrokes."""

    triggered = Signal()
    status_changed = Signal(str)

    def __init__(self) -> None:
        super().__init__()
        self._active = False
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._windows_thread_id = 0
        self._mac_monitors: list[object] = []
        self._portal_loop: asyncio.AbstractEventLoop | None = None
        self._portal_bus = None
        self._portal_session = ""

    def start(self) -> None:
        if self._active:
            return
        self._active = True
        self._stop = threading.Event()
        if sys.platform == "win32":
            self._thread = threading.Thread(target=self._windows_loop, daemon=True)
            self._thread.start()
        elif sys.platform == "darwin":
            self._start_macos()
        elif sys.platform.startswith("linux"):
            self._thread = threading.Thread(target=self._linux_loop, daemon=True)
            self._thread.start()
        else:
            self.status_changed.emit(
                f"Global {SHORTCUT_LABEL} is unavailable on this platform; use the tray action."
            )

    def stop(self) -> None:
        if not self._active:
            return
        self._active = False
        self._stop.set()
        if sys.platform == "win32" and self._windows_thread_id:
            ctypes.windll.user32.PostThreadMessageW(self._windows_thread_id, 0x0012, 0, 0)
        if sys.platform == "darwin":
            self._stop_macos()
        if self._portal_loop is not None:
            self._portal_loop.call_soon_threadsafe(lambda: None)
        thread = self._thread
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=1.0)
        self._thread = None

    def _windows_loop(self) -> None:
        from ctypes import wintypes

        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32
        hotkey_id = 0x5349
        self._windows_thread_id = kernel32.GetCurrentThreadId()
        # MOD_CONTROL | MOD_ALT | MOD_NOREPEAT, VK_SPACE
        if not user32.RegisterHotKey(None, hotkey_id, 0x0002 | 0x0001 | 0x4000, 0x20):
            self.status_changed.emit(
                f"Could not reserve {SHORTCUT_LABEL}; another application may already use it."
            )
            self._active = False
            self._windows_thread_id = 0
            return
        self.status_changed.emit(f"Recall search shortcut active: {SHORTCUT_LABEL}")
        message = wintypes.MSG()
        try:
            while user32.GetMessageW(ctypes.byref(message), None, 0, 0) > 0:
                if message.message == 0x0312 and message.wParam == hotkey_id:
                    self.triggered.emit()
        finally:
            user32.UnregisterHotKey(None, hotkey_id)
            self._windows_thread_id = 0

    def _start_macos(self) -> None:
        try:
            from AppKit import (
                NSEvent,
                NSEventMaskKeyDown,
                NSEventModifierFlagDeviceIndependentFlagsMask,
                NSEventModifierFlagControl,
                NSEventModifierFlagOption,
            )
        except ImportError:
            self.status_changed.emit(
                "The macOS shortcut helper is unavailable; use the tray action."
            )
            self._active = False
            return

        required = NSEventModifierFlagControl | NSEventModifierFlagOption

        def matches(event) -> bool:
            return (
                event.keyCode() == 49
                and event.modifierFlags()
                & NSEventModifierFlagDeviceIndependentFlagsMask
                == required
                and not event.isARepeat()
            )

        def global_handler(event) -> None:
            if matches(event):
                self.triggered.emit()

        def local_handler(event):
            if matches(event):
                self.triggered.emit()
                return None
            return event

        try:
            self._mac_monitors = [
                NSEvent.addGlobalMonitorForEventsMatchingMask_handler_(
                    NSEventMaskKeyDown, global_handler
                ),
                NSEvent.addLocalMonitorForEventsMatchingMask_handler_(
                    NSEventMaskKeyDown, local_handler
                ),
            ]
            self.status_changed.emit(
                f"Recall search shortcut active: {SHORTCUT_LABEL} (Input Monitoring may be requested)."
            )
        except Exception as error:  # pragma: no cover - requires macOS UI services
            self._mac_monitors = []
            self._active = False
            self.status_changed.emit(f"Could not register {SHORTCUT_LABEL}: {error}")

    def _stop_macos(self) -> None:
        try:
            from AppKit import NSEvent

            for monitor in self._mac_monitors:
                if monitor is not None:
                    NSEvent.removeMonitor_(monitor)
        except ImportError:
            pass
        self._mac_monitors = []

    def _linux_loop(self) -> None:
        stop_event = self._stop
        loop = asyncio.new_event_loop()
        self._portal_loop = loop
        try:
            loop.run_until_complete(self._linux_portal(stop_event))
        except Exception as error:  # pragma: no cover - depends on the desktop portal
            if self._stop is stop_event:
                self._active = False
            self.status_changed.emit(
                f"Global shortcut unavailable ({error}); use {SHORTCUT_LABEL} while SessionSifu is focused or the tray action."
            )
        finally:
            self._portal_loop = None
            loop.close()

    async def _linux_portal(self, stop_event: threading.Event) -> None:
        from dbus_next import BusType, MessageType, Variant
        from dbus_next.aio import MessageBus

        destination = "org.freedesktop.portal.Desktop"
        portal_path = "/org/freedesktop/portal/desktop"
        bus = await MessageBus(bus_type=BusType.SESSION).connect()
        self._portal_bus = bus
        sender = bus.unique_name.lstrip(":").replace(".", "_")
        responses: dict[str, asyncio.Future] = {}

        def message_handler(message) -> None:
            if (
                message.message_type == MessageType.SIGNAL
                and message.interface == "org.freedesktop.portal.Request"
                and message.member == "Response"
            ):
                future = responses.get(message.path)
                if future is not None and not future.done():
                    future.set_result(message.body)
            elif (
                message.message_type == MessageType.SIGNAL
                and message.interface == "org.freedesktop.portal.GlobalShortcuts"
                and message.member == "Activated"
                and len(message.body) >= 2
                and message.body[1] == "recall-search"
            ):
                self.triggered.emit()

        bus.add_message_handler(message_handler)
        introspection = await bus.introspect(destination, portal_path)
        portal = bus.get_proxy_object(destination, portal_path, introspection)
        shortcuts = portal.get_interface("org.freedesktop.portal.GlobalShortcuts")

        async def request(call, token: str):
            expected = f"/org/freedesktop/portal/desktop/request/{sender}/{token}"
            future = asyncio.get_running_loop().create_future()
            responses[expected] = future
            returned = await call
            if returned != expected:
                responses[returned] = responses.pop(expected)
                expected = returned
            try:
                response, results = await asyncio.wait_for(future, timeout=60)
            finally:
                responses.pop(expected, None)
            if response != 0:
                raise RuntimeError(f"desktop portal denied request ({response})")
            return results

        session_token = f"sessionsifu_{uuid.uuid4().hex}"
        create_token = f"create_{uuid.uuid4().hex}"
        created = await request(
            shortcuts.call_create_session(
                {
                    "handle_token": Variant("s", create_token),
                    "session_handle_token": Variant("s", session_token),
                }
            ),
            create_token,
        )
        self._portal_session = created["session_handle"].value
        bind_token = f"bind_{uuid.uuid4().hex}"
        await request(
            shortcuts.call_bind_shortcuts(
                self._portal_session,
                [[
                    "recall-search",
                    {
                        "description": Variant("s", "Open SessionSifu Privacy Recall search"),
                        "preferred_trigger": Variant("s", PORTAL_TRIGGER),
                    },
                ]],
                "",
                {"handle_token": Variant("s", bind_token)},
            ),
            bind_token,
        )
        self.status_changed.emit(
            f"Recall search shortcut active through the desktop portal: {SHORTCUT_LABEL}"
        )
        while not stop_event.is_set():
            await asyncio.sleep(0.2)
        try:
            session_introspection = await bus.introspect(destination, self._portal_session)
            session_object = bus.get_proxy_object(
                destination, self._portal_session, session_introspection
            )
            await session_object.get_interface("org.freedesktop.portal.Session").call_close()
        finally:
            bus.disconnect()
            self._portal_bus = None
            self._portal_session = ""

    def __del__(self) -> None:
        self.stop()

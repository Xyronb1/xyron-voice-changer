"""Windows global kısayolları (oyun/Discord öndeyken de çalışır). Ek kütüphane gerektirmez.

Kısayol iş parçacığı Tk'ye dokunmaz; basılan kısayolları kuyruğa yazar, arayüz okur.
"""

from __future__ import annotations

import queue
import sys
import threading

MOD_ALT, MOD_CONTROL, MOD_NOREPEAT = 0x0001, 0x0002, 0x4000
WM_HOTKEY, WM_QUIT = 0x0312, 0x0012

# eylem adı: (görünen ad, sanal tuş kodu)
HOTKEYS: dict[str, tuple[str, int]] = {
    "bypass": ("Ctrl+Alt+B", ord("B")),
    "mute": ("Ctrl+Alt+M", ord("M")),
    "power": ("Ctrl+Alt+V", ord("V")),
}


class GlobalHotkeys:
    def __init__(self) -> None:
        self.events: queue.Queue[str] = queue.Queue()
        self.failed: list[str] = []
        self._thread: threading.Thread | None = None
        self._thread_id = 0
        self._ready = threading.Event()

    def start(self) -> None:
        if sys.platform != "win32" or self._thread is not None:
            return
        self._thread = threading.Thread(target=self._run, name="xyrox-hotkeys", daemon=True)
        self._thread.start()
        self._ready.wait(1.0)

    def _run(self) -> None:
        import ctypes
        from ctypes import wintypes

        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32
        self._thread_id = kernel32.GetCurrentThreadId()
        ids: dict[int, str] = {}
        for i, (action, (label, vk)) in enumerate(HOTKEYS.items(), start=1):
            if user32.RegisterHotKey(None, i, MOD_CONTROL | MOD_ALT | MOD_NOREPEAT, vk):
                ids[i] = action
            else:  # başka bir program aynı kısayolu almış olabilir
                self.failed.append(label)
        self._ready.set()
        msg = wintypes.MSG()
        try:
            while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
                if msg.message == WM_HOTKEY and msg.wParam in ids:
                    self.events.put(ids[msg.wParam])
        finally:
            for i in ids:
                user32.UnregisterHotKey(None, i)

    def stop(self) -> None:
        if self._thread is None or not self._thread_id:
            return
        import ctypes
        ctypes.windll.user32.PostThreadMessageW(self._thread_id, WM_QUIT, 0, 0)
        self._thread.join(timeout=1.0)
        self._thread = None

"""Açılış yardımcıları: tek kopya koruması, açık pencereyi öne getirme, açılış ekranını kapatma.

Yavaş açılışta kullanıcı simgeye tekrar tıklayınca ikinci bir kopya açılıp ilkinin kısayollarını
ve ses aygıtlarını kapmaya çalışıyordu. Artık ikinci tıklama yeni kopya açmaz, açık olanı öne getirir.
"""

from __future__ import annotations

import ctypes
import sys

MUTEX_NAME = "Local\\Xyron.VoiceChanger.SingleInstance"
ERROR_ALREADY_EXISTS = 183
SW_RESTORE = 9


def acquire_single_instance(name: str = MUTEX_NAME) -> object | None:
    """Uygulama kilidini alır. Başka bir kopya çalışıyorsa None döner.

    Dönen tutamaç süreç boyunca saklanmalıdır; süreç bitince Windows kilidi kendisi bırakır.
    Windows dışında veya kilit oluşturulamazsa engel olmamak için her zaman izin verir.
    """
    if sys.platform != "win32":
        return True
    try:
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.CreateMutexW.restype = ctypes.c_void_p
        kernel32.CreateMutexW.argtypes = (ctypes.c_void_p, ctypes.c_bool, ctypes.c_wchar_p)
        handle = kernel32.CreateMutexW(None, False, name)
        if not handle:
            return True
        if ctypes.get_last_error() == ERROR_ALREADY_EXISTS:
            kernel32.CloseHandle.argtypes = (ctypes.c_void_p,)
            kernel32.CloseHandle(handle)
            return None
        return handle
    except (AttributeError, OSError):
        return True


def focus_existing_window(title_prefix: str) -> bool:
    """Başlığı `title_prefix` ile başlayan görünür pencereyi bulup öne getirir."""
    if sys.platform != "win32":
        return False
    try:
        from ctypes import wintypes
        user32 = ctypes.WinDLL("user32")
        hwnd_t = wintypes.HWND
        user32.IsWindowVisible.argtypes = (hwnd_t,)
        user32.GetWindowTextLengthW.argtypes = (hwnd_t,)
        user32.GetWindowTextW.argtypes = (hwnd_t, wintypes.LPWSTR, ctypes.c_int)
        user32.ShowWindow.argtypes = (hwnd_t, ctypes.c_int)
        user32.SetForegroundWindow.argtypes = (hwnd_t,)
        found: list[int] = []
        enum_proc = ctypes.WINFUNCTYPE(wintypes.BOOL, hwnd_t, wintypes.LPARAM)
        user32.EnumWindows.argtypes = (enum_proc, wintypes.LPARAM)

        def check(hwnd: int, _lparam: int) -> bool:
            if not user32.IsWindowVisible(hwnd):
                return True
            length = user32.GetWindowTextLengthW(hwnd)
            if length <= 0:
                return True
            buf = ctypes.create_unicode_buffer(length + 1)
            user32.GetWindowTextW(hwnd, buf, length + 1)
            if buf.value.startswith(title_prefix):
                found.append(hwnd)
                return False
            return True

        user32.EnumWindows(enum_proc(check), 0)
        if not found:
            return False
        user32.ShowWindow(found[0], SW_RESTORE)
        user32.SetForegroundWindow(found[0])
        return True
    except (AttributeError, OSError):
        return False


def wait_and_focus_existing_window(title_prefix: str, timeout: float = 20.0) -> bool:
    """İlk kopya hâlâ açılıyorsa penceresi belirene kadar bekleyip onu öne getirir."""
    import time
    deadline = time.monotonic() + timeout
    while True:
        if focus_existing_window(title_prefix):
            return True
        if time.monotonic() >= deadline:
            return False
        time.sleep(0.5)


def close_splash() -> None:
    """PyInstaller açılış ekranını kapatır (sadece EXE'de vardır; kaynaktan çalışırken yok)."""
    try:
        import pyi_splash  # type: ignore[import-not-found]
    except ImportError:
        return
    try:
        pyi_splash.close()
    except Exception:  # açılış ekranı zaten kapanmışsa uygulama yine açılsın
        pass

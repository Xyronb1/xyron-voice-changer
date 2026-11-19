"""Tek kopya koruması ve açılış yardımcıları."""

import sys
import uuid

import pytest

from xyrox_voice import startup


@pytest.mark.skipif(sys.platform != "win32", reason="Windows mutex")
def test_second_instance_is_detected():
    name = f"Local\\Xyron.Test.{uuid.uuid4().hex}"
    first = startup.acquire_single_instance(name)
    assert first not in (None, True)
    assert startup.acquire_single_instance(name) is None


@pytest.mark.skipif(sys.platform != "win32", reason="Windows mutex")
def test_different_names_do_not_block_each_other():
    a = startup.acquire_single_instance(f"Local\\Xyron.Test.{uuid.uuid4().hex}")
    b = startup.acquire_single_instance(f"Local\\Xyron.Test.{uuid.uuid4().hex}")
    assert a is not None and b is not None


def test_focus_returns_false_when_no_window_matches():
    assert startup.focus_existing_window(f"no-such-window-{uuid.uuid4().hex}") is False


def test_close_splash_is_safe_without_pyinstaller():
    startup.close_splash()  # kaynaktan çalışırken pyi_splash yok: sessizce geçmeli

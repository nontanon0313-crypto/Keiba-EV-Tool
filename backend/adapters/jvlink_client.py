"""JV-Link client abstraction (skeleton)."""
from __future__ import annotations
import os


class JVLinkError(RuntimeError):
    pass


class JVLinkClient:
    def __init__(self, sid, data_dir):
        self.sid = sid
        self.data_dir = data_dir

    def open(self, dataspec, fromtime, option=1):
        raise NotImplementedError

    def read(self):
        raise NotImplementedError

    def close(self):
        raise NotImplementedError


class NullJVLinkClient(JVLinkClient):
    def __init__(self, sid="", data_dir=""):
        super().__init__(sid, data_dir)
        self._opened = False

    def open(self, dataspec, fromtime, option=1):
        self._opened = True

    def read(self):
        if not self._opened:
            raise JVLinkError("open() not called")
        return iter(())

    def close(self):
        self._opened = False


class WindowsJVLinkClient(JVLinkClient):
    def __init__(self, sid, data_dir):
        super().__init__(sid, data_dir)
        self._com = None

    def _ensure_com(self):
        if self._com is not None:
            return
        try:
            import win32com.client
        except ImportError as exc:
            raise JVLinkError("pywin32 required") from exc
        self._com = win32com.client.Dispatch("JVDTLab.JVLink")

    def open(self, dataspec, fromtime, option=1):
        self._ensure_com()
        self._com.JVInit(self.sid)
        rc = self._com.JVOpen(dataspec, fromtime, option)
        if rc < 0:
            raise JVLinkError("JVOpen failed rc=" + str(rc))

    def read(self):
        self._ensure_com()
        while True:
            rc, data = self._com.JVRead("", 60000, 1)
            if rc == 0:
                break
            if rc == -1:
                continue
            if rc < -1:
                raise JVLinkError("JVRead failed rc=" + str(rc))
            if data:
                yield data

    def close(self):
        if self._com is not None:
            try:
                self._com.JVClose()
            finally:
                self._com = None


def make_default_client(sid, data_dir):
    if os.name == "nt":
        return WindowsJVLinkClient(sid, data_dir)
    return NullJVLinkClient(sid, data_dir)

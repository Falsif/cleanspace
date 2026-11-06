"""Информация о дисках (psutil)."""
from __future__ import annotations

import os
from dataclasses import dataclass

import psutil

from .utils import IS_WINDOWS


@dataclass
class DiskInfo:
    mountpoint: str     # C:\
    label: str          # «C:» или имя тома
    fstype: str
    total: int
    used: int
    free: int
    removable: bool = False

    @property
    def percent(self) -> float:
        # доля занятого относительно полного объёма (как в Проводнике)
        return (100.0 - self.free / self.total * 100) if self.total else 0.0

    @property
    def name(self) -> str:
        if IS_WINDOWS:
            return self.mountpoint.rstrip("\\/")
        return self.mountpoint


def _volume_label(mount: str) -> str:
    if not IS_WINDOWS:
        return ""
    try:
        import ctypes
        buf = ctypes.create_unicode_buffer(261)
        ok = ctypes.windll.kernel32.GetVolumeInformationW(
            ctypes.c_wchar_p(mount), buf, 261, None, None, None, None, 0)
        return buf.value if ok else ""
    except Exception:
        return ""


def list_disks() -> list[DiskInfo]:
    disks: list[DiskInfo] = []
    seen = set()
    try:
        parts = psutil.disk_partitions(all=False)
    except Exception:
        parts = []
    for p in parts:
        opts = (p.opts or "").lower()
        if IS_WINDOWS and ("cdrom" in opts or not p.fstype):
            continue  # пустые дисководы
        if not IS_WINDOWS and (p.mountpoint.startswith(("/snap", "/boot", "/proc", "/sys"))
                               or p.fstype in ("squashfs", "tmpfs", "overlay")):
            continue
        if p.mountpoint in seen:
            continue
        try:
            usage = psutil.disk_usage(p.mountpoint)
        except (OSError, PermissionError):
            continue
        if usage.total == 0:
            continue
        seen.add(p.mountpoint)
        disks.append(DiskInfo(p.mountpoint, _volume_label(p.mountpoint), p.fstype, usage.total,
                              usage.used, usage.free, "removable" in opts))
    if not disks:  # запасной вариант
        root = os.path.abspath(os.sep)
        try:
            u = psutil.disk_usage(root)
            disks.append(DiskInfo(root, "", "", u.total, u.used, u.free))
        except OSError:
            pass
    disks.sort(key=lambda d: d.mountpoint.lower())
    return disks


def system_disk() -> DiskInfo | None:
    disks = list_disks()
    if not disks:
        return None
    if IS_WINDOWS:
        sysdrive = (os.environ.get("SystemDrive", "C:") + "\\").lower()
        for d in disks:
            if d.mountpoint.lower() == sysdrive:
                return d
    for d in disks:
        if d.mountpoint == "/":
            return d
    return disks[0]

# -*- coding: utf-8 -*-
"""Small Windows notification-area icon using only the standard library."""

import ctypes
import threading
import uuid
from ctypes import wintypes


WM_DESTROY = 0x0002
WM_CLOSE = 0x0010
WM_APP = 0x8000
WM_TRAY = WM_APP + 41
WM_LBUTTONDBLCLK = 0x0203
WM_LBUTTONUP = 0x0202
WM_RBUTTONUP = 0x0205
NIM_ADD = 0x00000000
NIM_DELETE = 0x00000002
NIF_MESSAGE = 0x00000001
NIF_ICON = 0x00000002
NIF_TIP = 0x00000004
IMAGE_ICON = 1
LR_LOADFROMFILE = 0x00000010
LR_DEFAULTSIZE = 0x00000040
MF_STRING = 0x00000000
MF_SEPARATOR = 0x00000800
TPM_RETURNCMD = 0x0100
TPM_NONOTIFY = 0x0080


class _NOTIFYICONDATAW(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD), ("hWnd", wintypes.HWND),
        ("uID", wintypes.UINT), ("uFlags", wintypes.UINT),
        ("uCallbackMessage", wintypes.UINT), ("hIcon", wintypes.HICON),
        ("szTip", wintypes.WCHAR * 128), ("dwState", wintypes.DWORD),
        ("dwStateMask", wintypes.DWORD), ("szInfo", wintypes.WCHAR * 256),
        ("uTimeoutOrVersion", wintypes.UINT), ("szInfoTitle", wintypes.WCHAR * 64),
        ("dwInfoFlags", wintypes.DWORD), ("guidItem", ctypes.c_byte * 16),
        ("hBalloonIcon", wintypes.HICON),
    ]


class _WNDCLASSW(ctypes.Structure):
    pass


class WindowsTrayIcon:
    """Run a native notification icon and dispatch menu actions to a callback."""

    def __init__(self, icon_path, callback, app_name="StarTrace"):
        self.icon_path = str(icon_path)
        self.callback = callback
        self.app_name = app_name
        self.error = None
        self._ready = threading.Event()
        self._thread = threading.Thread(target=self._run, name="StarTraceTray", daemon=True)
        self._thread.start()
        self._ready.wait(5)

    def _run(self):
        try:
            self._run_native()
        except Exception as exc:
            self.error = exc
            self._ready.set()

    def _run_native(self):
        user32 = ctypes.windll.user32
        shell32 = ctypes.windll.shell32
        kernel32 = ctypes.windll.kernel32
        kernel32.GetModuleHandleW.restype = wintypes.HMODULE
        kernel32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
        user32.LoadImageW.restype = wintypes.HANDLE
        user32.LoadImageW.argtypes = [wintypes.HANDLE, wintypes.LPCWSTR, wintypes.UINT,
                                      ctypes.c_int, ctypes.c_int, wintypes.UINT]
        user32.RegisterClassW.restype = wintypes.ATOM
        user32.RegisterClassW.argtypes = [ctypes.POINTER(_WNDCLASSW)]
        user32.CreateWindowExW.restype = wintypes.HWND
        user32.CreateWindowExW.argtypes = [wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR,
                                           wintypes.DWORD, ctypes.c_int, ctypes.c_int,
                                           ctypes.c_int, ctypes.c_int, wintypes.HWND,
                                           wintypes.HMENU, wintypes.HANDLE, wintypes.LPVOID]
        user32.DefWindowProcW.restype = ctypes.c_ssize_t
        user32.DefWindowProcW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
        user32.CreatePopupMenu.argtypes = []
        user32.CreatePopupMenu.restype = wintypes.HMENU
        user32.AppendMenuW.argtypes = [wintypes.HMENU, wintypes.UINT, ctypes.c_size_t, wintypes.LPCWSTR]
        user32.TrackPopupMenu.argtypes = [wintypes.HMENU, wintypes.UINT, ctypes.c_int, ctypes.c_int,
                                          ctypes.c_int, wintypes.HWND, wintypes.LPVOID]
        user32.TrackPopupMenu.restype = wintypes.UINT
        user32.GetCursorPos.argtypes = [ctypes.POINTER(wintypes.POINT)]
        user32.SetForegroundWindow.argtypes = [wintypes.HWND]
        user32.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
        user32.GetMessageW.argtypes = [ctypes.POINTER(wintypes.MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT]
        user32.TranslateMessage.argtypes = [ctypes.POINTER(wintypes.MSG)]
        user32.DispatchMessageW.argtypes = [ctypes.POINTER(wintypes.MSG)]
        user32.DestroyMenu.argtypes = [wintypes.HMENU]
        user32.DestroyWindow.argtypes = [wintypes.HWND]
        user32.DestroyIcon.argtypes = [wintypes.HANDLE]
        user32.PostQuitMessage.argtypes = [ctypes.c_int]
        shell32.Shell_NotifyIconW.argtypes = [wintypes.DWORD, ctypes.POINTER(_NOTIFYICONDATAW)]
        shell32.Shell_NotifyIconW.restype = wintypes.BOOL
        wndproc_type = ctypes.WINFUNCTYPE(
            ctypes.c_ssize_t, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM
        )
        hinstance = kernel32.GetModuleHandleW(None)
        class_name = "StarTraceTray_" + uuid.uuid4().hex
        self._thread_id = kernel32.GetCurrentThreadId()
        self._icon_handle = user32.LoadImageW(
            None, self.icon_path, IMAGE_ICON, 0, 0, LR_LOADFROMFILE | LR_DEFAULTSIZE
        )

        def show_menu(hwnd):
            menu = user32.CreatePopupMenu()
            user32.AppendMenuW(menu, MF_STRING, 1, "打开 StarTrace")
            user32.AppendMenuW(menu, MF_STRING, 2, "立即发送邮件")
            user32.AppendMenuW(menu, MF_SEPARATOR, 0, None)
            user32.AppendMenuW(menu, MF_STRING, 3, "退出")
            point = wintypes.POINT()
            user32.GetCursorPos(ctypes.byref(point))
            user32.SetForegroundWindow(hwnd)
            command = user32.TrackPopupMenu(
                menu, TPM_RETURNCMD | TPM_NONOTIFY, point.x, point.y, 0, hwnd, None
            )
            user32.DestroyMenu(menu)
            user32.PostMessageW(hwnd, 0, 0, 0)
            actions = {1: "open", 2: "send", 3: "exit"}
            if command in actions:
                self.callback(actions[command])

        @wndproc_type
        def wndproc(hwnd, message, wparam, lparam):
            if message == WM_TRAY:
                if lparam in (WM_LBUTTONUP, WM_LBUTTONDBLCLK):
                    self.callback("open")
                elif lparam == WM_RBUTTONUP:
                    show_menu(hwnd)
                return 0
            if message == WM_DESTROY:
                data = _NOTIFYICONDATAW()
                data.cbSize = ctypes.sizeof(data)
                data.hWnd = hwnd
                data.uID = 1
                shell32.Shell_NotifyIconW(NIM_DELETE, ctypes.byref(data))
                if self._icon_handle:
                    user32.DestroyIcon(self._icon_handle)
                user32.PostQuitMessage(0)
                return 0
            if message == WM_CLOSE:
                user32.DestroyWindow(hwnd)
                return 0
            return user32.DefWindowProcW(hwnd, message, wparam, lparam)

        self._wndproc = wndproc
        _WNDCLASSW._fields_ = [
            ("style", wintypes.UINT), ("lpfnWndProc", wndproc_type),
            ("cbClsExtra", ctypes.c_int), ("cbWndExtra", ctypes.c_int),
            ("hInstance", wintypes.HANDLE), ("hIcon", wintypes.HANDLE),
            ("hCursor", wintypes.HANDLE), ("hbrBackground", wintypes.HANDLE),
            ("lpszMenuName", wintypes.LPCWSTR), ("lpszClassName", wintypes.LPCWSTR),
        ]
        wc = _WNDCLASSW()
        wc.style = 0x0008  # CS_DBLCLKS
        wc.lpfnWndProc = wndproc
        wc.hInstance = hinstance
        wc.lpszClassName = class_name
        atom = user32.RegisterClassW(ctypes.byref(wc))
        if not atom:
            self._ready.set()
            return
        hwnd = user32.CreateWindowExW(0, class_name, self.app_name, 0, 0, 0, 0, 0,
                                      None, None, hinstance, None)
        if not hwnd:
            self._ready.set()
            return
        self._hwnd = hwnd
        data = _NOTIFYICONDATAW()
        data.cbSize = ctypes.sizeof(data)
        data.hWnd = hwnd
        data.uID = 1
        data.uFlags = NIF_MESSAGE | NIF_ICON | NIF_TIP
        data.uCallbackMessage = WM_TRAY
        data.hIcon = self._icon_handle
        data.szTip = self.app_name
        if not shell32.Shell_NotifyIconW(NIM_ADD, ctypes.byref(data)):
            user32.DestroyWindow(hwnd)
            raise ctypes.WinError(ctypes.get_last_error())
        self._ready.set()
        msg = wintypes.MSG()
        while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))

    def stop(self):
        hwnd = getattr(self, "_hwnd", None)
        if hwnd:
            ctypes.windll.user32.PostMessageW(hwnd, WM_CLOSE, 0, 0)


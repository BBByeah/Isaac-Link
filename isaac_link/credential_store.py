"""Current Windows user's encrypted server invitation, outside release files."""
import ctypes
from ctypes import wintypes
import os


class Blob(ctypes.Structure):
    _fields_ = [('size', wintypes.DWORD), ('data', ctypes.POINTER(ctypes.c_ubyte))]


def _crypt(raw, decrypt=False):
    if os.name != 'nt':
        raise OSError('Windows credential storage is unavailable')
    crypt = ctypes.WinDLL('crypt32', use_last_error=True)
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.LocalFree.argtypes = [ctypes.c_void_p]
    kernel.LocalFree.restype = ctypes.c_void_p
    fn = crypt.CryptUnprotectData if decrypt else crypt.CryptProtectData
    fn.argtypes = [ctypes.POINTER(Blob), ctypes.c_void_p, ctypes.POINTER(Blob),
                   ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(Blob)]
    fn.restype = wintypes.BOOL
    buffer = (ctypes.c_ubyte * len(raw)).from_buffer_copy(raw)
    source, output = Blob(len(raw), buffer), Blob()
    if not fn(ctypes.byref(source), None, None, None, None, 1, ctypes.byref(output)):
        raise OSError('Windows credential storage failed', ctypes.get_last_error())
    try:
        return ctypes.string_at(output.data, output.size)
    finally:
        kernel.LocalFree(output.data)


class ServerCredential:
    def __init__(self, folder):
        self.path = folder / 'server-code.dpapi'

    def load(self):
        if not self.path.exists():
            return ''
        if self.path.stat().st_size > 16384:
            raise ValueError('Invalid credential size')
        return _crypt(self.path.read_bytes(), decrypt=True).decode('utf-8')

    def save(self, code):
        encrypted = _crypt(code.encode('utf-8'))
        temporary = self.path.with_suffix('.dpapi.tmp')
        temporary.write_bytes(encrypted)
        temporary.replace(self.path)

    def forget(self):
        self.path.unlink(missing_ok=True)
        self.path.with_suffix('.dpapi.tmp').unlink(missing_ok=True)

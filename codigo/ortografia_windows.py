"""Corrector ortográfico de Windows (el mismo de Edge/Office) vía COM con ctypes.
Tiene todas las formas del español: plurales, verbos conjugados, etc."""
import ctypes
import threading

ole32 = ctypes.OleDLL("ole32")
HR = ctypes.HRESULT


class GUID(ctypes.Structure):
    _fields_ = [("a", ctypes.c_uint32), ("b", ctypes.c_uint16), ("c", ctypes.c_uint16),
                ("d", ctypes.c_ubyte * 8)]

    def __init__(self, s):
        super().__init__()
        ole32.CLSIDFromString(ctypes.c_wchar_p("{" + s + "}"), ctypes.byref(self))


CLSID_FACTORY = GUID("7AB36653-1796-484B-BDFA-E74F1DB7C1DC")
IID_FACTORY = GUID("8E018A9D-2415-4677-BF08-794EA61F94BB")


def _metodo(obj, indice, *tipos):
    vtabla = ctypes.cast(obj, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents
    return ctypes.WINFUNCTYPE(HR, ctypes.c_void_p, *tipos)(vtabla[indice])


def _soltar(obj):
    vtabla = ctypes.cast(obj, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents
    ctypes.WINFUNCTYPE(ctypes.c_ulong, ctypes.c_void_p)(vtabla[2])(obj)


class OrtografiaWindows:
    """Un objeto COM por hilo (el gancho de teclado y la barra usan hilos distintos)."""

    def __init__(self, idioma="es-ES"):
        self.idioma = idioma
        self.local = threading.local()
        self.cache = {}
        self.disponible = self._checker() is not None

    def _checker(self):
        c = getattr(self.local, "c", "nada")
        if c != "nada":
            return c
        c = None
        try:
            try:
                ole32.CoInitializeEx(None, 0x2)
            except OSError:
                pass
            fab = ctypes.c_void_p()
            ole32.CoCreateInstance(ctypes.byref(CLSID_FACTORY), None, 1,
                                   ctypes.byref(IID_FACTORY), ctypes.byref(fab))
            ok = ctypes.c_int()
            _metodo(fab, 4, ctypes.c_wchar_p, ctypes.POINTER(ctypes.c_int))(
                fab, self.idioma, ctypes.byref(ok))
            if ok.value:
                sc = ctypes.c_void_p()
                _metodo(fab, 5, ctypes.c_wchar_p, ctypes.POINTER(ctypes.c_void_p))(
                    fab, self.idioma, ctypes.byref(sc))
                c = sc
        except OSError:
            c = None
        self.local.c = c
        return c

    def correcta(self, palabra):
        if palabra in self.cache:
            return self.cache[palabra]
        sc = self._checker()
        if sc is None:
            return None
        errores = ctypes.c_void_p()
        _metodo(sc, 4, ctypes.c_wchar_p, ctypes.POINTER(ctypes.c_void_p))(
            sc, palabra, ctypes.byref(errores))
        err = ctypes.c_void_p()
        hr = _metodo(errores, 3, ctypes.POINTER(ctypes.c_void_p))(errores, ctypes.byref(err))
        if err.value:
            _soltar(err)
        _soltar(errores)
        res = hr == 1 or not err.value      # S_FALSE = sin errores
        if len(self.cache) > 50000:
            self.cache.clear()
        self.cache[palabra] = res
        return res

    def sugerir(self, palabra, n=5):
        sc = self._checker()
        if sc is None:
            return []
        enum = ctypes.c_void_p()
        _metodo(sc, 5, ctypes.c_wchar_p, ctypes.POINTER(ctypes.c_void_p))(
            sc, palabra, ctypes.byref(enum))
        res = []
        siguiente = _metodo(enum, 3, ctypes.c_ulong, ctypes.POINTER(ctypes.c_wchar_p),
                            ctypes.POINTER(ctypes.c_ulong))
        while len(res) < n:
            s = ctypes.c_wchar_p()
            hecho = ctypes.c_ulong()
            if siguiente(enum, 1, ctypes.byref(s), ctypes.byref(hecho)) != 0 or not hecho.value:
                break
            res.append(s.value)
            ctypes.windll.ole32.CoTaskMemFree(s)
        _soltar(enum)
        return res


if __name__ == "__main__":
    o = OrtografiaWindows()
    print("disponible:", o.disponible)
    for w in ["todas", "quitó", "intenté", "está", "qeu", "cancion", "Keyla", "diseno"]:
        print(w, o.correcta(w), o.sugerir(w))

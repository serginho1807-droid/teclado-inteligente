"""Pregunta a Windows (UI Automation) dónde está el cuadro de texto donde
escribes y si es de contraseña. Funciona en WhatsApp, Chrome, Edge, Word...
donde Windows no da la posición del cursor."""
import ctypes
import ctypes.wintypes as wt

ole32 = ctypes.OleDLL("ole32")
HR = ctypes.HRESULT


class GUID(ctypes.Structure):
    _fields_ = [("a", ctypes.c_uint32), ("b", ctypes.c_uint16), ("c", ctypes.c_uint16),
                ("d", ctypes.c_ubyte * 8)]

    def __init__(self, s):
        super().__init__()
        ole32.CLSIDFromString(ctypes.c_wchar_p("{" + s + "}"), ctypes.byref(self))


CLSID_UIA = GUID("FF48DBA4-60EF-4201-AA87-54103EEF594E")
IID_UIA = GUID("30CBE57D-D9D0-452A-AB13-7AC5AC4825EE")
IID_TEXTO = GUID("32EBA289-3583-42C9-9C59-3B6D9A1E9B6A")
oleaut32 = ctypes.OleDLL("oleaut32")


class VARIANT(ctypes.Structure):
    _fields_ = [("vt", ctypes.c_ushort), ("r1", ctypes.c_ushort), ("r2", ctypes.c_ushort),
                ("r3", ctypes.c_ushort), ("val", ctypes.c_longlong)]


def _vt(obj, i, *tipos):
    tabla = ctypes.cast(obj, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents
    return ctypes.WINFUNCTYPE(HR, ctypes.c_void_p, *tipos)(tabla[i])


def _soltar(obj):
    tabla = ctypes.cast(obj, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents
    ctypes.WINFUNCTYPE(ctypes.c_ulong, ctypes.c_void_p)(tabla[2])(obj)


class Foco:
    """Usar siempre desde el mismo hilo (el de la barra)."""

    def __init__(self):
        self.uia = None
        self._cond = None
        try:
            try:
                ole32.CoInitializeEx(None, 0x2)
            except OSError:
                pass
            u = ctypes.c_void_p()
            ole32.CoCreateInstance(ctypes.byref(CLSID_UIA), None, 1,
                                   ctypes.byref(IID_UIA), ctypes.byref(u))
            self.uia = u
        except OSError:
            self.uia = None

    def _foco_real(self):
        """El elemento con el foco. Si Windows responde con la ventana o página
        entera (WhatsApp, Chrome), busca dentro el cuadro que tiene el foco."""
        P = ctypes.POINTER(ctypes.c_void_p)
        el = ctypes.c_void_p()
        _vt(self.uia, 8, P)(self.uia, ctypes.byref(el))
        if not el.value:
            return el
        try:
            tipo = ctypes.c_int()
            _vt(el, 21, ctypes.POINTER(ctypes.c_int))(el, ctypes.byref(tipo))
            r = wt.RECT()
            _vt(el, 43, ctypes.POINTER(wt.RECT))(el, ctypes.byref(r))
            if tipo.value not in (50030, 50032, 50033) and r.bottom - r.top < 300:
                return el                       # ya es un cuadro concreto
            if self._cond is None:
                v = VARIANT(11, 0, 0, 0, -1)    # VT_BOOL = VARIANT_TRUE
                c = ctypes.c_void_p()
                _vt(self.uia, 23, ctypes.c_int, VARIANT, P)(self.uia, 30008, v, ctypes.byref(c))
                self._cond = c                  # "tiene el foco del teclado"
            hijo = ctypes.c_void_p()
            _vt(el, 5, ctypes.c_int, ctypes.c_void_p, P)(el, 4, self._cond, ctypes.byref(hijo))
            if hijo.value:
                _soltar(el)
                return hijo
        except OSError:
            pass
        return el

    def cursor(self):
        """Rectángulo (izq, arriba, der, abajo) de la letra justo antes del cursor
        de texto, en programas modernos (WhatsApp, Chrome, Edge...). None si no se sabe."""
        if not self.uia:
            return None
        el = ctypes.c_void_p()
        try:
            el = self._foco_real()
        except OSError:
            return None
        if not el.value:
            return None
        objetos = [el]
        try:
            tp = ctypes.c_void_p()
            _vt(el, 14, ctypes.c_int, ctypes.POINTER(GUID), ctypes.POINTER(ctypes.c_void_p))(
                el, 10014, ctypes.byref(IID_TEXTO), ctypes.byref(tp))   # TextPattern
            if not tp.value:
                return None
            objetos.append(tp)
            sel = ctypes.c_void_p()
            _vt(tp, 5, ctypes.POINTER(ctypes.c_void_p))(tp, ctypes.byref(sel))
            if not sel.value:
                return None
            objetos.append(sel)
            n = ctypes.c_int()
            _vt(sel, 3, ctypes.POINTER(ctypes.c_int))(sel, ctypes.byref(n))
            if n.value < 1:
                return None
            rango = ctypes.c_void_p()
            _vt(sel, 4, ctypes.c_int, ctypes.POINTER(ctypes.c_void_p))(sel, 0, ctypes.byref(rango))
            objetos.append(rango)
            # incluir la letra anterior al cursor para que tenga tamaño
            movido = ctypes.c_int()
            _vt(rango, 14, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.POINTER(ctypes.c_int))(
                rango, 0, 0, -1, ctypes.byref(movido))
            rect = self._rectangulo(rango)
            if rect is None:                       # campo vacío: la línea entera
                _vt(rango, 6, ctypes.c_int)(rango, 3)
                rect = self._rectangulo(rango)
                if rect:
                    rect = (rect[0], rect[1], rect[0] + 2, rect[3])
            return rect
        except OSError:
            return None
        finally:
            for o in reversed(objetos):
                _soltar(o)

    def vacio(self):
        """True si el cuadro de texto activo está vacío (mensaje nuevo),
        False si tiene texto, None si no se puede saber."""
        if not self.uia:
            return None
        el = ctypes.c_void_p()
        try:
            el = self._foco_real()
        except OSError:
            return None
        if not el.value:
            return None
        objetos = [el]
        try:
            tp = ctypes.c_void_p()
            _vt(el, 14, ctypes.c_int, ctypes.POINTER(GUID), ctypes.POINTER(ctypes.c_void_p))(
                el, 10014, ctypes.byref(IID_TEXTO), ctypes.byref(tp))
            if not tp.value:
                return None
            objetos.append(tp)
            doc = ctypes.c_void_p()
            _vt(tp, 7, ctypes.POINTER(ctypes.c_void_p))(tp, ctypes.byref(doc))
            if not doc.value:
                return None
            objetos.append(doc)
            texto = ctypes.c_void_p()
            _vt(doc, 12, ctypes.c_int, ctypes.POINTER(ctypes.c_void_p))(doc, 8, ctypes.byref(texto))
            s = ctypes.wstring_at(texto.value) if texto.value else ""
            if texto.value:
                oleaut32.SysFreeString(texto)
            return not s.strip()
        except OSError:
            return None
        finally:
            for o in reversed(objetos):
                _soltar(o)

    def _rectangulo(self, rango):
        arr = ctypes.c_void_p()
        _vt(rango, 10, ctypes.POINTER(ctypes.c_void_p))(rango, ctypes.byref(arr))
        if not arr.value:
            return None
        try:
            hasta = ctypes.c_long()
            oleaut32.SafeArrayGetUBound(arr, 1, ctypes.byref(hasta))
            cuantos = hasta.value + 1
            if cuantos < 4:
                return None
            datos = ctypes.POINTER(ctypes.c_double)()
            oleaut32.SafeArrayAccessData(arr, ctypes.byref(datos))
            # puede haber varios rectángulos (varias líneas): el último es el del cursor
            x, y, w, h = (datos[cuantos - 4], datos[cuantos - 3],
                          datos[cuantos - 2], datos[cuantos - 1])
            oleaut32.SafeArrayUnaccessData(arr)
            if h <= 0:
                return None
            return int(x), int(y), int(x + w), int(y + h)
        finally:
            oleaut32.SafeArrayDestroy(arr)

    def consultar(self):
        """(rectángulo (izq, arriba, der, abajo) o None, es_contraseña)"""
        if not self.uia:
            return None, False
        el = ctypes.c_void_p()
        try:
            el = self._foco_real()
        except OSError:
            return None, False
        if not el.value:
            return None, False
        try:
            pw = wt.BOOL()
            try:
                _vt(el, 35, ctypes.POINTER(wt.BOOL))(el, ctypes.byref(pw))
            except OSError:
                pass
            r = wt.RECT()
            try:
                _vt(el, 43, ctypes.POINTER(wt.RECT))(el, ctypes.byref(r))
                rect = (r.left, r.top, r.right, r.bottom) if r.right > r.left else None
            except OSError:
                rect = None
            return rect, bool(pw.value)
        finally:
            _soltar(el)


if __name__ == "__main__":
    import time
    f = Foco()
    for _ in range(3):
        print(f.consultar(), "cursor:", f.cursor())
        time.sleep(1)

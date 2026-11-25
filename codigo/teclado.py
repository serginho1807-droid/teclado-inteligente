"""Teclado Inteligente para Windows: sugiere palabras, autocorrige y aprende
cómo escribes, como el teclado del móvil. Funciona en cualquier programa.

  Ctrl+1 / Ctrl+2 / Ctrl+3   elegir sugerencia (o clic en la barra)
  Retroceso tras corregir    deshace la corrección y recuerda tu palabra
  Ctrl+Shift+F11             pausar / reanudar
  Ctrl+Shift+F12             cerrar

Uso:  pythonw teclado.py            (sin ventana de consola)
      python teclado.py --entrenar archivo.txt [...]   aprende de tus textos
"""
import ctypes
import ctypes.wintypes as wt
import json
import os
import queue
import sys
import threading
import time
import unicodedata

try:  # coordenadas reales en pantallas con escala (125 %, 150 %...)
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
except Exception:
    pass

import tkinter as tk
from pynput import keyboard, mouse

from controlador import Controlador
from motor import Motor
from uia import Foco

# carpeta del programa (también cuando es un .exe hecho con PyInstaller)
AQUI = os.path.dirname(sys.executable if getattr(sys, "frozen", False)
                       else os.path.abspath(__file__))
# lo de cada persona va en su perfil: así el programa se puede copiar a cualquier PC
CARPETA_DATOS = os.path.join(os.environ.get("APPDATA", AQUI), "TecladoInteligente")
DATOS = os.path.join(CARPETA_DATOS, "aprendizaje.json")
CONFIG_RUTA = os.path.join(CARPETA_DATOS, "config.json")
CONFIG_BASE = {
    "autocorregir": True,
    "completar_con_espacio": True,
    "teclas_F": True,
    "emojis": True,               # emoji al lado de las palabras (como el iPhone)
    "actualizaciones": "preguntar",   # "preguntar", "automatico" o "nunca"
    "posicion_barra": None,
    "opacidad": 0.6,           # 1 = sólida, 0.4 = muy transparente
    "mayuscula_inicial": True,
    "espacio_predice": True,       # espacio tras espacio = tu siguiente palabra habitual
    "veces_para_predecir": 2,      # cuántas veces la has escrito para que lo haga
    "min_letras_autocorregir": 3,
    "num_sugerencias": 3,
    "min_frecuencia_correccion": 1000,
    "apps_excluidas": ["KeePass.exe", "KeePassXC.exe", "1Password.exe", "Bitwarden.exe",
                       "mstsc.exe", "LogonUI.exe"],
    "tamano_letra": 12,
}

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
gdi32 = ctypes.WinDLL("gdi32")
gdi32.CreateRoundRectRgn.restype = wt.HANDLE
user32.SetWindowRgn.argtypes = [wt.HWND, wt.HANDLE, wt.BOOL]
user32.GetForegroundWindow.restype = wt.HWND
user32.GetParent.restype = wt.HWND
user32.GetParent.argtypes = [wt.HWND]
user32.GetWindowThreadProcessId.argtypes = [wt.HWND, ctypes.POINTER(wt.DWORD)]
user32.GetWindowLongW.argtypes = [wt.HWND, ctypes.c_int]
user32.SetWindowLongW.argtypes = [wt.HWND, ctypes.c_int, ctypes.c_long]
user32.MapVirtualKeyW.restype = wt.UINT
kernel32.OpenProcess.restype = wt.HANDLE

MARCA = 0x7EC1AD0          # marca nuestras pulsaciones para no leerlas
VK_BACK, VK_SHIFT, VK_CONTROL, VK_MENU = 0x08, 0x10, 0x11, 0x12


# ---------------- envío de teclas (SendInput) ----------------
class KEYBDINPUT(ctypes.Structure):
    _fields_ = [("wVk", wt.WORD), ("wScan", wt.WORD), ("dwFlags", wt.DWORD),
                ("time", wt.DWORD), ("dwExtraInfo", ctypes.c_size_t)]


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [("dx", wt.LONG), ("dy", wt.LONG), ("mouseData", wt.DWORD),
                ("dwFlags", wt.DWORD), ("time", wt.DWORD), ("dwExtraInfo", ctypes.c_size_t)]


class _U(ctypes.Union):
    _fields_ = [("ki", KEYBDINPUT), ("mi", MOUSEINPUT)]


class INPUT(ctypes.Structure):
    _fields_ = [("type", wt.DWORD), ("u", _U)]


def _ki(vk=0, scan=0, flags=0):
    i = INPUT(type=1)
    i.u.ki = KEYBDINPUT(vk, scan, flags, 0, MARCA)
    return i


class Salida:
    """Borra y escribe en el programa activo desde un hilo aparte."""

    def __init__(self):
        self.cola = queue.Queue()
        threading.Thread(target=self._bucle, daemon=True).start()

    def reemplazar(self, n_borrar, texto, n_suprimir=0):
        self.cola.put((n_borrar, texto, n_suprimir, None))

    def tecla(self, vk):
        """Pulsa una tecla (p. ej. Enter) después de lo que haya en la cola."""
        self.cola.put((0, "", 0, vk))

    def _bucle(self):
        while True:
            n, texto, supr, vk_extra = self.cola.get()
            if vk_extra:
                arr = (INPUT * 2)(_ki(vk_extra), _ki(vk_extra, 0, 2))
                user32.SendInput(2, arr, ctypes.sizeof(INPUT))
                continue
            ev = []
            for vk in (0xA2, 0xA3, 0xA4, 0xA5):          # soltar Ctrl/Alt si siguen
                if user32.GetAsyncKeyState(vk) & 0x8000:
                    ev.append(_ki(vk, 0, 2))
            for _ in range(supr):                         # Supr: lo de la derecha
                ev += [_ki(0x2E, 0, 1), _ki(0x2E, 0, 1 | 2)]
            for _ in range(n):
                ev += [_ki(VK_BACK), _ki(VK_BACK, 0, 2)]
            data = texto.encode("utf-16-le")
            for k in range(0, len(data), 2):
                u = int.from_bytes(data[k:k + 2], "little")
                ev += [_ki(0, u, 4), _ki(0, u, 4 | 2)]
            if ev:
                arr = (INPUT * len(ev))(*ev)
                user32.SendInput(len(ev), arr, ctypes.sizeof(INPUT))


# ---------------- utilidades de Windows ----------------
class GUITHREADINFO(ctypes.Structure):
    _fields_ = [("cbSize", wt.DWORD), ("flags", wt.DWORD), ("hwndActive", wt.HWND),
                ("hwndFocus", wt.HWND), ("hwndCapture", wt.HWND), ("hwndMenuOwner", wt.HWND),
                ("hwndMoveSize", wt.HWND), ("hwndCaret", wt.HWND), ("rcCaret", wt.RECT)]


def pos_cursor_texto():
    hwnd = user32.GetForegroundWindow()
    tid = user32.GetWindowThreadProcessId(hwnd, None)
    gi = GUITHREADINFO(cbSize=ctypes.sizeof(GUITHREADINFO))
    if user32.GetGUIThreadInfo(tid, ctypes.byref(gi)) and gi.hwndCaret:
        pt = wt.POINT(gi.rcCaret.left, gi.rcCaret.bottom)
        user32.ClientToScreen(gi.hwndCaret, ctypes.byref(pt))
        if pt.x or pt.y:
            return pt.x, pt.y
    return None


_cache_app = {}


def app_activa(hwnd):
    if hwnd in _cache_app:
        return _cache_app[hwnd]
    pid = wt.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    nombre = ""
    h = kernel32.OpenProcess(0x1000, False, pid.value)
    if h:
        buf = ctypes.create_unicode_buffer(512)
        n = wt.DWORD(512)
        if kernel32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(n)):
            nombre = os.path.basename(buf.value)
        kernel32.CloseHandle(h)
    if len(_cache_app) > 200:
        _cache_app.clear()
    _cache_app[hwnd] = nombre
    return nombre


def pulsada(vk):
    return bool(user32.GetAsyncKeyState(vk) & 0x8000)


user32.GetKeyboardLayout.restype = ctypes.c_void_p
user32.ToUnicodeEx.argtypes = [wt.UINT, wt.UINT, ctypes.c_void_p, wt.LPWSTR, ctypes.c_int,
                               wt.UINT, ctypes.c_void_p]


def traducir_tecla(vk, scan, hwnd):
    """Qué carácter escribe esta tecla con la distribución de teclado de esa ventana
    (latinoamericana, española...). Usa ToUnicodeEx con el indicador 4, que no
    toca el estado del teclado, así las tildes (teclas muertas) siguen funcionando."""
    hkl = user32.GetKeyboardLayout(user32.GetWindowThreadProcessId(hwnd, None))
    estado = (ctypes.c_ubyte * 256)()
    for v in (0x10, 0xA0, 0xA1, 0x11, 0xA2, 0xA3, 0x12, 0xA4, 0xA5):
        if pulsada(v):
            estado[v] = 0x80
    if user32.GetKeyState(0x14) & 1:                  # Bloq Mayús
        estado[0x14] = 0x01
    buf = ctypes.create_unicode_buffer(8)
    n = user32.ToUnicodeEx(vk, scan, estado, buf, 8, 4, hkl)
    return buf.value[:n] if n > 0 else None


ACENTOS = {"´": "́", "`": "̀", "¨": "̈", "^": "̂", "~": "̃"}


def combinar(acento, letra):
    r = unicodedata.normalize("NFC", letra + ACENTOS.get(acento, ""))
    return r if len(r) == 1 else letra


# ---------------- programa ----------------
class App:
    def __init__(self, cfg):
        self.cfg = cfg
        self.motor = Motor(DATOS, cfg["min_frecuencia_correccion"])
        self.motor.completar_con_espacio = cfg["completar_con_espacio"]
        self.ui = queue.Queue()
        try:
            from gramatica import Gramatica          # se carga en segundo plano (~1 s)
            gram = Gramatica()
        except Exception:
            gram = None
        self.ctl = Controlador(self.motor, Salida(), cfg, al_cambiar=lambda: self.ui.put("act"),
                               gramatica=gram)
        self.excluir = {a.lower() for a in cfg["apps_excluidas"]}
        self.ventana_ant = None
        self.acento = None
        self.evento_muerto = False
        self.ultimo_clic = None
        self.mi_hwnd = None
        self.rect_barra = None
        self.rect_foco = None
        self.ultima_tecla = time.time()
        self.lineas = {}               # ventana -> última línea donde escribiste
        self.foco = Foco()
        self.crear_barra()

    # ----- barra de sugerencias -----
    def crear_barra(self):
        self.root = tk.Tk()
        self.root.withdraw()
        b = self.barra = tk.Toplevel(self.root)
        b.overrideredirect(True)
        b.attributes("-topmost", True)
        b.attributes("-alpha", self.cfg["opacidad"])
        b.configure(bg="#2b2d31")
        self.etiquetas = []
        letra = ("Segoe UI", self.cfg["tamano_letra"])
        # asa para arrastrar la barra a donde quieras (se recuerda el sitio)
        asa = tk.Label(b, text="⠿", fg="#8e9297", bg="#2b2d31", font=("Segoe UI", 14),
                       cursor="fleur", padx=4)
        asa.pack(side="left", fill="y")
        asa.bind("<ButtonPress-1>", self._agarrar)
        asa.bind("<B1-Motion>", self._arrastrar)
        asa.bind("<ButtonRelease-1>", self._soltar)
        asa.bind("<Button-3>", self._posicion_auto)      # clic derecho: volver a automático
        for i in range(self.cfg["num_sugerencias"]):
            f = tk.Frame(b, bg="#2b2d31")
            f.pack(side="left", padx=1, pady=1)
            num = tk.Label(f, text=f"F{i + 1}" if self.cfg["teclas_F"] else f"Ctrl+{i + 1}",
                           fg="#8e9297", bg="#2b2d31",
                           font=("Segoe UI", 7))
            num.pack(side="top")
            lab = tk.Label(f, text="", fg="white", bg="#2b2d31", font=letra,
                           padx=10, pady=2, cursor="hand2")
            lab.pack(side="top")
            for w in (lab, num, f):
                w.bind("<Button-1>", lambda e, k=i: self.ctl.elegir(k))
            lab.bind("<Enter>", lambda e, l=lab: l.configure(bg="#5865f2"))
            lab.bind("<Leave>", lambda e, l=lab: l.configure(bg="#2b2d31"))
            self.etiquetas.append((f, lab))
        # el hueco del emoji, a la derecha de las palabras (como el iPhone)
        fe = tk.Frame(b, bg="#2b2d31")
        self.num_emoji = tk.Label(fe, text="", fg="#8e9297", bg="#2b2d31", font=("Segoe UI", 7))
        self.num_emoji.pack(side="top")
        self.lab_emoji = tk.Label(fe, text="", fg="white", bg="#2b2d31", padx=8, pady=0,
                                  font=("Segoe UI Emoji", self.cfg["tamano_letra"] + 2),
                                  cursor="hand2")
        self.lab_emoji.pack(side="top")
        for w in (fe, self.num_emoji, self.lab_emoji):
            w.bind("<Button-1>", lambda e: self.ctl.elegir_emoji())
        self.lab_emoji.bind("<Enter>", lambda e: self.lab_emoji.configure(bg="#5865f2"))
        self.lab_emoji.bind("<Leave>", lambda e: self.lab_emoji.configure(bg="#2b2d31"))
        self.marco_emoji = fe
        b.withdraw()
        b.update_idletasks()
        # que no robe el foco al programa donde escribes
        self.mi_hwnd = user32.GetParent(b.winfo_id())
        ex = user32.GetWindowLongW(self.mi_hwnd, -20)
        user32.SetWindowLongW(self.mi_hwnd, -20, ex | 0x08000000 | 0x80 | 0x08)
        self.root.after(30, self.revisar_cola)
        self.root.after(30000, self.autoguardar)
        self.root.after(400, self.vigilar_foco)

    def vigilar_foco(self):
        """Cada 1/4 s: dónde está el cuadro de texto y si es de contraseña."""
        rect, contrasena = self.foco.consultar()
        self.ctl.campo_vacio = self.foco.vacio() is True   # mensaje nuevo: mayúscula
        if rect != self.rect_foco and self.rect_barra:
            self.rect_foco = rect
            self.ui.put("act")                    # recolocar la barra
        self.rect_foco = rect
        if contrasena != self.ctl.contrasena:
            self.ctl.contrasena = contrasena      # en contraseñas: ni mira ni aprende
            self.ctl.reiniciar()
        self.root.after(400, self.vigilar_foco)

    def revisar_cola(self):
        hay, aviso = False, None
        try:
            while True:
                msg = self.ui.get_nowait()
                if msg == "salir":
                    return self.salir()
                if isinstance(msg, tuple) and msg[0] == "preguntar":
                    self.ventana_actualizar(*msg[1:])
                elif isinstance(msg, tuple):
                    aviso = msg[1]
                else:
                    hay = True
        except queue.Empty:
            pass
        if aviso:
            self.aviso(aviso)
        elif hay:
            self.mostrar(self.ctl.calcular())
        self.root.after(30, self.revisar_cola)

    def mostrar(self, sugs, aviso=None):
        b = self.barra
        if aviso:
            sugs = [aviso]
        emoji = None if aviso else getattr(self.ctl, "emoji", None)
        if not sugs and not emoji:
            b.withdraw()
            self.rect_barra = None
            return
        if emoji:
            n = len(sugs) + 1
            self.num_emoji.configure(text=f"F{n}" if self.cfg["teclas_F"] else f"Ctrl+{n}")
            self.lab_emoji.configure(text=emoji)
            self.marco_emoji.pack_forget()
        else:
            self.marco_emoji.pack_forget()
        resaltar = not aviso and getattr(self.ctl, "resaltar", False)
        for i, (f, lab) in enumerate(self.etiquetas):
            if i < len(sugs):
                destacada = resaltar and i == 0      # la que pondrá el espacio
                lab.configure(text=("␣ " + sugs[i]) if destacada else sugs[i],
                              fg="#ffd866" if destacada else "white",
                              font=("Segoe UI", self.cfg["tamano_letra"],
                                    "bold" if destacada else "normal"))
                f.pack(side="left", padx=1, pady=1)
            else:
                f.pack_forget()
        if emoji:
            self.marco_emoji.pack(side="left", padx=(1, 6), pady=1)   # siempre el último
        b.update_idletasks()
        w, h = b.winfo_reqwidth(), b.winfo_reqheight()
        area = wt.RECT()
        user32.SystemParametersInfoW(0x30, 0, ctypes.byref(area), 0)
        r, _ = self.foco.consultar()             # el cuadro que tiene el foco ahora mismo
        linea = self.foco.cursor()               # letra donde escribes (WhatsApp, Chrome...)
        if not linea:
            c = pos_cursor_texto()               # programas clásicos (Bloc de notas...)
            if c:
                linea = (c[0], c[1] - 20, c[0] + 2, c[1])
        if self.cfg.get("posicion_barra"):        # la pusiste tú en un sitio
            x, y = self.cfg["posicion_barra"]
        else:
            ventana = user32.GetForegroundWindow()
            if linea and r and not (r[0] - 60 <= linea[0] <= r[2] and r[1] - 60 <= linea[1] <= r[3]):
                linea = None                     # posición rara, fuera del cuadro
            if linea:
                self.lineas[ventana] = linea     # recordar dónde escribes en esta ventana
            elif r and 0 < r[3] - r[1] < 250:
                linea = (r[0] + 30, r[1], r[0] + 32, r[3])   # cuadro de escribir
            else:
                linea = self.lineas.get(ventana)  # donde escribiste la última vez aquí
        if self.cfg.get("posicion_barra"):
            pass
        elif linea:
            # como el desplegable de Claude: justo encima de la línea que escribes
            x, y = linea[0] - 30, linea[1] - h - 4
            if y < area.top:
                y = linea[3] + 4                 # sin sitio arriba: debajo
        else:
            x, y = (area.left + area.right - w) // 2, area.top + 40
        x = max(area.left, min(x, area.right - w))
        y = max(area.top, min(y, area.bottom - h))
        b.geometry(f"+{x}+{y}")
        self.rect_barra = (x, y, x + w, y + h)
        if (w, h) != getattr(self, "_tam_region", None):   # bordes redondeados
            self._tam_region = (w, h)
            radio = max(10, h // 2)
            region = gdi32.CreateRoundRectRgn(0, 0, w + 1, h + 1, radio, radio)
            user32.SetWindowRgn(self.mi_hwnd, region, True)
        b.deiconify()
        b.attributes("-topmost", True)

    def _agarrar(self, e):
        self._agarre = (e.x_root - self.barra.winfo_x(), e.y_root - self.barra.winfo_y())

    def _arrastrar(self, e):
        x, y = e.x_root - self._agarre[0], e.y_root - self._agarre[1]
        self.barra.geometry(f"+{x}+{y}")
        self.rect_barra = (x, y, x + self.barra.winfo_width(), y + self.barra.winfo_height())

    def _posicion_auto(self, e=None):
        self.cfg["posicion_barra"] = None
        self._guardar_posicion()
        self.aviso("La barra vuelve a ir encima de donde escribes")

    def _soltar(self, e):
        self.cfg["posicion_barra"] = [self.barra.winfo_x(), self.barra.winfo_y()]
        self._guardar_posicion()

    def _guardar_posicion(self):
        self._guardar_ajuste("posicion_barra", self.cfg["posicion_barra"])

    def _guardar_ajuste(self, clave, valor):
        self.cfg[clave] = valor
        try:
            with open(CONFIG_RUTA, encoding="utf-8") as f:
                guardada = json.load(f)
        except (OSError, ValueError):
            guardada = {}
        guardada[clave] = valor
        with open(CONFIG_RUTA, "w", encoding="utf-8") as f:
            json.dump(guardada, f, ensure_ascii=False, indent=2)

    def ventana_actualizar(self, version_nueva, cambios, aceptar):
        """Hay una versión nueva: enseñar qué cambia y que decidas tú."""
        if getattr(self, "_ventana_act", None):
            return
        v = self._ventana_act = tk.Toplevel(self.root)
        v.title("Teclado Inteligente: actualización")
        v.attributes("-topmost", True)
        v.resizable(False, False)
        v.configure(bg="white", padx=18, pady=14)
        tk.Label(v, text=f"Hay una versión nueva del teclado ({version_nueva})",
                 font=("Segoe UI", 12, "bold"), bg="white").pack(anchor="w")
        tk.Label(v, text="Qué cambia:" if cambios else "No trae lista de cambios.",
                 font=("Segoe UI", 10), bg="white", fg="#555").pack(anchor="w", pady=(8, 2))
        for c in cambios[:15]:
            tk.Label(v, text="• " + c, font=("Segoe UI", 10), bg="white", justify="left",
                     wraplength=440).pack(anchor="w")
        modo = tk.StringVar(value=self.cfg.get("actualizaciones", "preguntar"))
        caja = tk.Frame(v, bg="white")
        caja.pack(anchor="w", pady=(12, 4))
        for valor, texto in (("preguntar", "Avisarme siempre antes de actualizar"),
                             ("automatico", "Actualizar solo, sin preguntar"),
                             ("nunca", "No buscar actualizaciones")):
            tk.Radiobutton(caja, text=texto, value=valor, variable=modo, bg="white",
                           font=("Segoe UI", 9)).pack(anchor="w")
        botones = tk.Frame(v, bg="white")
        botones.pack(anchor="e", pady=(10, 0))

        def cerrar():
            self._guardar_ajuste("actualizaciones", modo.get())
            self._ventana_act = None
            v.destroy()

        def actualizar():
            cerrar()
            self.reiniciar_ya = True
            self.aviso("⬇ Descargando la actualización…")
            threading.Thread(target=lambda: self._instalar(aceptar), daemon=True).start()

        def luego():
            if getattr(self, "act", None):
                self.act.mas_tarde()
            cerrar()

        tk.Button(botones, text="Ahora no", command=luego, width=12).pack(side="right", padx=4)
        tk.Button(botones, text="Actualizar", command=actualizar, width=12,
                  bg="#2b7a3d", fg="white").pack(side="right")
        v.protocol("WM_DELETE_WINDOW", luego)
        v.update_idletasks()
        x = (v.winfo_screenwidth() - v.winfo_reqwidth()) // 2
        y = (v.winfo_screenheight() - v.winfo_reqheight()) // 3
        v.geometry(f"+{x}+{y}")

    def _instalar(self, aceptar):
        try:
            if not aceptar():
                self.ui.put(("aviso", "Ya tenías la última versión"))
        except Exception:
            self.reiniciar_ya = False
            self.ui.put(("aviso", "No se pudo descargar; se intentará más tarde"))

    def aviso(self, texto):
        self.mostrar([], aviso=texto)
        self.root.after(1500, lambda: self.ui.put("act"))

    def autoguardar(self):
        with self.ctl.lock:
            self.motor.guardar()
        self.root.after(30000, self.autoguardar)

    # ----- teclado -----
    def filtro(self, msg, data):
        """Se ejecuta en cada tecla, antes que on_press. False = no procesar."""
        if data.dwExtraInfo == MARCA:            # lo escribimos nosotros
            return False
        self.ultima_tecla = time.time()
        if msg not in (0x100, 0x104):           # solo pulsaciones (no soltar)
            return False
        vk = data.vkCode
        ctrl, alt, shift = pulsada(VK_CONTROL), pulsada(VK_MENU), pulsada(VK_SHIFT)
        self.evento_muerto = False
        self.caracter = None
        if ctrl and shift and vk == 0x7A:        # Ctrl+Shift+F11
            self.ctl.pausado = not self.ctl.pausado
            self.ctl.reiniciar()
            self.ui.put(("aviso", "⏸ Teclado en pausa" if self.ctl.pausado
                         else "▶ Teclado activo"))
            self.oyente.suppress_event()
        if ctrl and shift and vk == 0x7B:        # Ctrl+Shift+F12
            self.ui.put("salir")
            self.oyente.suppress_event()
        if self.ctl.pausado or self.ctl.contrasena:
            return False
        if pulsada(0x5B) or pulsada(0x5C) or vk in (0x5B, 0x5C):
            # tecla Windows (Win+Shift+S, Win+V...): no tocar nada, y la barra se
            # queda donde está (así sale en las capturas de pantalla)
            self.tras_tecla_windows = True
            return False
        if getattr(self, "tras_tecla_windows", False):
            # el atajo pudo cambiar el texto (pegar, cambiar de ventana): empezar de cero
            self.tras_tecla_windows = False
            self.ctl.reiniciar()
        hwnd = user32.GetForegroundWindow()
        if hwnd != self.ventana_ant:
            self.ventana_ant = hwnd
            self.acento = None
            self.ctl.reiniciar()
        if app_activa(hwnd).lower() in self.excluir:
            return False
        if vk == 0x20 and not ctrl and not alt and not shift and self.ctl.espacio_predice():
            self.oyente.suppress_event()         # espacio tras espacio: tu siguiente palabra
        if vk == 0x0D and not ctrl and not alt and self.ctl.antes_de_enter():
            # "vamos a hac" + Enter: primero completar/corregir, luego enviar
            self.ctl.salida.tecla(0x0D)
            self.ctl.fin_palabra("\n")
            self.oyente.suppress_event()         # (lanza excepción: va al final)
        if vk == VK_BACK and not ctrl and not alt and self.ctl.ver_opciones_correccion():
            self.oyente.suppress_event()         # tras corregir: no borra, da opciones
        indice = None
        if ctrl and not alt and 0x31 <= vk <= 0x39:   # Ctrl+1..9 (AltGr no)
            indice = vk - 0x31
        if (self.cfg["teclas_F"] and not ctrl and not alt and not shift
                and 0x70 <= vk <= 0x78 and self.rect_barra):   # F1..F9: una sola tecla
            indice = vk - 0x70
        if indice is not None:
            if indice < len(self.ctl.visibles):
                self.ctl.elegir(indice)
                self.oyente.suppress_event()
            elif indice == len(self.ctl.visibles) and self.ctl.emoji:
                self.ctl.elegir_emoji()                # la tecla de después: el emoji
                self.oyente.suppress_event()
        try:
            self.caracter = traducir_tecla(vk, data.scanCode, hwnd)
        except Exception:
            self.caracter = None
        car = user32.MapVirtualKeyW(vk, 2)
        if car & 0x80000000:                     # tecla de tilde (muerta)
            base = chr(car & 0xFFFF)
            if shift and base == "´":
                base = "¨"
            elif shift and base == "`":
                base = "^"
            self.acento = base
            self.evento_muerto = True
        return True

    def on_press(self, key):
        if self.evento_muerto:
            return
        ctrl = pulsada(VK_CONTROL)
        alt = pulsada(VK_MENU)
        if isinstance(key, keyboard.Key):
            if key in (keyboard.Key.shift, keyboard.Key.shift_r, keyboard.Key.ctrl_l,
                       keyboard.Key.ctrl_r, keyboard.Key.alt_l, keyboard.Key.alt_r,
                       keyboard.Key.alt_gr, keyboard.Key.caps_lock):
                return
            acento, self.acento = self.acento, None
            simple = not ctrl and not alt and not pulsada(VK_SHIFT)
            if key == keyboard.Key.space and not ctrl:
                self.ctl.fin_palabra(" ")
            elif key == keyboard.Key.backspace and not ctrl:
                self.ctl.borrar()
            elif key == keyboard.Key.left and simple:
                self.ctl.izquierda()
            elif key == keyboard.Key.right and simple:
                self.ctl.derecha()
            elif key == keyboard.Key.delete and simple:
                self.ctl.suprimir()
            elif key == keyboard.Key.enter:
                self.ctl.fin_palabra("\n")
            else:                                # flechas, Tab, Inicio, Esc...
                self.ctl.reiniciar()
            return
        # el carácter según Windows y tu distribución de teclado ("?" en la
        # latinoamericana es Mayús + tecla 0xDB); pynput solo de reserva
        ch = getattr(self, "caracter", None) or getattr(key, "char", None)
        acento, self.acento = self.acento, None
        if ch is None or ord(ch[0]) < 32 or (ctrl and not alt):
            self.ctl.reiniciar()                 # atajos tipo Ctrl+C
            return
        if acento and ch.isalpha():
            ch = combinar(acento, ch)
        if ch.isalpha():
            self.ctl.letra(ch)
        else:
            self.ctl.simbolo(ch)

    def on_click(self, x, y, boton, pulsado):
        if not pulsado:
            return
        r = self.rect_barra
        if not (r and r[0] <= x <= r[2] and r[1] <= y <= r[3]):
            self.ultimo_clic = (x, y)
            self.ctl.reiniciar()

    def iniciar(self):
        self.oyente = keyboard.Listener(on_press=self.on_press, win32_event_filter=self.filtro)
        self.oyente.start()
        self.raton = mouse.Listener(on_click=self.on_click)
        self.raton.start()
        self.root.after(300, self.aviso, "⌨ Teclado Inteligente activo")
        if getattr(sys, "frozen", False):           # solo el programa instalado se actualiza
            try:
                import version
                from actualizador import Actualizador, version_instalada
                self.act = Actualizador(
                    version_instalada(version.CODIGO), version.PROGRAMA,
                    al_actualizar=self._actualizado,
                    al_avisar=lambda t: self.ui.put(("aviso", t)),
                    al_preguntar=lambda v, c, ok: self.ui.put(("preguntar", v, c, ok)),
                    modo=lambda: self.cfg.get("actualizaciones", "preguntar"))
                self.act.iniciar()
            except Exception:
                pass
        self.root.after(10000, self._quizas_reiniciar)
        self.root.mainloop()

    def _actualizado(self, version_nueva):
        """El actualizador bajó código nuevo (desde otro hilo)."""
        self.pendiente_reinicio = version_nueva

    def _quizas_reiniciar(self):
        """Aplica la actualización cuando llevas un minuto sin escribir."""
        v = getattr(self, "pendiente_reinicio", None)
        if v and (getattr(self, "reiniciar_ya", False)
                  or time.time() - self.ultima_tecla > 60 and not self.rect_barra):
            with self.ctl.lock:
                self.motor.guardar()
            import subprocess
            subprocess.Popen([sys.executable, "--reinicio"], close_fds=True)
            self.salir()
            return
        self.root.after(10000, self._quizas_reiniciar)

    def salir(self):
        with self.ctl.lock:
            self.motor.guardar()
        self.oyente.stop()
        self.raton.stop()
        self.root.destroy()


def cargar_config():
    cfg = dict(CONFIG_BASE)
    os.makedirs(CARPETA_DATOS, exist_ok=True)
    if not os.path.exists(CONFIG_RUTA):
        vieja = os.path.join(AQUI, "config.json")     # versión anterior: junto al programa
        base = dict(CONFIG_BASE)
        try:
            with open(vieja, encoding="utf-8") as f:
                base.update(json.load(f))
        except (OSError, ValueError):
            pass
        with open(CONFIG_RUTA, "w", encoding="utf-8") as f:
            json.dump(base, f, ensure_ascii=False, indent=2)
    try:
        with open(CONFIG_RUTA, encoding="utf-8") as f:
            cfg.update(json.load(f))
    except (OSError, ValueError):
        pass
    return cfg


def main():
    cfg = cargar_config()
    if sys.argv[1:] == ["--autoprueba"]:            # comprobar que el .exe funciona
        m = Motor(os.path.join(os.environ.get("TEMP", AQUI), "tec_prueba.json"))
        with open(os.path.join(os.environ.get("TEMP", AQUI), "tec_autoprueba.txt"),
                  "w", encoding="utf-8") as f:
            f.write(f"windows={bool(m.win)} palabras={len(m.frec)} foco={Foco().uia is not None}\n")
            for w in ["qeu", "cancion", "intentpe", "pal4bra", "tambie", "mas"]:
                f.write(f"{w} -> {m.sugerencias(w)} espacio={m.reemplazo(w)}\n")
            try:
                from gramatica import Gramatica
                g = Gramatica()
                for _ in range(300):
                    if g.listo:
                        break
                    time.sleep(0.1)
                f.write(f"gramatica={g.listo} {g.revisar('Ella esta trabajando.', True)}\n")
            except Exception as e:
                f.write(f"gramatica=ERROR {e!r}\n")
        return
    # entrenar: arrastrar .txt encima del programa (o --entrenar archivo.txt)
    archivos = [a for a in sys.argv[1:] if a not in ("--entrenar", "--reinicio")]
    if archivos and all(os.path.isfile(a) for a in archivos):
        m = Motor(DATOS, cfg["min_frecuencia_correccion"])
        for ruta in archivos:
            with open(ruta, encoding="utf-8", errors="ignore") as f:
                m.entrenar_texto(f.read())
        m.cambios = True
        m.guardar()
        user32.MessageBoxW(None, f"Aprendido de {len(archivos)} archivo(s).\n"
                           f"Ya conoce {len(m.usuario)} palabras tuyas.",
                           "Teclado Inteligente", 0x40)
        return
    # solo una copia abierta (tras actualizarse, esperar a que cierre la anterior)
    for intento in range(20 if "--reinicio" in sys.argv else 1):
        kernel32.CreateMutexW(None, False, "TecladoInteligente_unico")
        if ctypes.get_last_error() != 183:
            break
        time.sleep(0.5)
    else:
        return
    App(cfg).iniciar()


if __name__ == "__main__":
    main()

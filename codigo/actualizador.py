"""Actualizaciones automáticas del Teclado Inteligente.

Cada pocas horas mira en GitHub el archivo version.json. Si hay una versión
nueva del código, descarga solo los archivos .py (pocos KB), comprueba que han
llegado completos (huella SHA-256) y los guarda en
%LOCALAPPDATA%\\TecladoInteligente\\codigo\\<versión>. El lanzador usa esa carpeta
la próxima vez que arranca el teclado (y el teclado se reinicia solo cuando
llevas un rato sin escribir).

Si la versión nueva necesita librerías que este programa no trae
("min_programa" mayor que el del .exe), no se instala: avisa para descargar
el instalador completo."""
import hashlib
import json
import os
import shutil
import threading
import time
import urllib.request

# dónde se publican las versiones (repositorio público en GitHub)
try:
    from version import REPO
except ImportError:
    REPO = "{REPO}"
URL_VERSION = f"https://raw.githubusercontent.com/{REPO}/main/version.json"
URL_ARCHIVO = f"https://raw.githubusercontent.com/{REPO}/" + "{commit}/codigo/{nombre}"
CARPETA = os.path.join(os.environ.get("LOCALAPPDATA", os.path.expanduser("~")),
                       "TecladoInteligente", "codigo")
CADA = 6 * 3600                       # revisar cada 6 horas


def version_tupla(v):
    try:
        return tuple(int(x) for x in str(v).split("."))
    except ValueError:
        return (0,)


def version_instalada(base):
    """La versión del código que está en uso: la descargada o la que trae el .exe."""
    try:
        with open(os.path.join(CARPETA, "actual.json"), encoding="utf-8") as f:
            d = json.load(f)
        if os.path.isdir(os.path.join(CARPETA, d["version"])):
            if version_tupla(d["version"]) > version_tupla(base):
                return d["version"]
    except (OSError, ValueError, KeyError):
        pass
    return base


def _bajar(url, limite=5_000_000):
    req = urllib.request.Request(url, headers={"User-Agent": "TecladoInteligente"})
    with urllib.request.urlopen(req, timeout=20) as r:
        datos = r.read(limite + 1)
    if len(datos) > limite:
        raise ValueError("archivo demasiado grande")
    return datos


class Actualizador:
    """modo (lo elige cada persona en config.json o en la ventana de aviso):
      "preguntar"   avisa con la lista de cambios y solo descarga si aceptas
      "automatico"  descarga e instala solo
      "nunca"       no mira si hay versiones nuevas"""

    def __init__(self, version_codigo, version_programa, al_actualizar=None, al_avisar=None,
                 al_preguntar=None, modo=lambda: "preguntar"):
        self.base = version_codigo              # versión del código que trae el .exe
        self.programa = version_programa        # versión de las librerías del .exe
        self.al_actualizar = al_actualizar or (lambda v: None)
        self.al_avisar = al_avisar or (lambda texto: None)
        self.al_preguntar = al_preguntar or (lambda v, cambios, aceptar: None)
        self.modo = modo
        self.avisado = None
        self.preguntado = None

    def iniciar(self):
        if "{" in REPO:                         # sin repositorio configurado
            return
        threading.Thread(target=self._bucle, daemon=True).start()

    def _bucle(self):
        time.sleep(30)                          # no estorbar al arrancar
        while True:
            try:
                self.revisar()
            except Exception:
                pass                            # sin internet, GitHub caído...: otra vez luego
            time.sleep(CADA)

    def revisar(self):
        if self.modo() == "nunca":
            return None
        info = json.loads(_bajar(URL_VERSION, 200_000).decode("utf-8"))
        nueva = info["version"]
        actual = version_instalada(self.base)
        if version_tupla(nueva) <= version_tupla(actual):
            return None
        if self.modo() != "automatico":
            # avisar con lo que cambia en las versiones que te faltan; descargar
            # solo si aceptas (una vez por versión; "más tarde" vuelve a avisar)
            if self.preguntado != nueva:
                self.preguntado = nueva
                cambios = [c for h in info.get("historial", [])
                           if version_tupla(h.get("version")) > version_tupla(actual)
                           for c in h.get("cambios", [])]
                self.al_preguntar(nueva, cambios, lambda: self.instalar(info))
            return None
        return self.instalar(info)

    def mas_tarde(self):
        """"Ahora no": se volverá a avisar en la próxima revisión."""
        self.preguntado = None

    def instalar(self, info):
        nueva = info["version"]
        actual = version_instalada(self.base)
        if version_tupla(nueva) <= version_tupla(actual):
            return None
        if version_tupla(info.get("min_programa", "0")) > version_tupla(self.programa):
            if self.avisado != nueva:
                self.avisado = nueva
                self.al_avisar(f"Hay una versión nueva ({nueva}) que necesita el instalador "
                               f"completo: {info.get('instalador', 'pídeselo a quien te lo pasó')}")
            return None
        destino = os.path.join(CARPETA, nueva)
        tmp = destino + ".descargando"
        shutil.rmtree(tmp, ignore_errors=True)
        os.makedirs(tmp)
        for nombre, huella in info["archivos"].items():
            if "/" in nombre or "\\" in nombre or not nombre.endswith(".py"):
                raise ValueError("nombre de archivo no permitido")
            datos = _bajar(URL_ARCHIVO.format(commit=info["commit"], nombre=nombre))
            if hashlib.sha256(datos).hexdigest() != huella:
                shutil.rmtree(tmp, ignore_errors=True)
                raise ValueError(f"{nombre} llegó dañado")
            with open(os.path.join(tmp, nombre), "wb") as f:
                f.write(datos)
        shutil.rmtree(destino, ignore_errors=True)
        os.replace(tmp, destino)
        with open(os.path.join(CARPETA, "actual.json"), "w", encoding="utf-8") as f:
            json.dump({"version": nueva}, f)
        # borrar versiones viejas (se queda la nueva y la anterior)
        for d in sorted(os.listdir(CARPETA), key=version_tupla)[:-2]:
            if d not in (nueva, actual) and os.path.isdir(os.path.join(CARPETA, d)):
                shutil.rmtree(os.path.join(CARPETA, d), ignore_errors=True)
        self.al_actualizar(nueva)
        return nueva

"""Motor del teclado: diccionario, sugerencias, corrección y aprendizaje.
No depende de Windows, así se puede probar solo (pruebas.py)."""
import bisect
import json
import math
import os
import re
import unicodedata

import wordfreq

# Frecuencias reales del español (wordfreq), en apariciones por cada mil millones
COMUN = 30000      # palabra corriente (≈ zipf 4.5)
RARA = 300         # palabra muy poco usada (≈ zipf 2.5)
COUN_ERRATA = 100000   # por debajo de esto, si Windows no la conoce, es una errata

TILDES = {"a": "á", "e": "é", "i": "í", "o": "ó", "u": "ú",
          "á": "á", "é": "é", "í": "í", "ó": "ó", "ú": "ú"}

# determinantes: si van con una "s" de más delante de algo singular, es un error
DET_SINGULAR = {"ese", "esa", "este", "esta", "aquel", "aquella", "un", "una", "el", "la",
                "mi", "tu", "su", "nuestro", "nuestra", "vuestro", "vuestra", "otro",
                "otra", "cada", "cualquier", "ningun", "ningún", "algun", "algún", "del", "al"}
# los plurales de verdad no se tocan ("las casa" puede ser "las casas")
DET_PLURAL = {"los", "las", "unos", "unas", "esos", "esas", "estos", "estas", "mis", "tus",
              "sus", "otros", "otras", "aquellos", "aquellas", "nuestros", "nuestras",
              "vuestros", "vuestras", "eso", "esto", "es", "tus", "dels"}

# verbos tras los que qué/cómo/dónde/cuándo forman una pregunta indirecta
VERBOS_PREGUNTA = {
    "sé", "no se", "no sé", "sabes", "sabe", "sabemos", "saben", "saber", "sabía", "sabia",
    "sabías", "sabias", "sabrás", "dime", "dinos", "dígame", "digame", "decime", "dile",
    "diles", "pregunta", "pregunto", "pregunté", "pregunte", "preguntar", "preguntarle",
    "preguntale", "pregúntale", "averiguar", "averigua", "decidir", "decide", "decidimos",
    "imagina", "imagínate", "imaginate", "explica", "explícame", "explicame", "explicar",
    "entiendo", "entiendes", "entender", "depende de", "idea de", "cuéntame", "cuentame",
    "contar", "recuerdas", "recuerdo", "olvidé", "olvide", "elegir", "pensar", "veremos",
    "vemos", "mira", "miren", "fíjate", "fijate", "importa", "veré", "vere"}
ESTADOS = {"bien", "mal", "aquí", "aqui", "ahí", "ahi", "allí", "alli", "listo", "lista",
           "listos", "listas", "seguro", "segura", "loco", "loca", "cansado", "cansada",
           "enfermo", "enferma", "ocupado", "ocupada", "feliz", "contento", "contenta",
           "triste", "libre", "solo", "sola", "despierto", "despierta", "en", "de", "muy",
           "tan", "como", "cómo", "todavía", "aún", "aun", "ya"}
VERBOS_TU = {"eres", "tienes", "sabes", "puedes", "quieres", "vas", "haces", "dices",
             "crees", "piensas", "estabas", "tenías", "tenias", "fuiste", "dijiste",
             "sabías", "sabias", "también", "tambien", "mismo", "misma"}
AUN_SIN_TILDE = {"así", "asi", "cuando", "si", "sin", "con", "siendo", "sabiendo",
                 "teniendo", "a", "haciendo", "estando"}
CLITICOS = {"te", "le", "les", "me", "nos", "os"}
VERBOS_OPINION = {"parece", "parecen", "parecería", "pareció", "parecio", "pasa", "pasó",
                  "paso", "gusta", "gustó", "gusto", "gustaría", "gustaria", "apetece",
                  "ocurre", "ocurrió", "dijo", "dijeron", "dices", "opinas", "pareces",
                  "importa", "preocupa", "falta", "duele"}

# detrás de estas no hay "una cosa" (verbos y palabritas): no aplicar la concordancia
NO_SUSTANTIVO = {"son", "eran", "fueron", "serán", "seran", "sean", "están", "estan", "estaban",
                 "van", "iban", "tienen", "tenían", "hay", "han", "habían", "pueden", "que",
                 "de", "del", "con", "por", "para", "sin", "sobre", "entre", "y", "o", "pero",
                 "no", "ni", "se", "me", "te", "le", "les", "lo", "nos", "muy", "más", "mas",
                 "también", "tambien", "ya", "aquí", "aqui", "allí", "alli", "ahí", "ahi",
                 "bien", "mal", "cuando", "como", "donde", "porque", "aunque", "si", "sí"}

# palabras que llevan tilde cuando preguntan o exclaman
INTERROGATIVOS = {"que": "qué", "como": "cómo", "donde": "dónde", "adonde": "adónde",
                  "cuando": "cuándo", "cuanto": "cuánto", "cuanta": "cuánta",
                  "cuantos": "cuántos", "cuantas": "cuántas", "quien": "quién",
                  "quienes": "quiénes", "cual": "cuál", "cuales": "cuáles"}
ACENTUADOS = set(INTERROGATIVOS.values())
# verbo que suele ir detrás y también lleva tilde: "cómo estás"
VERBO_TILDE = {"estas": "estás", "esta": "está", "estan": "están", "estais": "estáis"}
# siempre son pregunta, estén donde estén
PAREJAS_SIEMPRE = {("que", "tal"), ("como", "estas"), ("como", "estás"), ("donde", "estas"),
                   ("donde", "estás"), ("cuanto", "cuesta"), ("cuanto", "vale"),
                   ("cuanto", "cuestan"), ("cuanto", "valen")}
# son pregunta cuando empiezan la frase ("Que haces" sí; "lo que haces" no)
PAREJAS_INICIO = {("que", "haces"), ("que", "hora"), ("que", "hiciste"), ("que", "opinas"),
                  ("que", "piensas"), ("que", "quieres"), ("que", "necesitas"),
                  ("que", "dices"), ("que", "hay"), ("que", "pena"), ("que", "bien"),
                  ("que", "bueno"), ("que", "lindo"), ("que", "rico"), ("que", "horror"),
                  ("que", "susto"), ("que", "alegria"), ("que", "alegría"),
                  ("como", "vas"), ("como", "va"), ("como", "van"), ("como", "esta"),
                  ("como", "está"), ("como", "así"), ("como", "asi"), ("como", "sigues"),
                  ("como", "amaneciste"), ("como", "estuvo"),
                  ("donde", "esta"), ("donde", "está"), ("donde", "vives"),
                  ("donde", "queda"), ("cuando", "vienes"), ("cuando", "llegas"),
                  ("cuando", "puedes"), ("quien", "es"), ("quien", "eres"), ("cual", "es"), ("cuanto", "es"),
                  ("cuanto", "tiempo"), ("cuantos", "años")}

# letras que están justo debajo de cada número en el teclado
DIGITO_CERCA = {"1": "qa", "2": "wqs", "3": "ewd", "4": "rea", "5": "tr", "6": "yt",
                "7": "uy", "8": "iu", "9": "oi", "0": "op"}

PALABRA_RE =re.compile(r"[^\W\d_]+", re.UNICODE)


_EMOJIS = None


def _cargar_emojis():
    """El diccionario de emojis está en emojis_datos.py, al lado de este archivo
    (también cuando llega con una actualización automática)."""
    global _EMOJIS
    if _EMOJIS is None:
        try:
            from emojis_datos import EMOJIS
            _EMOJIS = EMOJIS
        except ImportError:
            import importlib.util
            ruta = os.path.join(os.path.dirname(os.path.abspath(__file__)), "emojis_datos.py")
            try:
                spec = importlib.util.spec_from_file_location("emojis_datos", ruta)
                mod = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(mod)
                _EMOJIS = mod.EMOJIS
            except Exception:
                _EMOJIS = {}
    return _EMOJIS


def sin_tildes(s):
    return "".join(c for c in unicodedata.normalize("NFD", s)
                   if unicodedata.category(c) != "Mn")


def distancia(a, b):
    """Número de letras cambiadas, puestas o quitadas entre a y b."""
    fila = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        nueva = [i]
        for j, cb in enumerate(b, 1):
            nueva.append(min(fila[j] + 1, nueva[j - 1] + 1, fila[j - 1] + (ca != cb)))
        fila = nueva
    return fila[-1]


def aplicar_mayus(original, sugerida):
    """Copia el uso de mayúsculas de lo que escribió el usuario."""
    if not original:
        return sugerida
    if len(original) > 1 and original.isupper():
        return sugerida.upper()
    if original[0].isupper():
        return sugerida[:1].upper() + sugerida[1:]
    return sugerida


class Motor:
    def __init__(self, ruta_datos, min_frec_correccion=1000):
        self.frec = {w: max(1, int(f * 1e9))
                     for w, f in wordfreq.get_frequency_dict("es").items() if w.isalpha()}
        self.min_frec = min_frec_correccion
        self.completar_con_espacio = True
        # Índice para completar sin importar las tildes: (base, palabra)
        self.indice = sorted((sin_tildes(w), w) for w in self.frec)
        # Variantes con tilde de cada palabra: "mas" -> ["más"], "cancion" -> ["canción"]
        self.con_tilde = {}
        for w, c in self.frec.items():
            b = sin_tildes(w)
            if b != w and c >= self.min_frec:
                self.con_tilde.setdefault(b, []).append(w)
        for lista in self.con_tilde.values():
            lista.sort(key=lambda x: -self.frec[x])
        self.win = None
        try:
            from ortografia_windows import OrtografiaWindows
            ow = OrtografiaWindows("es-ES")
            self.win = ow if ow.disponible else None
        except Exception:
            pass
        if self.win:   # fuera tildes mal puestas que circulan en internet ("màs", "tambíen")
            for b in list(self.con_tilde):
                self.con_tilde[b] = [v for v in self.con_tilde[b] if self.win.correcta(v)]
                if not self.con_tilde[b]:
                    del self.con_tilde[b]
        # Para corregir "cancion" -> "canción": la variante más usada
        self.por_base = {b: l[0] for b, l in self.con_tilde.items()}
        self.ruta = ruta_datos
        self.usuario = {}      # palabra -> veces usada
        self.bigramas = {}     # palabra anterior -> {siguiente: veces}
        self.trigramas = {}    # "dos anteriores" -> {siguiente: veces}
        self.emojis_usuario = {}  # palabra -> {emoji: veces que lo elegiste}
        self.protegidas = set()  # palabras que el usuario no quiere que se corrijan
        self.cambios = False
        self.cargar()

    # ---------- datos del usuario ----------
    def cargar(self):
        try:
            with open(self.ruta, encoding="utf-8") as f:
                d = json.load(f)
            self.usuario = d.get("palabras", {})
            self.bigramas = d.get("bigramas", {})
            self.trigramas = d.get("trigramas", {})
            self.emojis_usuario = d.get("emojis", {})
            self.protegidas = set(d.get("protegidas", []))
        except (OSError, ValueError):
            pass

    def guardar(self):
        if not self.cambios:
            return
        os.makedirs(os.path.dirname(self.ruta), exist_ok=True)
        tmp = self.ruta + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({"palabras": self.usuario, "bigramas": self.bigramas,
                       "trigramas": self.trigramas, "emojis": self.emojis_usuario,
                       "protegidas": sorted(self.protegidas)}, f, ensure_ascii=False)
        os.replace(tmp, self.ruta)
        self.cambios = False

    def aprender(self, palabra, anterior=None):
        """Aprende la palabra y lo que suele ir delante. `anterior` puede ser
        una palabra ("mueble") o las dos anteriores ("el mueble")."""
        w = palabra.lower()
        if " " in w:                               # "hola como": aprender cada una
            previas = (anterior or "").lower().split()
            for parte in w.split():
                self.aprender(parte, " ".join(previas[-2:]) or None)
                previas.append(parte)
            return
        if not PALABRA_RE.fullmatch(w) or len(w) > 30:
            return
        self.usuario[w] = self.usuario.get(w, 0) + 1
        if anterior:
            ant = anterior.lower().split()
            sig = self.bigramas.setdefault(ant[-1], {})
            sig[w] = sig.get(w, 0) + 1
            if len(ant) >= 2:                      # frases de 3 palabras
                sig = self.trigramas.setdefault(" ".join(ant[-2:]), {})
                sig[w] = sig.get(w, 0) + 1
        self.cambios = True

    def proteger(self, palabra):
        w = palabra.lower()
        self.protegidas.add(w)
        self.usuario[w] = self.usuario.get(w, 0) + 2
        self.cambios = True

    def entrenar_texto(self, texto):
        """Aprende el estilo a partir de un texto ya escrito por el usuario."""
        for frase in re.split(r"[.!?¿¡\n]+", texto):
            previas = []
            for w in PALABRA_RE.findall(frase):
                self.aprender(w, " ".join(previas[-2:]) or None)
                previas.append(w.lower())

    # ---------- consultas ----------
    def falta_tilde(self, w):
        """"cancion", "tambien": formas sin tilde mucho menos usadas que con tilde."""
        v = self.por_base.get(w)
        return bool(v) and self.frec[v] > 3 * self.frec.get(w, 0)

    def conocida(self, w):
        """¿Está bien escrita? (solo cuentan tus palabras si las elegiste tú en la barra,
        así una errata repetida no se queda como buena)."""
        if w in self.protegidas:
            return True
        # palabra real que tú usas a menudo ("claude"), aunque Windows no la tenga
        if self.usuario.get(w, 0) >= 3 and self.frec.get(w, 0) >= RARA:
            return True
        if self.win:
            if self.win.correcta(w):
                # existe, pero casi nadie la usa así: "anos" (años), "sueno" (sueño)
                v = self.por_base.get(w)
                if (v and self.frec.get(v, 0) > 60 * max(1, self.frec.get(w, 0))
                        and self.usuario.get(w, 0) < 2):
                    return False
                return True
            # jerga muy usada que Windows no tiene: "jaja", "ok"...
            return self.frec.get(w, 0) >= COMUN and not self.falta_tilde(w)
        return w in self.frec and not self.falta_tilde(w)

    def puntos(self, w, anterior=None):
        """Tu forma de escribir pesa mucho más que el diccionario general."""
        p = math.log1p(self.frec.get(w, 0)) + 7.0 * math.log1p(self.usuario.get(w, 0))
        if anterior:
            ant = anterior.split()
            p += 8.0 * math.log1p(self.bigramas.get(ant[-1], {}).get(w, 0))
            if len(ant) >= 2:
                p += 10.0 * math.log1p(self.trigramas.get(" ".join(ant[-2:]), {}).get(w, 0))
        return p

    def correccion(self, palabra, anterior=None):
        """Devuelve la palabra corregida o None si no hace falta."""
        w = palabra.lower()
        if len(w) < 2 or self.conocida(w):
            return None
        b = sin_tildes(w)
        if b in self.por_base:            # solo faltaban tildes / ñ
            return self.por_base[b]
        if self.win:                      # corrector de Windows: muy fiable
            for s in self.win.sugerir(w, 3):
                s = s.lower()
                if " " not in s and distancia(w, s) <= 2:
                    return s
            return None
        letras = "abcdefghijklmnñopqrstuvwxyzáéíóúü"
        partes = [(w[:i], w[i:]) for i in range(len(w) + 1)]
        ediciones = ({a + b[1:] for a, b in partes if b}
                     | {a + b[1] + b[0] + b[2:] for a, b in partes if len(b) > 1}
                     | {a + c + b[1:] for a, b in partes if b for c in letras}
                     | {a + c + b for a, b in partes for c in letras})
        candidatos = [c for c in ediciones
                      if self.frec.get(c, 0) >= self.min_frec or c in self.protegidas]
        if not candidatos:
            return None
        return max(candidatos, key=lambda c: self.puntos(c, anterior))

    def corregir_numero(self, palabra, anterior=None):
        """"pal4bra" -> "palabra", "c0cina" -> "cocina": un número colado en medio.
        Prueba a quitarlo o a cambiarlo por una letra (mejor si es la tecla de encima)."""
        w = palabra.lower()
        digitos = [i for i, ch in enumerate(w) if ch.isdigit()]
        if len(digitos) != 1 or not 0 < digitos[0] < len(w) - 1 or len(w) < 4:
            return None
        i = digitos[0]
        cerca = DIGITO_CERCA.get(w[i], "")
        cands = {w[:i] + w[i + 1:]: 0.0}
        for c in "abcdefghijklmnñopqrstuvwxyzáéíóú":
            cands[w[:i] + c + w[i + 1:]] = 3.0 if c in cerca else 0.0
        validas = {c: extra + self.puntos(c, anterior) for c, extra in cands.items()
                   if self.conocida(c) and (c in self.frec or c in self.protegidas)}
        if validas:
            return aplicar_mayus(palabra, max(validas, key=validas.get))
        return None

    def _fuerte(self, x):
        """Palabra corriente y bien escrita (para partir palabras unidas)."""
        if len(x) == 1 and x not in "aeoyu":
            return False
        if not self.conocida(x):
            return False
        return self.frec.get(x, 0) >= COMUN or self.usuario.get(x, 0) >= 3

    def separar(self, w, anterior=None):
        """"holacomo" -> "hola como", "porfavor" -> "por favor", "dela" -> "de la"."""
        if len(w) < 4:
            return None
        r = self._partir(w, anterior, 3)
        return r[0] if r and " " in r[0] else None

    def _partir(self, w, anterior, max_partes):
        """Mejor forma de partir w en hasta max_partes palabras corrientes:
        (texto, puntos medios) o None. "alomejor" -> "a lo mejor"."""
        mejor = None
        if self._fuerte(w):
            mejor = (w, self.puntos(w, anterior))
        if max_partes > 1:
            for i in range(1, len(w)):
                a = w[:i]
                if not self._fuerte(a):
                    continue
                resto = self._partir(w[i:], a, max_partes - 1)
                if resto:
                    # media por palabra, y un poco de castigo por cada corte
                    n = resto[0].count(" ") + 2
                    p = (self.puntos(a, anterior) + resto[1] * (n - 1)) / n - 1.0
                    if mejor is None or p > mejor[1]:
                        mejor = (f"{a} {resto[0]}", p)
        return mejor

    def arreglo_p(self, w):
        """La p está junto a la tecla de tilde: "intentpe"/"intentpé" -> "intenté"."""
        for i, ch in enumerate(w):
            if ch == "p" and 0 < i < len(w) - 1 and w[i + 1] in TILDES:
                cand = w[:i] + TILDES[w[i + 1]] + w[i + 2:]
                if self.conocida(cand):
                    return cand
        return None

    def reemplazo(self, palabra, anterior=None):
        """Lo que pondrá la barra espaciadora en lugar de lo escrito (o None).
        Si la palabra ya está bien escrita, siempre se deja como está."""
        w = palabra.lower()
        if len(w) < 2:
            return None
        if (palabra != w and self.frec.get(w, 0) >= self.min_frec and w not in self.por_base
                and self.win and self.win.correcta(palabra)):
            return None                           # nombre propio escrito así: "Claude"
        if self.conocida(w):
            # palabra válida pero rarísima que casi seguro es el comienzo de otra
            if self.completar_con_espacio and w not in self.protegidas and len(w) >= 3:
                comp = self.completar(w, anterior, 1)
                if comp:
                    c = comp[0]
                    fw, fc = self.frec.get(w, 0), self.frec.get(c, 0)
                    # "mayu", "mayus": existen pero casi nadie las escribe
                    if fw < RARA and self.usuario.get(w, 0) < 2 and (
                            (fc >= self.min_frec and fc >= 10 * fw)
                            or self.usuario.get(c, 0) >= 2):
                        return c
                    # tú nunca escribes "pal"/"pala", pero "palabra" la usas mucho
                    if self.usuario.get(w, 0) == 0 and self.usuario.get(c, 0) >= 5:
                        return c
            return None
        b = sin_tildes(w)
        if b in self.por_base:                    # solo faltaba la tilde: "rapido" -> "rápido"
            return self.por_base[b]
        arreglo = self.arreglo_p(w)               # la p junto a la tilde: "intentpe"
        if arreglo:
            return arreglo
        separada = self.separar(w, anterior)
        if separada:
            comp = self.completar(w, anterior, 1) if self.completar_con_espacio else []
            if comp and self.usuario.get(comp[0], 0) >= 2:
                return comp[0]                    # una palabra tuya que empieza así
            return separada
        if self.completar_con_espacio:
            comp = self.completar(w, anterior, 1)
            if comp:
                return comp[0]
        return self.correccion(w, anterior)

    def completar(self, prefijo, anterior=None, n=3):
        p = prefijo.lower()
        bp = sin_tildes(p)
        con_tilde = bp != p
        puntuadas = {}
        i = bisect.bisect_left(self.indice, (bp, ""))
        j = bisect.bisect_left(self.indice, (bp + "￿", ""))
        for base, w in self.indice[i:j]:
            if len(w) <= len(p) or (con_tilde and not w.startswith(p)):
                continue
            if self.falta_tilde(w) and w not in self.protegidas:
                continue                      # no proponer "tambien" si existe "también"
            puntuadas[w] = self.puntos(w, anterior)
        for w, veces in self.usuario.items():
            if (veces >= 2 and len(w) > len(p) and w not in puntuadas
                    and (w in self.protegidas or (self.win and self.win.correcta(w)))):
                if (w.startswith(p) if con_tilde else sin_tildes(w).startswith(bp)):
                    puntuadas[w] = self.puntos(w, anterior)
        res = []
        for w in sorted(puntuadas, key=puntuadas.get, reverse=True):
            if self.win and sin_tildes(w) != w and not self.win.correcta(w):
                continue                      # tilde mal puesta: "tambíen"
            if (self.win and self.frec.get(w, 0) < COUN_ERRATA and w not in self.protegidas
                    and self.usuario.get(w, 0) < 3 and not self.win.correcta(w)):
                continue                      # erratas que circulan: "creoque", "tambiem"
            res.append(w)
            if len(res) >= n:
                break
        return res

    # ---------- tildes según el contexto (como el iPhone) ----------
    def _es_infinitivo(self, b):
        return (len(b) > 3 and b.endswith(("ar", "er", "ir", "arlo", "erlo", "irlo", "arla",
                                           "erla", "irla", "arle", "erle", "irle", "arse",
                                           "erse", "irse"))
                and self.conocida(b))

    def tilde_indirecta(self, a, b, antes):
        """Pregunta indirecta: "a ver que les", "no sé como", "dime donde".
        a, b en minúscula; antes = las dos palabras anteriores a `a`."""
        if a not in INTERROGATIVOS:
            return None
        prev = (antes or "").lower().split()
        t1, t2 = (prev[-1] if prev else ""), " ".join(prev[-2:])
        a_ver = t2 == "a ver"
        if not (a_ver or t1 in VERBOS_PREGUNTA or t2 in VERBOS_PREGUNTA):
            return None
        if a != "que" or a_ver:
            return INTERROGATIVOS[a]          # "no sé cómo", "a ver qué"
        # "que" detrás de saber/decir... solo es pregunta si sigue un infinitivo
        # ("no sé qué hacer") o "tal"; "sé que vienes" no lleva tilde
        if b == "tal" or self._es_infinitivo(b):
            return "qué"
        return None

    def tilde_tres(self, w0, w1, w2, antes, inicio_frase):
        """"(a ver / dime / al empezar) que te parece" -> "qué te parece".
        Mira dos palabras atrás. Devuelve la nueva w0 o None."""
        a, c, d = w0.lower(), w1.lower(), w2.lower()
        if a != "que" or c not in CLITICOS or d not in VERBOS_OPINION:
            return None
        prev = (antes or "").lower().split()
        t1, t2 = (prev[-1] if prev else ""), " ".join(prev[-2:])
        if inicio_frase or t2 == "a ver" or t1 in VERBOS_PREGUNTA or t2 in VERBOS_PREGUNTA:
            return "qué"
        return None

    def tilde_por_contexto(self, w1, w2, inicio_frase, antes=None):
        """Mirando la palabra siguiente, ¿llevaba tilde la anterior?
        "que tal" -> ("qué", "tal"), "como estas" -> ("cómo", "estás").
        Devuelve (nueva_w1, nueva_w2) o None."""
        a, b = w1.lower(), w2.lower()
        # "no se que/como..." -> "no sé" (del verbo saber)
        prev = (antes or "").lower().split()
        if a == "se" and prev and prev[-1] == "no" and (b in INTERROGATIVOS or b in ACENTUADOS
                                                        or b == "si"):
            return "sé", b
        # "estas aprendiendo" -> "estás aprendiendo" (estar + gerundio o estado)
        if a in VERBO_TILDE and (b.endswith(("ando", "iendo", "yendo")) and len(b) > 5
                                 or b in ESTADOS or (prev and prev[-1] in ("tú", "tu"))):
            return VERBO_TILDE[a], b
        # "tu estas" / "tu eres" -> "tú estás" / "tú eres"
        if a == "tu" and (b in VERBO_TILDE or b in VERBOS_TU):
            return "tú", VERBO_TILDE.get(b, b)
        # "mas rapido" -> "más rápido" (el "mas" que significa "pero" ya casi no se usa)
        if a == "mas" and b not in ("no",):
            return "más", b
        # "aun te falta" -> "aún" (= todavía); "aun así", "ni aun" -> sin tilde
        if a == "aun" and b not in AUN_SIN_TILDE and not (prev and prev[-1] == "ni"):
            return "aún", b
        ind = self.tilde_indirecta(a, b, antes)
        if ind:
            return ind, VERBO_TILDE.get(b, b) if ind != "qué" else b
        if a in INTERROGATIVOS:
            if (a, b) in PAREJAS_SIEMPRE or (inicio_frase and (a, b) in PAREJAS_INICIO):
                return INTERROGATIVOS[a], VERBO_TILDE.get(b, b)
            # lo que tú sueles escribir: "qué" delante de esta palabra y no "que"
            v = INTERROGATIVOS[a]
            con = self.bigramas.get(v, {}).get(b, 0)
            if con >= 2 and con > 2 * self.bigramas.get(a, {}).get(b, 0):
                return v, b
        if a in ACENTUADOS and b in VERBO_TILDE:        # "cómo estas" -> "cómo estás"
            return a, VERBO_TILDE[b]
        # concordancia: "eses estilo" -> "ese estilo", "estes dia" -> "este dia"
        aa = sin_tildes(a)                       # "estés" (ya corregida) cuenta como "estes"
        if (aa not in DET_PLURAL and len(b) > 2 and not b.endswith("s")
                and b not in NO_SUSTANTIVO and self.conocida(b)):
            for corte in (1, 2):
                base = aa[:-corte]
                if aa.endswith("s") and base in DET_SINGULAR:
                    return base, b
        return None

    def tilde_pregunta(self, palabras):
        """Al cerrar una pregunta con "?": la palabra interrogativa del principio
        lleva tilde ("Como estas?" -> "Cómo estás?"). Recibe las palabras de la
        frase y devuelve la lista corregida."""
        res = [p.lower() for p in palabras]
        if not res:
            return res
        i = 0
        if res[0] == "por" and len(res) > 1 and res[1] == "que":
            i = 1                                         # "por que" -> "por qué"
        if res[i] in INTERROGATIVOS:
            res[i] = INTERROGATIVOS[res[i]]
            if i + 1 < len(res) and res[i + 1] in VERBO_TILDE:
                res[i + 1] = VERBO_TILDE[res[i + 1]]
        return res

    def cambiar_pareja(self, viejo, nuevo, siguiente):
        """Tras poner la tilde, que lo aprendido diga "qué tal" y no "que tal"."""
        s = siguiente.lower()
        malo = self.bigramas.get(viejo.lower(), {})
        if malo.get(s, 0) > 0:
            malo[s] -= 1
        bueno = self.bigramas.setdefault(nuevo.lower(), {})
        bueno[s] = bueno.get(s, 0) + 1
        self.usuario[nuevo.lower()] = self.usuario.get(nuevo.lower(), 0) + 1
        self.cambios = True

    # ---------- emojis (como el iPhone: el emoji al lado de la palabra) ----------
    def emoji_para(self, palabra):
        """Emoji para esta palabra, o None. Primero el que tú sueles usar con ella."""
        if not palabra or len(palabra) < 2:
            return None
        w = palabra.lower()
        tuyos = self.emojis_usuario.get(w)
        if tuyos:
            return max(tuyos, key=tuyos.get)
        EMOJIS = _cargar_emojis()
        if not EMOJIS:
            return None
        clave = unicodedata.normalize("NFC", "".join(
            c for c in unicodedata.normalize("NFD", w)
            if unicodedata.category(c) != "Mn" or c == "̃"))
        for k in (clave, clave[:-1] if clave.endswith("s") else None,
                  clave[:-2] if clave.endswith("es") else None):
            if k and k in EMOJIS and EMOJIS[k]:
                return EMOJIS[k][0]
        return None

    def aprender_emoji(self, palabra, emoji):
        d = self.emojis_usuario.setdefault(palabra.lower(), {})
        d[emoji] = d.get(emoji, 0) + 1
        self.cambios = True

    def veces_siguiente(self, anterior, palabra):
        """Cuántas veces has escrito `palabra` justo después de `anterior`."""
        if not anterior:
            return 0
        ant = anterior.split()
        w = palabra.lower()
        tri = self.trigramas.get(" ".join(ant[-2:]), {}).get(w, 0) if len(ant) >= 2 else 0
        return max(tri, self.bigramas.get(ant[-1], {}).get(w, 0))

    def siguiente(self, anterior, n=3):
        """Próxima palabra según lo que sueles escribir: primero tus frases
        de 3 palabras, luego las de 2."""
        if not anterior:
            return []
        ant = anterior.split()
        res = []
        for tabla, clave in ((self.trigramas, " ".join(ant[-2:])), (self.bigramas, ant[-1])):
            if tabla is self.trigramas and len(ant) < 2:
                continue
            sig = tabla.get(clave, {})
            for w in sorted(sig, key=sig.get, reverse=True):
                if w not in res:
                    res.append(w)
        return res[:n]

    def sugerencias(self, escrito, anterior=None, n=3):
        """Lista para la barra: corrección primero, luego completados."""
        if not escrito:
            return self.siguiente(anterior, n)
        res = []
        lw = escrito.lower()
        completados = self.completar(escrito, anterior, n + 1)
        # primero lo que hará el espacio, para que se vea antes de pulsarlo
        primero = self.reemplazo(escrito, anterior)
        if primero:
            res.append(primero)
        # con y sin tilde: "mas" -> mas / más, "si" -> si / sí
        b = sin_tildes(lw)
        variantes = [v for v in self.con_tilde.get(b, [])
                     if v != lw and len(v) > 1 and self.conocida(v)]
        if b != lw and self.conocida(b) and (self.frec.get(b, 0) >= RARA
                                             or self.usuario.get(b, 0) > 0):
            variantes.append(b)
        if variantes:
            grupo = ([lw] if not primero and self.conocida(lw) else []) + variantes
            # primero la forma que tú más usas (con o sin tilde)
            grupo.sort(key=lambda v: -self.usuario.get(v, 0))
            res += [v for v in grupo if v not in res]
        if (primero and not completados and self.win and not self.conocida(lw)
                and sin_tildes(primero) != b):
            # mal escrita: otras posibilidades de Windows ("vuelfa" -> vuelta, vuelva)
            for s in self.win.sugerir(lw, 4):
                s = s.lower()
                if " " not in s and distancia(lw, s) <= 2 and s not in res:
                    res.append(s)
        for w in completados:
            if w not in res:
                res.append(w)
        if len(res) < n and len(escrito) > 3:
            # palabra ya completa (p. ej. al volver a ella): variantes parecidas
            raiz = escrito[:len(escrito) - 2]
            for w in self.completar(raiz, anterior, n + 3):
                if len(res) >= n:
                    break
                if w != escrito.lower() and w not in res:
                    res.append(w)
        return [aplicar_mayus(escrito, w) for w in res[:n]]

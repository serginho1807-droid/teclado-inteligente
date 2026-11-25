"""Lógica de escritura. Recuerda el texto que has escrito y dónde está el
cursor, así al volver a una palabra (Retroceso o flechas) la toma completa
y vuelve a predecir. Escribe por medio de `salida`
(en el programa real es SendInput; en las pruebas, un texto falso)."""
import threading

from motor import ACENTUADOS, INTERROGATIVOS, aplicar_mayus

ACENTUADOS_TODOS = ACENTUADOS | set(INTERROGATIVOS)

SEPARADORES = set(" .,;:!?¿¡\"()…\n")
FIN_FRASE = set(".!?¿¡\n")
SIGNOS_PEGADOS = set(".,;:!?)…")      # van pegados a la palabra, sin espacio delante
NO_CORREGIR_CON = {"\n"}   # con Enter el mensaje puede haberse enviado ya
MAX_TEXTO = 3000


class Controlador:
    def __init__(self, motor, salida, cfg, al_cambiar=None, gramatica=None):
        self.m = motor
        self.gramatica = gramatica    # reglas generales de la RAE (puede faltar)
        self.salida = salida          # .reemplazar(n_borrar, texto, n_suprimir)
        self.cfg = cfg
        self.al_cambiar = al_cambiar or (lambda: None)
        self.lock = threading.RLock()
        self.texto = ""               # lo que sabemos que hay alrededor del cursor
        self.cur = 0                  # posición del cursor dentro de self.texto
        self.ultima_corr = None       # (original, corregida)
        self.deshacer = None          # corrección a la que volviste con Retroceso
        self.opciones_corr = False    # barra mostrando opciones de la última corrección
        self.rechazadas = {}          # correcciones a las que volviste para cambiarlas
        self.visibles = []
        self.resaltar = False
        self.pausado = False
        self.contrasena = False       # el cuadro activo es de contraseña
        self.campo_vacio = False      # lo avisa la barra: el cuadro de texto está vacío
        self.inicio_campo = False     # self.texto empieza al principio del cuadro/línea

    # ---------- ayudas sobre el texto ----------
    def _tramo(self):
        """Inicio y fin de la palabra donde está el cursor, y si está 'sucia'
        (pegada a números o símbolos, p. ej. contraseñas o códigos)."""
        t, a, b = self.texto, self.cur, self.cur
        while a > 0 and t[a - 1].isalpha():
            a -= 1
        while b < len(t) and t[b].isalpha():
            b += 1
        sucia = ((a > 0 and t[a - 1] not in SEPARADORES)
                 or (b < len(t) and t[b] not in SEPARADORES)
                 # pegada a un punto sin espacio: web, correo, decimales ("google.com")
                 or (a > 1 and t[a - 1] in ".," and t[a - 2].isalnum()))
        return a, b, sucia

    def _palabra_antes(self, a):
        """(palabra, inicio) justo antes de la posición a, en la misma frase."""
        t, i = self.texto, a
        while i > 0 and not t[i - 1].isalpha():
            if t[i - 1] in FIN_FRASE:
                return None, 0
            i -= 1
        j = i
        while j > 0 and t[j - 1].isalpha():
            j -= 1
        return (t[j:i].lower() or None), j

    def _anterior(self, a):
        """Las dos palabras anteriores ("el mueble"), o una, o None."""
        p1, j = self._palabra_antes(a)
        if not p1:
            return None
        p2, _ = self._palabra_antes(j)
        return f"{p2} {p1}" if p2 else p1

    def _insertar(self, s):
        self.texto = self.texto[:self.cur] + s + self.texto[self.cur:]
        self.cur += len(s)
        if self.cur > MAX_TEXTO:
            self.texto = self.texto[1000:]
            self.cur -= 1000

    def reiniciar_sin_aviso(self):
        self.texto, self.cur = "", 0
        self.ultima_corr = self.deshacer = None
        self.opciones_corr = False
        self.espacio_auto = None
        self.inicio_campo = False

    def _opciones_de(self, original, corregida, anterior):
        """Lo que habías escrito primero, luego otras correcciones posibles."""
        otras = self.m.sugerencias(original, anterior, self.cfg["num_sugerencias"] + 2)
        res = [original] + [v for v in otras
                            if v.lower() not in (original.lower(), corregida.lower())]
        return res[:self.cfg["num_sugerencias"]]

    def espacio_predice(self):
        """Espacio justo después de un espacio: escribe la siguiente palabra que
        sueles poner (frases enteras a golpe de espacio). True si lo hizo."""
        with self.lock:
            if not (self.resaltar and self.visibles
                    and getattr(self, "visibles_para", None) == (self.texto, self.cur)):
                return False                      # barra sin actualizar: no arriesgar
            a, b, _ = self._tramo()
            if a != b or self.cur == 0 or self.texto[self.cur - 1] != " ":
                return False
        return self.elegir(0)

    def ver_opciones_correccion(self):
        """Retroceso justo después de corregir: no borra nada, enseña opciones.
        Devuelve False si no hay corrección reciente (el Retroceso borra normal)."""
        with self.lock:
            if not self.ultima_corr or self.opciones_corr:
                return False
            self.opciones_corr = True
        self.al_cambiar()
        return True

    # ---------- eventos ----------
    def _inicio_frase(self, pos):
        """¿Empieza aquí una frase? (tras punto y espacio, al principio del
        mensaje o de una línea nueva)."""
        pre = self.texto[:pos]
        q = pre.rstrip(" \t\"(«¿¡")
        if not q:
            return self.inicio_campo
        if q[-1] == "\n":
            return True
        return q[-1] in ".!?" and len(q) < len(pre)

    def letra(self, ch):
        with self.lock:
            self.ultima_corr = None
            self.opciones_corr = False
            self.espacio_auto = None
            if not self.texto:
                self.inicio_campo = self.inicio_campo or self.campo_vacio
            empieza_palabra = self.cur == 0 or not self.texto[self.cur - 1].isalpha()
            if (self.cfg.get("mayuscula_inicial", True) and ch.islower()
                    and empieza_palabra and self._inicio_frase(self.cur)):
                ch = ch.upper()
                self.salida.reemplazar(1, ch)      # cambia la letra recién escrita
            self._insertar(ch)
        self.al_cambiar()

    def simbolo(self, ch):
        if ch in SEPARADORES:
            return self.fin_palabra(ch)
        with self.lock:              # número o símbolo: la palabra queda "sucia"
            self.ultima_corr = None
            self.opciones_corr = False
            self.espacio_auto = None
            self._insertar(ch)
        self.al_cambiar()

    def fin_palabra(self, sep):
        with self.lock:
            auto = getattr(self, "espacio_auto", None)
            self.espacio_auto = None
            if (sep in SIGNOS_PEGADOS and auto == self.cur and self.cur > 0
                    and self.texto[self.cur - 1] == " "):
                # elegiste una palabra (el teclado puso el espacio) y ahora un signo:
                # "hola ," -> "hola," como en el móvil
                self.texto = self.texto[:self.cur - 1] + self.texto[self.cur:]
                self.cur -= 1
                self.salida.reemplazar(2, sep)
                self._insertar(sep)
                self.ultima_corr = None
                if sep in "?!" and self.cfg.get("tildes_contexto", True):
                    self._tildes_pregunta()
                if sep in "?!" and self.cfg.get("signos_apertura", True):
                    self._signo_apertura(sep)
                if self.gramatica and self.cfg.get("tildes_contexto", True):
                    self._revisar_gramatica(sep in ".?!")
                self.al_cambiar()
                return
            self.ultima_corr = None
            self.opciones_corr = False
            self.espacio_auto = None
            a, b, sucia = self._tramo()
            w = self.texto[a:self.cur]
            al_final = b == self.cur       # no hay letras pegadas a la derecha
            if sucia and al_final:
                # ¿un número colado en medio de la palabra? ("pal4bra")
                i = self.cur
                while i > 0 and self.texto[i - 1].isalnum():
                    i -= 1
                token = self.texto[i:self.cur]
                limpio = i == 0 or self.texto[i - 1] in SEPARADORES
                corr = (self.m.corregir_numero(token, self._anterior(i))
                        if limpio and self.cfg["autocorregir"] and sep not in NO_CORREGIR_CON
                        else None)
                self._insertar(sep)
                if corr:
                    self.salida.reemplazar(len(token) + 1, corr + sep)
                    self.texto = self.texto[:i] + corr + sep + self.texto[self.cur:]
                    self.cur = i + len(corr) + 1
                    self.ultima_corr = (token, corr)
                    self.m.aprender(corr, self._anterior(i))
                if sep == "\n":
                    self.reiniciar_sin_aviso()
                self.al_cambiar()
                return
            self._insertar(sep)
            if w and al_final and not sucia:
                anterior = self._anterior(a)
                final = w
                if w.lower() in self.rechazadas:
                    # te la corregimos, volviste atrás a cambiarla y la has escrito
                    # otra vez igual: es la que quieres, no tocarla nunca más
                    self.m.proteger(w)
                    self.rechazadas.pop(w.lower())
                elif (self.cfg["autocorregir"] and sep not in NO_CORREGIR_CON
                        and len(w) >= self.cfg["min_letras_autocorregir"]):
                    corr = self.m.reemplazo(w, anterior)
                    if corr:
                        final = aplicar_mayus(w, corr)
                        self.salida.reemplazar(len(w) + 1, final + sep)
                        self.texto = self.texto[:a] + final + sep + self.texto[self.cur:]
                        self.cur = a + len(final) + 1
                        self.ultima_corr = (w, final)
                self.m.aprender(final, anterior)
                if self.cfg.get("tildes_contexto", True) and sep != "\n":
                    if not self._espacio_movido(a, w, final):
                        self._tildes_contexto(a, final)
                if final != w:
                    self.corr_previa = (a, final, w)    # por si la siguiente lo aclara
                else:
                    self.corr_previa = None
            if sep in "?!" and self.cfg.get("tildes_contexto", True):
                self._tildes_pregunta()            # "Que bonito!" -> "Qué bonito!"
            if sep in "?!" and self.cfg.get("signos_apertura", True):
                self._signo_apertura(sep)
            if sep != "\n" and self.gramatica and self.cfg.get("tildes_contexto", True):
                self._revisar_gramatica(sep in ".?!")
            if sep == "\n":                # tras Enter el chat suele vaciarse
                self.reiniciar_sin_aviso()
                self.inicio_campo = True   # mensaje o línea nueva: mayúscula
        self.al_cambiar()

    # ---------- tildes según el contexto, corrigiendo hacia atrás ----------
    def _reescribir(self, ini, nuevo):
        """Cambia lo que hay entre ini y el cursor por `nuevo`."""
        n = self.cur - ini
        if n <= 0 or n > 150 or self.texto[ini:self.cur] == nuevo:
            return
        self.salida.reemplazar(n, nuevo)
        self.texto = self.texto[:ini] + nuevo + self.texto[self.cur:]
        self.cur = ini + len(nuevo)

    def _tildes_contexto(self, a, final):
        """"que tal" -> "qué tal": al terminar una palabra, mira si la anterior
        llevaba tilde en este contexto y la corrige aunque ya la hayas pasado."""
        p1, j = self._palabra_antes(a)
        if not p1:
            return
        fin1 = j + len(p1)
        if self.texto[fin1:a].strip():          # hay una coma u otro signo entre medias
            return
        orig1 = self.texto[j:fin1]
        antes = self._anterior(j) if not self._inicio_frase(j) else None
        self._tildes_tres(j, orig1, a, final)
        if self.texto[j:fin1] != orig1:          # lo anterior cambió de sitio: recalcular
            return
        r = self.m.tilde_por_contexto(orig1, final, self._inicio_frase(j), antes)
        if not r:
            return
        n1, n2 = aplicar_mayus(orig1, r[0]), aplicar_mayus(final, r[1])
        if (n1, n2) == (orig1, final):
            return
        resto = self.texto[a + len(final):self.cur]
        self._reescribir(j, n1 + self.texto[fin1:a] + n2 + resto)
        self.ultima_corr = None
        if n1 != orig1:
            self.m.cambiar_pareja(orig1, n1, n2)

    def _tildes_tres(self, j, w1, a, final):
        """"a ver que les parece" -> "a ver qué les parece": dos palabras atrás."""
        p0, i0 = self._palabra_antes(j)
        if not p0 or self.texto[i0 + len(p0):j].strip():
            return
        orig0 = self.texto[i0:i0 + len(p0)]
        antes = self._anterior(i0) if not self._inicio_frase(i0) else None
        nuevo = self.m.tilde_tres(orig0, w1, final, antes, self._inicio_frase(i0))
        if not nuevo:
            return
        n0 = aplicar_mayus(orig0, nuevo)
        if n0 == orig0:
            return
        self._reescribir(i0, n0 + self.texto[i0 + len(orig0):self.cur])
        self.ultima_corr = None
        self.m.cambiar_pareja(orig0, n0, w1)

    def _espacio_movido(self, a, w2, final):
        """"Creoq ue" -> "Creo que": el espacio cayó una letra antes o después.
        Devuelve True si lo arregló."""
        p1, j = self._palabra_antes(a)
        if not p1 or self.texto[j + len(p1):a] != " ":
            return False
        actual1 = self.texto[j:j + len(p1)]
        o1 = actual1
        cp = getattr(self, "corr_previa", None)
        if cp and cp[0] == j and cp[1] == actual1:
            o1 = cp[2]                               # lo que escribiste de verdad
        o2 = w2
        l1, l2 = o1.lower(), o2.lower()
        if self.m.conocida(l1) and self.m.conocida(l2):
            return False                             # las dos existen: no tocar
        opciones = []
        if len(l1) > 1:
            opciones.append((o1[:-1], o1[-1] + o2))  # "Creoq ue" -> "Creo que"
        if len(l2) > 1:
            opciones.append((o1 + o2[0], o2[1:]))    # "Cre oque" -> "Creo que"
        mejor = None
        for n1, n2 in opciones:
            if self.m._fuerte(n1.lower()) and self.m._fuerte(n2.lower()):
                p = self.m.puntos(n1.lower()) + self.m.puntos(n2.lower(), n1.lower())
                if mejor is None or p > mejor[0]:
                    mejor = (p, n1, n2)
        if not mejor:
            return False
        _, n1, n2 = mejor
        resto = self.texto[a + len(final):self.cur]  # el separador
        self._reescribir(j, n1 + " " + n2.lower() + resto)
        self.ultima_corr = None
        self.corr_previa = None
        self.m.aprender(n2, n1)
        return True

    def _signo_apertura(self, sep):
        """En español la pregunta y la exclamación se abren: "¿" "¡".
        "Será que sí?" -> "¿Será que sí?", "Hola, cómo estás?" -> "Hola, ¿cómo estás?"."""
        abre = "¿" if sep == "?" else "¡"
        fin = self.cur - 1
        i = fin
        while i > 0 and self.texto[i - 1] not in ".!?\n¿¡":
            i -= 1
        if i > 0 and self.texto[i - 1] in "¿¡":
            return                                   # ya está abierta
        if i == 0 and not self.inicio_campo:
            return                                   # no sabemos dónde empieza
        frase = self.texto[i:fin]
        if abre in frase or not frase.strip():
            return
        # si hay comas, la pregunta empieza en la parte que lleva el qué/cómo...
        k = i + (len(frase) - len(frase.lstrip()))
        import re
        for m in re.finditer(r",\s*", frase):
            resto = frase[m.end():]
            pal = re.match(r"[^\W\d_]+", resto)
            if pal and (pal.group().lower() in ACENTUADOS_TODOS):
                k = i + m.end()
        self._reescribir(k, abre + self.texto[k:self.cur])

    def _revisar_gramatica(self, cerrada):
        """Reglas generales de la RAE (tilde diacrítica) sobre la frase actual:
        "Ella esta trabajando" -> "Ella está trabajando", "El me dijo" -> "Él me dijo"."""
        i = self.cur
        while i > 0 and self.texto[i - 1] not in ".!?\n¿¡" and self.cur - i < 300:
            i -= 1
        if cerrada:                                  # incluir el signo que acaba de cerrar
            i = self.cur - 1
            while i > 0 and self.texto[i - 1] not in ".!?\n¿¡" and self.cur - i < 300:
                i -= 1
        frase = self.texto[i:self.cur]
        cambios = [(a, b, n) for a, b, n in self.gramatica.revisar(frase, cerrada)
                   if frase[a:b].lower() not in self.m.protegidas]
        if not cambios:
            return
        nueva = frase
        for a, b, n in sorted(cambios, reverse=True):
            nueva = nueva[:a] + n + nueva[b:]
        primero = cambios[0][0]
        self._reescribir(i + primero, nueva[primero:])
        self.ultima_corr = None

    def _tildes_pregunta(self):
        """Al cerrar con "?": "como estas?" -> "cómo estás?", "que hora es?" ->
        "qué hora es?". Busca el principio de la pregunta."""
        t, fin = self.texto, self.cur - 1            # fin: posición del "?"
        i = fin
        while i > 0 and t[i - 1] not in ".!?\n¿¡":
            i -= 1
        if i == 0 and not self.inicio_campo:
            return                                   # no sabemos dónde empieza la frase
        import re
        trozos = list(re.finditer(r"[^\W\d_]+", t[i:fin]))[:3]
        if not trozos:
            return
        nuevas = self.m.tilde_pregunta([m.group() for m in trozos])
        if all(m.group().lower() == n for m, n in zip(trozos, nuevas)):
            return
        ini = i + trozos[0].start()
        partes, pos = [], ini
        for m, n in zip(trozos, nuevas):
            ia, ib = i + m.start(), i + m.end()
            partes.append(t[pos:ia])
            partes.append(aplicar_mayus(m.group(), n) if m.group().lower() != n else m.group())
            pos = ib
        partes.append(t[pos:self.cur])
        self._reescribir(ini, "".join(partes))
        self.ultima_corr = None
        for k, (m, n) in enumerate(zip(trozos, nuevas)):
            if m.group().lower() != n and k + 1 < len(nuevas):
                self.m.cambiar_pareja(m.group(), n, nuevas[k + 1])

    def borrar(self):
        with self.lock:
            # tras una corrección, Retroceso borra normal; lo que escribiste
            # queda en la barra por si lo quieres recuperar
            self.espacio_auto = None
            if self.ultima_corr:                   # volviste atrás justo tras corregir
                self.rechazadas[self.ultima_corr[0].lower()] = self.ultima_corr[1]
                if len(self.rechazadas) > 30:
                    self.rechazadas.pop(next(iter(self.rechazadas)))
            self.deshacer, self.ultima_corr = self.ultima_corr, None
            if self.cur > 0:
                self.texto = self.texto[:self.cur - 1] + self.texto[self.cur:]
                self.cur -= 1
            else:
                self.reiniciar_sin_aviso()         # texto que no conocemos
        self.al_cambiar()

    def suprimir(self):
        with self.lock:
            self.ultima_corr = None
            self.opciones_corr = False
            self.espacio_auto = None
            if self.cur < len(self.texto):
                self.texto = self.texto[:self.cur] + self.texto[self.cur + 1:]
            else:
                self.reiniciar_sin_aviso()
        self.al_cambiar()

    def izquierda(self):
        with self.lock:
            self.ultima_corr = None
            self.opciones_corr = False
            self.espacio_auto = None
            if self.cur > 0:
                self.cur -= 1
            else:
                self.reiniciar_sin_aviso()
        self.al_cambiar()

    def derecha(self):
        with self.lock:
            self.ultima_corr = None
            self.opciones_corr = False
            self.espacio_auto = None
            if self.cur < len(self.texto):
                self.cur += 1
            else:
                self.reiniciar_sin_aviso()
        self.al_cambiar()

    def reiniciar(self):
        with self.lock:
            self.reiniciar_sin_aviso()
        self.al_cambiar()

    def elegir(self, i):
        with self.lock:
            if i >= len(self.visibles):
                return False
            if self.opciones_corr and self.ultima_corr:
                # cambiar la palabra recién corregida sin tocar el espacio de detrás
                original, corregida = self.ultima_corr
                self.rechazadas.pop(original.lower(), None)   # ya elegiste en la barra
                sep = self.texto[self.cur - 1]
                ini = self.cur - 1 - len(corregida)
                palabra = aplicar_mayus(original, self.visibles[i])
                self.salida.reemplazar(len(corregida) + 1, palabra + sep)
                anterior = self._anterior(ini)
                self.texto = self.texto[:ini] + palabra + sep + self.texto[self.cur:]
                self.cur = ini + len(palabra) + 1
                if palabra.lower() == original.lower():
                    self.m.proteger(palabra)      # era lo que querías: no corregirla más
                else:
                    self.m.aprender(palabra, anterior)
                self.ultima_corr = self.deshacer = None
                self.opciones_corr = False
                self.espacio_auto = None
            else:
                return self._elegir_normal(i)
        self.al_cambiar()
        return True

    def _elegir_normal(self, i):
        with self.lock:
            a, b, _ = self._tramo()
            actual = self.texto[a:b]
            palabra = aplicar_mayus(actual, self.visibles[i]) if actual else self.visibles[i]
            sep = "" if self.texto[b:b + 1] == " " else " "
            # borra la palabra entera, también lo que queda a la derecha del cursor
            self.salida.reemplazar(self.cur - a, palabra + sep, b - self.cur)
            anterior = self._anterior(a)
            self.texto = self.texto[:a] + palabra + sep + self.texto[b:]
            self.cur = a + len(palabra) + len(sep)
            self.espacio_auto = self.cur if sep == " " else None   # lo puso el teclado
            if self.deshacer:
                self.rechazadas.pop(self.deshacer[0].lower(), None)   # ya elegiste en la barra
            if self.deshacer and palabra.lower() == self.deshacer[0].lower():
                self.m.proteger(palabra)          # no volver a corregirla
            else:
                self.m.aprender(palabra, anterior)
            self.ultima_corr = self.deshacer = None
        self.al_cambiar()
        return True

    # ---------- para la barra ----------
    def palabra_actual(self):
        with self.lock:
            a, b, sucia = self._tramo()
            return self.texto[a:b], sucia

    def calcular(self):
        with self.lock:
            self.resaltar = False
            a, b, sucia = self._tramo()
            buf = self.texto[a:b]
            if self.pausado or self.contrasena or sucia:
                self.visibles = []
                return []
            if self.opciones_corr and self.ultima_corr:
                original, corregida = self.ultima_corr
                ini = self.cur - 1 - len(corregida)
                self.visibles = self._opciones_de(original, corregida, self._anterior(ini))
                return list(self.visibles)
            anterior = self._anterior(a)
            if self.deshacer and b == self.cur and buf == self.deshacer[1]:
                self.visibles = self._opciones_de(*self.deshacer, anterior)
                return list(self.visibles)
            self.visibles = self.m.sugerencias(buf, anterior, self.cfg["num_sugerencias"])
            self.visibles_para = (self.texto, self.cur)
            if (not buf and self.cfg.get("mayuscula_inicial", True)
                    and self._inicio_frase(self.cur)):
                self.visibles = [v[:1].upper() + v[1:] for v in self.visibles]
            if not buf:
                # ¿pondrá el espacio la siguiente palabra? solo si la sueles escribir aquí
                self.resaltar = bool(
                    self.visibles and self.cfg.get("espacio_predice", True)
                    and self.cur > 0 and self.texto[self.cur - 1] == " "
                    and self.m.veces_siguiente(anterior, self.visibles[0])
                    >= self.cfg.get("veces_para_predecir", 2))
                return list(self.visibles)
            self.deshacer = None
            # ¿la primera es la que pondrá el espacio? (solo al final de la palabra)
            self.resaltar = bool(buf and b == self.cur and self.cfg["autocorregir"]
                                 and len(buf) >= self.cfg["min_letras_autocorregir"]
                                 and self.m.reemplazo(buf, anterior))
            return list(self.visibles)

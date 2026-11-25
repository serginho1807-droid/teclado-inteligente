"""Reglas generales de la RAE para la tilde diacrítica, aplicadas a toda la frase.

La tilde diacrítica distingue palabras que se escriben igual según su FUNCIÓN:
  el (artículo)        / él (pronombre)      "el perro"   / "él me dijo"
  tu, mi (posesivos)   / tú, mí (pronombres) "tu casa"    / "tú eres", "para mí"
  esta, estas (determ.)/ está, estás (verbo) "esta mesa"  / "está trabajando"
  te (pronombre)       / té (sustantivo)     "te quiero"  / "un té"
  de (preposición)     / dé (verbo dar)      "casa de"    / "que me dé"
  se (pronombre)       / sé (verbo saber)    "se fue"     / "no sé", "lo sé"
  si (condicional)     / sí (afirmación)     "si quieres" / "dijo que sí"
  mas (= pero, en desuso) / más (cantidad)   "más rápido"

Regla de fondo: un determinante (el, tu, mi, esta, estas) SIEMPRE va delante de un
sustantivo (o adjetivo/número) con el que concuerda en género y número. Si detrás
viene un verbo, un pronombre, un adverbio o se acaba la frase, no es determinante
y lleva tilde. Para saber qué es cada palabra vecina se usa un analizador
gramatical (spaCy, modelo de español), sin internet.

Solo AÑADE tildes, nunca las quita: si tú la pusiste, es que la querías."""
import threading

NOMINAL = {"NOUN", "ADJ", "NUM", "PROPN", "DET"}
# determinante -> (forma con tilde, género, número) que debe tener lo que sigue
DETERMINANTES = {"el": ("él", "Masc", "Sing"), "tu": ("tú", None, "Sing"),
                 "mi": ("mí", None, "Sing"), "esta": ("está", "Fem", "Sing"),
                 "estas": ("estás", "Fem", "Plur")}
# tras estas, "el" sigue siendo artículo ("el que quiera", "el de Juan")
NO_DECIDE = {"que", "de", "cual", "cuál", "del"}
ANTES_DE_TE_SUSTANTIVO = {"un", "el", "del", "al", "mi", "tu", "su", "este", "ese",
                          "buen", "otro", "ningún", "algún", "rico", "tu", "mi"}
CLITICOS = {"me", "te", "le", "les", "nos", "os", "se"}
ANTES_DE_SE = {"no", "ya", "lo", "tampoco", "ni", "bien", "yo"}
ANTES_DE_SI = {"que", "eso", "claro", "pues", "creo", "dijo", "dije", "porque",
               "esto", "ahora", "también", "tambien", "a", "para", "de", "entre", "por"}
CIERRES = set(".?!,;:…)\"»")
PREPOSICIONES = {"a", "para", "de", "en", "por", "sin", "sobre", "contra", "hacia", "según",
                 "segun", "entre", "ante", "tras", "desde", "hasta", "con"}
FIN = object()                                     # marca: aquí se acaba la frase
ANTES_DE_AHI = {"por", "de", "está", "esta", "estás", "estas", "están", "estan", "estoy",
                "estaba", "ponlo", "ponla", "déjalo", "dejalo", "déjala", "dejala", "allí",
                "quédate", "quedate", "hasta", "desde"}
FORMAS_IR = {"voy", "vas", "va", "vamos", "van", "iba", "ibas", "íbamos", "ibamos", "iban",
             "fui", "fue", "fuimos", "fueron", "ir", "vete", "ve"}
FORMAS_HABER = {"he", "has", "ha", "hemos", "han", "había", "habia", "habías", "habias",
                "habíamos", "habiamos", "habían", "habian", "haber", "habría", "habria",
                "hubiera", "hubiese", "haya", "hayas", "hayan", "hayamos", "habiendo"}
ANTES_DE_HABER = {"de", "puede", "pueden", "debe", "deben", "debería", "deberia", "podría",
                  "podria", "tiene", "tienen", "que", "para", "sin", "por", "va", "a"}
ANTES_DE_VAYA = {"que", "se", "me", "te", "le", "les", "nos", "no", "ojalá", "ojala",
                 "cuando", "donde"}
ANTES_DE_VEZ = {"otra", "tal", "una", "cada", "la", "esta", "esa", "primera", "última",
                "ultima", "alguna", "ninguna", "segunda", "única", "unica", "toda"}


class Gramatica:
    def __init__(self):
        self.nlp = None
        self.listo = False
        threading.Thread(target=self._cargar, daemon=True).start()

    def _cargar(self):
        try:
            import sys
            # spaCy intenta cargar torch/tensorflow si están instalados (+500 MB):
            # no hacen falta para etiquetar palabras
            for pesado in ("torch", "tensorflow", "cupy", "jax", "transformers"):
                sys.modules.setdefault(pesado, None)
            import spacy
            self.nlp = spacy.load("es_core_news_md", exclude=["ner", "lemmatizer", "parser"])
            self.nlp("hola que tal")            # calentar
            self.listo = True
        except Exception:
            self.nlp = None

    def revisar(self, frase, cerrada=False):
        """Devuelve [(inicio, fin, nueva_palabra)] con las tildes que faltan.
        `cerrada`: la frase terminó (punto, ?, !), así la última palabra también
        se puede decidir; si no, la última se deja para cuando llegue la siguiente."""
        if not self.listo or not frase.strip():
            return []
        try:
            doc = self.nlp(frase)
        except Exception:
            return []
        toks = [t for t in doc]
        cambios = {}                               # índice -> nueva palabra
        verbo = set()                              # índices que pasan a ser verbo/pronombre

        def siguiente(i):
            """Palabra siguiente, o FIN si la frase se acaba ahí, o None si
            todavía no la sabemos (estás escribiendo)."""
            if i + 1 < len(toks):
                t = toks[i + 1]
                if t.is_punct or t.text in CIERRES:
                    return FIN
                return t
            return FIN if cerrada else None

        def es_verbo_conjugado(t):
            return t.pos_ in ("VERB", "AUX") and "Fin" in t.morph.get("VerbForm")

        def concuerda(genero, numero, t):
            g, n = t.morph.get("Gender"), t.morph.get("Number")
            if genero and g and genero not in g:
                return False
            if numero and n and numero not in n:
                return False
            return True

        # primero las palabras que suenan igual ("que ay" -> "que hay"), así la
        # tilde de la anterior se decide con la palabra ya corregida
        dobles = self._homofonos(toks, siguiente, cambios)
        # de derecha a izquierda: así "Tu estas loco" decide primero "estás"
        for i in range(len(toks) - 1, -1, -1):
            t = toks[i]
            w = t.text.lower()
            if t.text != t.text.lower() and t.text != t.text.capitalize():
                continue                            # siglas, MAYÚSCULAS: no tocar
            sig = siguiente(i)
            prev = toks[i - 1].text.lower() if i > 0 else None

            if w in DETERMINANTES and sig is not None:
                tilde, genero, numero = DETERMINANTES[w]
                if sig is not FIN and sig.text.lower() in NO_DECIDE:
                    continue
                fin = sig is FIN
                ya_verbo = not fin and (i + 1) in verbo
                if not fin and cambios.get(i + 1) in ("ahí", "a ver"):
                    fin = True                      # "esta hay" -> "está ahí": lo que sigue no es sustantivo
                # tras un determinante no puede ir otro artículo, posesivo o
                # demostrativo ("esta mi casa" no existe: es "está mi casa")
                otro_det = (not fin and sig.pos_ == "DET" and (
                    "Yes" in sig.morph.get("Poss")
                    or set(sig.morph.get("PronType")) & {"Art", "Dem", "Prs"}))
                es_det = (not fin and not ya_verbo and not otro_det
                          and sig.pos_ in NOMINAL and concuerda(genero, numero, sig))
                if (w in ("esta", "estas") and es_det and i > 0
                        and (toks[i - 1].pos_ in ("NOUN", "PROPN")
                             or "Prs" in toks[i - 1].morph.get("PronType")
                             and toks[i - 1].pos_ == "PRON")):
                    # el demostrativo va delante, no detrás de un sustantivo o
                    # pronombre: "mi mamá esta feliz" = "mi mamá está feliz"
                    es_det = False
                if es_det and sig.pos_ == "ADJ":
                    # "esta feliz noticia" (determinante) / "está feliz." (verbo):
                    # el adjetivo solo hace de determinante si luego viene un sustantivo
                    tras = siguiente(i + 1)
                    if tras is None:
                        continue                    # aún no lo sabemos: esperar
                    es_det = tras is not FIN and tras.pos_ in ("NOUN", "PROPN", "ADJ")
                if es_det:
                    continue
                if w in ("esta", "estas"):
                    # "esta es la mía", "estas son mías": pronombre, sin tilde.
                    # Es el verbo estar si sigue un gerundio, participio, adverbio,
                    # preposición, un adjetivo que no concuerda o se acaba la frase
                    if not fin and not ya_verbo and es_verbo_conjugado(sig):
                        continue
                elif w == "mi":
                    if prev not in PREPOSICIONES:
                        continue                    # "mí" solo va tras preposición
                cambios[i] = tilde
                verbo.add(i)
            elif w == "te" and prev in ANTES_DE_TE_SUSTANTIVO:
                cambios[i] = "té"
            elif w == "de" and prev in CLITICOS and sig is not None and sig is not FIN:
                cambios[i] = "dé"
            elif w == "se" and prev in ANTES_DE_SE and sig is not None:
                if sig is FIN:
                    cambios[i] = "sé"               # "lo sé.", "no sé."
                elif prev == "yo" and "Inf" in sig.morph.get("VerbForm"):
                    cambios[i] = "sé"               # "yo sé cocinar"
                elif (sig.pos_ not in ("VERB", "AUX") and sig.text.lower() not in CLITICOS
                      and sig.text.lower() not in ("lo", "la", "los", "las")):
                    cambios[i] = "sé"               # "no sé qué", "no sé si"
            elif w == "si":
                if sig is FIN and (prev is None or prev in ANTES_DE_SI):
                    cambios[i] = "sí"               # "dijo que sí."
                elif sig is not None and sig is not FIN and sig.text.lower() in (
                        "mismo", "misma", "mismos", "mismas"):
                    cambios[i] = "sí"               # "sí mismo"
            elif w == "mas" and sig is not None:
                cambios[i] = "más"

        res = dobles
        for i, nueva in cambios.items():
            t = toks[i]
            if t.text[0].isupper():
                nueva = nueva[0].upper() + nueva[1:]
            if nueva != t.text:
                res.append((t.idx, t.idx + len(t.text), nueva))
        return sorted(res)

    # ---------- palabras que suenan igual (homófonos) ----------
    def _homofonos(self, toks, siguiente, cambios):
        """Reglas del Diccionario panhispánico de dudas para las confusiones más
        comunes. Escribe en `cambios` (índice -> palabra) y devuelve los cambios
        que ocupan dos palabras ("a ver" -> "haber") como (inicio, fin, texto)."""
        dobles = []

        def part(t):
            if t is None or t is FIN:
                return False
            if "Part" in t.morph.get("VerbForm"):
                return True
            # el analizador a veces no lo marca: participios por su terminación
            return (len(t.text) > 4 and t.text.lower().endswith(("ado", "ido", "ada", "ida"))
                    and t.text.islower() and t.pos_ not in ("ADP", "DET", "PRON", "CCONJ"))

        def inf(t):
            return t is not None and t is not FIN and "Inf" in t.morph.get("VerbForm")

        for i, t in enumerate(toks):
            if i in cambios:
                continue
            w = t.text.lower()
            sig = siguiente(i)
            prev = toks[i - 1].text.lower() if i > 0 else None
            inicio = prev is None or toks[i - 1].is_punct
            sw = sig.text.lower() if sig not in (None, FIN) else None

            if w == "ay" and sig is not None and sig is not FIN:
                # "¡Ay, qué dolor!" (queja) / "que hay en la mesa" (existir)
                queja = inicio and (sw in ("no", "dios", "mi", "caramba", "perdón", "perdon")
                                    or sw in ("que", "qué") and not inf(siguiente(i + 1)))
                if not queja:
                    cambios[i] = "hay"
            elif w == "hay" and prev is not None:
                # "está hay", "por hay" -> "ahí" (lugar)
                if prev in ANTES_DE_AHI or (sig is FIN and toks[i - 1].pos_ in ("VERB", "AUX")
                                            and prev not in ("no", "sí", "si", "ya")):
                    cambios[i] = "ahí"
            elif w == "haber" and sig is not None:
                # "vamos haber" / "haber si viene" -> "a ver"
                if (prev in FORMAS_IR and not part(sig)) or (
                        sw in ("si", "qué", "que", "cómo", "como", "cuándo", "cuando", "dónde",
                               "donde", "quién", "quien", "cuánto", "cuanto")
                        and prev not in ANTES_DE_HABER):
                    cambios[i] = "a ver"
            elif w == "a" and sw == "ver" and part(siguiente(i + 1)):
                # "debe a ver sido" -> "debe haber sido"
                v = toks[i + 1]
                nuevo = "Haber" if t.text[0].isupper() else "haber"
                dobles.append((t.idx, v.idx + len(v.text), nuevo))
                cambios[i + 1] = v.text            # marcar como tratado
            elif w == "echo" and (prev in FORMAS_HABER or prev == "de"):
                cambios[i] = "hecho"               # "he echo" -> "he hecho", "de hecho"
            elif w == "hecho" and prev in CLITICOS and sw == "de":
                cambios[i] = "echo"                # "te hecho de menos" -> "te echo de menos"
            elif w == "valla" and (inicio or prev in ANTES_DE_VAYA):
                cambios[i] = "vaya"                # "que te valla bien" -> "vaya"
            elif w == "vaya" and prev in ("una", "esa", "esta", "otra", "aquella"):
                cambios[i] = "valla"               # "la vaya del jardín" -> "valla"
            elif w == "tubo" and (sw == "que" or prev in ("él", "ella", "usted", "no",
                                                         "se", "lo", "le", "ya", "nunca")):
                cambios[i] = "tuvo"                # "tubo que irse" -> "tuvo que"
            elif w in ("halla", "aya", "alla") and part(sig):
                cambios[i] = "haya"                # "que halla venido" -> "haya"
            elif w == "a" and part(sig) and prev is not None and (
                    toks[i - 1].pos_ in ("NOUN", "PROPN", "PRON")
                    or prev in ("ya", "no", "se", "me", "te", "le", "lo", "la", "nunca")):
                cambios[i] = "ha"                  # "ella a comido" -> "ha comido"
            elif w == "ha" and (inf(sig) or prev in FORMAS_IR):
                cambios[i] = "a"                   # "voy ha comer" -> "a comer"
            elif w == "has" and sw in ("lo", "la", "los", "las", "me", "nos", "le", "les"):
                cambios[i] = "haz"                 # "has lo que quieras" -> "haz"
            elif w == "haz" and part(sig):
                cambios[i] = "has"                 # "haz hecho" -> "has hecho"
            elif w == "ves" and prev in ANTES_DE_VEZ:
                cambios[i] = "vez"                 # "otra ves" -> "otra vez"
        return dobles

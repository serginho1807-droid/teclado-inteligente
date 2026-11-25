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

        res = []
        for i, nueva in cambios.items():
            t = toks[i]
            if t.text[0].isupper():
                nueva = nueva[0].upper() + nueva[1:]
            if nueva != t.text:
                res.append((t.idx, t.idx + len(t.text), nueva))
        return sorted(res)

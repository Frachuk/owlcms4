#!/usr/bin/env python3
"""Busca tokens CSS que un tema USA con var() y nunca DEFINE en ninguna de sus hojas.

Uso:
    python3 tools/theme-check/tokens.py            # los tres temas modern
    python3 tools/theme-check/tokens.py --all      # además, los 4 de fábrica
    python3 tools/theme-check/tokens.py --strict   # fallar también con los heredados
    python3 tools/theme-check/tokens.py public     # un tema puntual

Un `var(--x)` sin `--x` definido y sin fallback hace que la declaración entera
se descarte (el valor computa a "guaranteed-invalid" y la propiedad queda como
si no se hubiera escrito). Es una falla silenciosa: no hay error de sintaxis, el
diff no muestra nada raro y el board simplemente no pinta ese color.

Un token usado y no definido en las hojas del tema puede ser cualquiera de estas
cuatro cosas, y el script las distingue en vez de tirarlas todas al mismo balde:

  RUNTIME    el nombre del token aparece en el código de owlcms (Java o los
             templates Lit), así que se inyecta en runtime como `style` inline y
             no tiene por qué estar en el CSS. Ejemplos reales: --top y --bottom
             (Results.js), --leaderFillerHeight (BaseResults.java),
             --tableFontSize (pushEmSize). Informativo.
  FALLBACK   TODOS los usos pasan un fallback (`var(--x, algo)`), así que la
             degradación está definida a propósito. Informativo.
  HEREDADO   el token también está sin definir en el tema DE FÁBRICA del que este
             tema es fork, y las hojas donde se usa son byte-idénticas o
             derivadas de las de esa base: es un defecto preexistente de owlcms,
             no una regresión nuestra. Informativo por defecto; con --strict
             falla.
  HUERFANO   ninguna de las anteriores. En un tema forkeado eso significa que el
             fork rompió una referencia que en su base SÍ resolvía: es una
             regresión propia. Falla siempre.

Por qué la comparación contra la base y no una lista blanca a mano: las hojas de
los temas de fábrica arrastran tokens de temas viejos (todo el juego
--dark*/--light* que usa top.css se define hoy sólo en
shared/src/test/resources/styles/{TV,samples}/colors.css, no en css/). Una lista
blanca de eso quedaría desactualizada y volvería el gate inservible. Comparar
contra la base hace que el gate mida exactamente lo que puede medir: si el fork
empeoró algo respecto de su punto de partida.

Hallazgo que ya dio este chequeo: --lightGoodTextColor y --lightGoodBackgroundColor
se usan en top.css y topSinclair.css de los SIETE temas de css/ y no se definen en
ninguno. Sale como HEREDADO en los tres temas modern (lo heredamos byte a byte) y
como HUERFANO al correr con --all sobre los de fábrica. Es un defecto preexistente
de owlcms, no de este fork.

Límites conocidos:
  - No interpreta la cascada ni los scopes: un token definido en `.light` y usado
    en un contexto que nunca lleva esa clase cuenta como definido. Este chequeo
    mira el grafo de nombres, no la resolución real (para eso está contrast.py,
    que sí resuelve por modo).
  - No detecta el caso inverso (un token DEFINIDO y nunca usado). Es mucho más
    benigno -- peso muerto, no una propiedad que desaparece -- y da muchos falsos
    positivos, porque los temas definen tokens a propósito para que el usuario
    los pueda pisar desde su propia carpeta de estilos.
  - Los comentarios se ignoran, así que un `var()` comentado no cuenta como uso
    ni una definición comentada como definición. Es lo correcto, y es también lo
    que hace que este chequeo NO vea el daño estructural de un comentario mal
    cerrado: eso lo cubre parse.py.
"""
import argparse
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
CSS_ROOT = REPO_ROOT / "shared" / "src" / "main" / "resources" / "css"

# Mismos pares fork -> base que drift.py y parse.py.
THEMES = {"modern": "nogrid", "modern-public": "public", "modern-video": "transparent"}
TEMAS_FABRICA = ["nogrid", "public", "transparent", "grid"]

# Dónde buscar tokens inyectados en runtime.
FUENTES_RUNTIME = [
    REPO_ROOT / "owlcms" / "src" / "main" / "java",
    REPO_ROOT / "owlcms" / "src" / "main" / "frontend",
]
EXT_RUNTIME = {".java", ".js", ".ts", ".html"}

DEF = re.compile(r"--([A-Za-z0-9_-]+)\s*:")
USE = re.compile(r"var\(\s*--([A-Za-z0-9_-]+)\s*([,)])")


def strip_comments(text):
    """Reemplaza cada comentario de bloque por espacios, respetando que CSS no los anida."""
    out = []
    i, n = 0, len(text)
    while i < n:
        if text.startswith("/*", i):
            j = text.find("*/", i + 2)
            if j == -1:
                out.append(" " * (n - i))
                break
            out.append(" " * (j + 2 - i))
            i = j + 2
        else:
            out.append(text[i])
            i += 1
    return "".join(out)


def escanear_tema(theme_dir):
    """Devuelve (definidos, usos, con_fallback_en_todos_los_usos).

    usos: token -> set de nombres de archivo donde aparece un var() de ese token.
    """
    definidos = set()
    usos = {}
    fallback_si = {}
    for f in sorted(theme_dir.glob("*.css")):
        s = strip_comments(f.read_text())
        definidos |= set(DEF.findall(s))
        for name, nxt in USE.findall(s):
            usos.setdefault(name, set()).add(f.name)
            tiene_fb = nxt == ","
            fallback_si[name] = fallback_si.get(name, True) and tiene_fb
    todos_con_fallback = {n for n, v in fallback_si.items() if v}
    return definidos, usos, todos_con_fallback


def tokens_runtime():
    """Nombres de token que aparecen en el codigo de owlcms (se inyectan en runtime)."""
    encontrados = set()
    fuentes_vistas = 0
    for root in FUENTES_RUNTIME:
        if not root.is_dir():
            continue
        fuentes_vistas += 1
        for f in root.rglob("*"):
            if f.is_file() and f.suffix in EXT_RUNTIME:
                try:
                    encontrados |= set(DEF.findall(f.read_text(errors="ignore")))
                except OSError:
                    continue
    return encontrados, fuentes_vistas


def huerfanos_de(theme_dir):
    """Tokens usados y no definidos en las hojas de esa carpeta (sin clasificar)."""
    definidos, usos, _ = escanear_tema(theme_dir)
    return {n for n in usos if n not in definidos}


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("temas", nargs="*", help="temas a revisar (default: los tres modern)")
    ap.add_argument("--all", action="store_true", help="revisar tambien los 4 temas de fabrica")
    ap.add_argument("--strict", action="store_true",
                    help="fallar tambien con los HEREDADO (defectos preexistentes de owlcms)")
    args = ap.parse_args()

    if not CSS_ROOT.is_dir():
        print(f"No se encontro {CSS_ROOT}. ¿Estas corriendo esto dentro del repo owlcms4?")
        return 2

    runtime, fuentes_vistas = tokens_runtime()
    if fuentes_vistas == 0:
        print("ATENCION: no se encontro el codigo de owlcms (java/frontend), asi que NO se "
              "pueden reconocer los tokens inyectados en runtime. Van a aparecer como HUERFANO.")
    else:
        print(f"{len(runtime)} token(s) detectados en el codigo de owlcms (inyectados en runtime).")

    temas = args.temas or list(THEMES)
    if args.all:
        temas = list(dict.fromkeys(list(temas) + TEMAS_FABRICA))

    total_fail = 0
    for theme in temas:
        theme_dir = CSS_ROOT / theme
        if not theme_dir.is_dir():
            print(f"\n=== {theme} ===\n  ERROR no existe {theme_dir}")
            total_fail += 1
            continue

        definidos, usos, con_fallback = escanear_tema(theme_dir)
        base = THEMES.get(theme)
        base_dir = CSS_ROOT / base if base else None
        base_huerfanos = huerfanos_de(base_dir) if base_dir and base_dir.is_dir() else set()

        sin_definir = sorted(n for n in usos if n not in definidos)
        cat = {"RUNTIME": [], "FALLBACK": [], "HEREDADO": [], "HUERFANO": []}
        for n in sin_definir:
            if n in runtime:
                cat["RUNTIME"].append(n)
            elif n in con_fallback:
                cat["FALLBACK"].append(n)
            elif n in base_huerfanos:
                cat["HEREDADO"].append(n)
            else:
                cat["HUERFANO"].append(n)

        etiqueta = f"base: {base}" if base else "sin base registrada"
        print(f"\n=== {theme} ({etiqueta}) — {len(definidos)} definidos, {len(usos)} usados ===")
        for nombre in ("HUERFANO", "HEREDADO", "FALLBACK", "RUNTIME"):
            for n in cat[nombre]:
                donde = ", ".join(sorted(usos[n]))
                print(f"  {nombre:9} --{n:32} usado en: {donde}")

        fails = len(cat["HUERFANO"]) + (len(cat["HEREDADO"]) if args.strict else 0)
        total_fail += fails
        if not sin_definir:
            print("  OK: todos los tokens usados con var() estan definidos en el tema.")
        elif fails == 0:
            print(f"  OK: 0 HUERFANO ({len(cat['HEREDADO'])} heredados de {base or 'n/a'}, "
                  f"{len(cat['FALLBACK'])} con fallback, {len(cat['RUNTIME'])} de runtime).")

    print(f"\n{total_fail} token(s) contados como falla"
          + (" (--strict: los HEREDADO cuentan)" if args.strict else ""))
    return 1 if total_fail else 0


if __name__ == "__main__":
    sys.exit(main())

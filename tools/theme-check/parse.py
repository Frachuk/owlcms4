#!/usr/bin/env python3
"""Verifica que cada hoja de un tema forkeado siga parseando como su base de fábrica.

Uso:
    python3 tools/theme-check/parse.py                     # los tres temas modern
    python3 tools/theme-check/parse.py modern modern-video # sólo esos
    python3 tools/theme-check/parse.py --all               # además, los 4 de fábrica

Este es el ÚNICO chequeo del proyecto que ve daño estructural INVISIBLE EN EL
`git diff`. El caso real que lo motivó: al tokenizar una línea se le agregó al
final el marcador `/* modern: tokenizado */`, pero esa línea vivía DENTRO de un
comentario de bloque. Los comentarios de CSS no anidan, así que el `*/` del
marcador cerró el comentario grande antes de tiempo; el resto del bloque
comentado pasó a ser CSS vivo, apareció un `*/` huérfano más abajo, y el parser
terminó descartando una regla real. En el diff se ve una línea con un comentario
prolijo agregado. Ni el verificador de contraste ni el detector de drift pueden
ver eso: el primero sólo lee tokens de colors.css, el segundo sólo compara SHA
de la base contra el manifiesto.

Qué chequea, por archivo:

  COMENTARIO   un `/*` que nunca se cierra (el resto del archivo queda comido).
  HUERFANO     un `*/` que aparece FUERA de un comentario. En CSS eso es siempre
               un error: o sobra, o -- el caso peligroso -- hay un `/*` de más
               arriba que se cerró antes de tiempo.
  LLAVES       llaves desbalanceadas: un `}` de más (cierra sin abrir) o un `{`
               que queda abierto al final del archivo.
  REGLAS       el archivo del fork tiene una cantidad de bloques `{...}`
               DISTINTA de la de su archivo base de fábrica.

El chequeo REGLAS es el que atrapa la clase de defecto de arriba, y funciona
porque la disciplina del fork es editar VALORES, no agregar ni quitar reglas:
medido sobre los 49 archivos de los tres temas, todos coinciden exactamente con
su base salvo las dos excepciones declaradas en EXCEPCIONES_REGLAS. Es una lista
blanca a propósito, igual que SIN_BASE_ESPERADOS en drift.py: si algún día hace
falta agregar una regla a otro archivo, se declara acá y queda escrito por qué,
en vez de que el gate se vuelva inservible o mienta.

Los archivos del fork que no tienen base de fábrica (hoy sólo
ncurrentathlete.css) se chequean igual en lo estructural -- comentarios, `*/`
huérfanos y llaves -- y quedan fuera de la comparación de REGLAS, que no tendría
contra qué comparar.

Límites conocidos:
  - el conteo de bloques cuenta TODO bloque `{...}`, incluidos los de las
    at-rules (`@media { ... }` cuenta el @media y además cada regla de adentro).
    Es una medida consistente entre fork y base, que es lo único que importa acá;
    no pretende ser el conteo de reglas del CSSOM.
  - no interpreta strings de CSS: un `/*`, un `*/` o una llave DENTRO de una
    string (p.ej. `content: "*/"`) se contaría como sintaxis. Hoy no pasa en
    ningún archivo de css/, y si algún día pasa el síntoma es un falso positivo
    ruidoso, no un falso negativo silencioso.
  - compara cantidades, no estructura: dos cambios que se compensen (una regla
    agregada y otra borrada) pasarían. Para eso está el `git diff`, que sí ve
    esos cambios; este chequeo cubre justamente lo que el diff NO ve.
"""
import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
CSS_ROOT = REPO_ROOT / "shared" / "src" / "main" / "resources" / "css"

# Mismos pares fork -> base que drift.py.
THEMES = {"modern": "nogrid", "modern-public": "public", "modern-video": "transparent"}
TEMAS_FABRICA = ["nogrid", "public", "transparent", "grid"]

# Archivos que legítimamente NO tienen la misma cantidad de bloques que su base.
# Lista blanca declarada, no inferida: cada entrada dice por qué.
EXCEPCIONES_REGLAS = {
    "colors.css": (
        "es la hoja de paleta del tema: se reescribe entera a propósito (los temas "
        "modern colapsan los bloques de fábrica en `*`/`.dark`/`.light` y agregan un "
        "bloque `.wrapper` y, en modern-public/modern-video, un bloque de overrides "
        "al final). Comparar cantidades acá no diría nada."
    ),
}

# Archivos del fork sin base de fábrica: se chequean estructuralmente pero no
# entran en la comparación de REGLAS. Igual que SIN_BASE_ESPERADOS en drift.py.
SIN_BASE_ESPERADOS = {"ncurrentathlete.css"}


def scan_comments(text):
    """Recorre el texto respetando los comentarios de bloque de CSS (que NO anidan).

    Devuelve (texto_sin_comentarios, huerfanos, sin_cerrar), donde
    `texto_sin_comentarios` tiene la misma longitud que el original (cada
    carácter comentado se reemplaza por un espacio) para que los offsets sigan
    sirviendo para reportar líneas, `huerfanos` es la lista de offsets de los
    `*/` que aparecieron fuera de un comentario, y `sin_cerrar` es el offset del
    `/*` que quedó abierto al final, o None.
    """
    out = []
    huerfanos = []
    sin_cerrar = None
    i, n = 0, len(text)
    while i < n:
        if text.startswith("/*", i):
            j = text.find("*/", i + 2)
            if j == -1:
                sin_cerrar = i
                out.append(" " * (n - i))
                i = n
                break
            out.append(" " * (j + 2 - i))
            i = j + 2
        elif text.startswith("*/", i):
            huerfanos.append(i)
            out.append("  ")
            i += 2
        else:
            out.append(text[i])
            i += 1
    return "".join(out), huerfanos, sin_cerrar


def count_braces(sin_comentarios):
    """Devuelve (bloques, abiertos_al_final, cierres_sobrantes) sobre texto ya sin comentarios."""
    bloques = 0
    depth = 0
    sobrantes = []
    for idx, ch in enumerate(sin_comentarios):
        if ch == "{":
            depth += 1
            bloques += 1
        elif ch == "}":
            if depth == 0:
                sobrantes.append(idx)
            else:
                depth -= 1
    return bloques, depth, sobrantes


def line_of(text, offset):
    return text.count("\n", 0, offset) + 1


def analizar(path):
    """Analiza un archivo. Devuelve (bloques, [problemas]) — problemas es lista de (categoria, detalle)."""
    text = path.read_text()
    limpio, huerfanos, sin_cerrar = scan_comments(text)
    bloques, abiertos, sobrantes = count_braces(limpio)

    problemas = []
    if sin_cerrar is not None:
        problemas.append(("COMENTARIO",
                          f"un `/*` abierto en la linea {line_of(text, sin_cerrar)} nunca se cierra "
                          f"-- todo lo que sigue queda comentado"))
    for off in huerfanos:
        problemas.append(("HUERFANO",
                          f"`*/` fuera de un comentario en la linea {line_of(text, off)} "
                          f"-- revisar si un `/*` de mas arriba se cerro antes de tiempo "
                          f"(p.ej. un marcador `/* modern: ... */` agregado DENTRO de un comentario)"))
    for off in sobrantes:
        problemas.append(("LLAVES",
                          f"`}}` sin `{{` que lo abra, en la linea {line_of(limpio, off)}"))
    if abiertos:
        problemas.append(("LLAVES", f"{abiertos} bloque(s) `{{` quedan abiertos al final del archivo"))
    return bloques, problemas


def revisar_tema(theme, base, fallar_sin_base):
    """Revisa un tema. Devuelve (n_problemas, lineas_de_salida)."""
    theme_dir = CSS_ROOT / theme
    lineas = []
    n_prob = 0

    if not theme_dir.is_dir():
        return 1, [f"  ERROR    no existe la carpeta {theme_dir}"]

    base_dir = CSS_ROOT / base if base else None
    if base and not base_dir.is_dir():
        n_prob += 1
        lineas.append(f"  ERROR    no existe la carpeta base '{base}' -- no se puede comparar REGLAS")
        base_dir = None

    for f in sorted(theme_dir.glob("*.css")):
        bloques, problemas = analizar(f)
        for cat, detalle in problemas:
            n_prob += 1
            lineas.append(f"  {cat:11} {theme}/{f.name}: {detalle}")

        if base_dir is None:
            continue
        bf = base_dir / f.name
        if not bf.is_file():
            if f.name in SIN_BASE_ESPERADOS:
                lineas.append(f"  (ok)        {theme}/{f.name}: {bloques} bloques, sin base de fabrica "
                              f"(declarado en SIN_BASE_ESPERADOS) -- fuera de la comparacion de REGLAS")
            elif fallar_sin_base:
                n_prob += 1
                lineas.append(f"  SIN BASE    {theme}/{f.name}: no hay {base}/{f.name} y no esta en "
                              f"SIN_BASE_ESPERADOS -- revisar (drift.py cubre este caso en detalle)")
            continue

        if f.name in EXCEPCIONES_REGLAS:
            base_bloques, _ = analizar(bf)
            lineas.append(f"  (excepcion) {theme}/{f.name}: {bloques} bloques contra {base_bloques} de "
                          f"{base}/{f.name} -- {EXCEPCIONES_REGLAS[f.name]}")
            continue

        base_bloques, base_problemas = analizar(bf)
        if base_problemas:
            # La base de fábrica está rota: no es culpa nuestra, pero hay que decirlo,
            # porque invalida la comparación de este archivo.
            for cat, detalle in base_problemas:
                lineas.append(f"  (base)      {base}/{f.name}: {cat} -- {detalle}")
        if bloques != base_bloques:
            n_prob += 1
            lineas.append(f"  REGLAS      {theme}/{f.name}: {bloques} bloques contra {base_bloques} de "
                          f"{base}/{f.name} ({bloques - base_bloques:+d}) -- el fork edita valores, no "
                          f"agrega ni quita reglas; si el cambio es intencional, declararlo en "
                          f"EXCEPCIONES_REGLAS")
    return n_prob, lineas


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("temas", nargs="*", help="temas a revisar (default: los tres modern)")
    ap.add_argument("--all", action="store_true",
                    help="revisar tambien los 4 temas de fabrica (solo chequeos estructurales)")
    args = ap.parse_args()

    if not CSS_ROOT.is_dir():
        print(f"No se encontro {CSS_ROOT}. ¿Estas corriendo esto dentro del repo owlcms4?")
        return 2

    temas = args.temas or list(THEMES)
    if args.all:
        temas = list(dict.fromkeys(list(temas) + TEMAS_FABRICA))

    total_prob = 0
    total_files = 0
    for theme in temas:
        base = THEMES.get(theme)
        n_files = len(list((CSS_ROOT / theme).glob("*.css"))) if (CSS_ROOT / theme).is_dir() else 0
        total_files += n_files
        etiqueta = f"base: {base}" if base else "sin base registrada (solo chequeos estructurales)"
        print(f"\n=== {theme} ({etiqueta}) — {n_files} archivos ===")
        n_prob, lineas = revisar_tema(theme, base, fallar_sin_base=bool(base))
        total_prob += n_prob
        if lineas:
            print("\n".join(lineas))
        if n_prob == 0:
            print("  OK: comentarios balanceados, sin `*/` huerfanos, llaves balanceadas"
                  + (", conteo de bloques igual al de la base." if base else "."))

    print(f"\n{total_files} archivos · {total_prob} problema(s)")
    return 1 if total_prob else 0


if __name__ == "__main__":
    sys.exit(main())

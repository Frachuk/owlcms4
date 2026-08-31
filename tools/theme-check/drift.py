#!/usr/bin/env python3
"""Detecta cuándo un tema de fábrica cambió respecto del último sync de su fork.

Uso:
    python3 tools/theme-check/drift.py            # compara contra el manifiesto
    python3 tools/theme-check/drift.py --update    # registra el estado actual como nuevo sync

Este script mitiga el riesgo principal de la familia de temas "modern": tres
carpetas (modern, modern-public, modern-video) son forks de tres temas de
fábrica (nogrid, public, transparent respectivamente). Si la carpeta de
fábrica cambia -- o desaparece, o se renombra -- y nadie porta el cambio al
fork correspondiente, el tema forkeado queda desactualizado en silencio.

El manifiesto (theme-sync.json) registra, para cada archivo de cada carpeta
de fábrica, el SHA de blob de git de su contenido en el momento del último
`--update`. Correr sin argumentos recalcula los SHA actuales y compara la
UNIÓN de nombres de archivo conocidos -- los que aparecen ahora en la base y
los que estaban registrados en el manifiesto -- para que un archivo borrado o
renombrado no desaparezca de la comparación simplemente por no aparecer en el
`glob` actual. Y un archivo que SÍ aparece en el `glob` pero cuyo contenido no
se puede leer (symlink roto, sin permisos) se registra con SHA nulo y se
reporta como ILEGIBLE, para que tampoco se escape por el otro lado:

  DRIFT    un archivo de la base que ya existía en el último sync y sigue
           existiendo ahora cambió de contenido -> portar el cambio al
           archivo correspondiente del fork.
  NUEVO    un archivo que existe en la base ahora pero no estaba registrado
           en el último sync -> decidir si el fork lo necesita.
  FALTA    un archivo de la base que existe ahora mismo pero el fork no
           tiene.
  PERDIDA  un archivo que SÍ estaba registrado en el último sync y que ya no
           aparece en la carpeta base (borrado o renombrado) -> revisar si el
           fork todavía necesita ese contenido.
  ILEGIBLE un archivo que SÍ aparece en la carpeta base pero cuyo contenido
           no se puede leer (symlink roto, sin permisos de lectura) -> no se
           puede comparar nada de él, así que se reporta explícitamente.
           IMPORTANTE: esta categoría no depende de que el archivo estuviera
           registrado antes. Un archivo ilegible DESDE QUE APARECE (p.ej. un
           symlink roto nuevo) no cae en PERDIDA -- PERDIDA sólo mira el
           manifiesto -- y sin esta categoría saldría con código 0 y sin una
           sola mención.
  BASE     la carpeta base entera de un tema no existe (renombrada o
           borrada) -> revisar el tema completo; implica PERDIDA para todos
           sus archivos registrados.

Todas estas categorías hacen salir con código 1. En cada caso el archivo del
fork a revisar es `css/<tema>/<mismo nombre>`.

Dos límites de la detección, explícitos para que nadie confíe de más en ella:

  - "sin permisos de lectura" NO se detecta corriendo como root: root saltea
    los chequeos de permisos del filesystem, así que un archivo con modo 000
    se lee sin problema y no dispara ILEGIBLE ni ninguna otra categoría. Como
    gate esto sólo importa si alguien corre el script con privilegios (CI en
    un contenedor, por ejemplo): el resultado puede ser un exit 0 que un
    usuario normal no obtendría.

  - una entrada del manifiesto para un tema que NO está en la constante
    THEMES se IGNORA EN SILENCIO: do_check() itera sobre el snapshot actual,
    que se construye a partir de THEMES, así que un tema que se saca de esa
    constante (o que se escribe mal en el manifiesto) deja de compararse sin
    ningún aviso. Si algún día se renombra o se retira un tema, hay que
    limpiar el manifiesto a mano con --update.

Además, sólo a título informativo (no afecta el código de salida): el
manifiesto también guarda el SHA del archivo *del fork* en el momento del
sync, así que se puede avisar qué archivos del fork fueron editados desde
entonces (EDITADO). No es drift -- el fork difiere de la base a propósito --
pero da visibilidad de qué se tocó desde el último punto de referencia común
(por ejemplo, cambios ya portados que todavía no se confirmaron con
--update).

Un archivo puede existir en el fork sin tener ningún archivo base
equivalente, ni ahora ni en el último sync. El único caso legítimo conocido
es ncurrentathlete.css (NCurrentAthlete.js:60 lo carga, pero ningún tema de
fábrica lo provee -- lo agregamos nosotros al armar el fork), y está
declarado explícitamente en SIN_BASE_ESPERADOS más abajo -- a propósito una
lista blanca, no una inferencia por ausencia, para que un huérfano
inesperado (por ejemplo, el archivo base real fue borrado o renombrado y
"parece" no tener base) no se confunda con este caso intencional. Un archivo
fork-only que NO está en esa lista se reporta como SIN BASE (inesperado) y
también hace salir con código 1.

Los archivos sueltos en la raíz de css/ (hoy sólo decision-lights.css) NO
entran en esta comparación, y es intencional: no pertenecen a ningún tema en
particular. DecisionElement.js:109 y PassiveDecisionElement.js:33 fijan
`stylesDir = "css"` (la raíz, no un tema) para cargarlos, y son compartidos
por igual por todos los temas -- de fábrica y forkeados. CSS_ROOT sólo se
recorre a través de las subcarpetas de THEMES (los `base_dir`/`fork_dir` de
cada tema), así que el glob nunca llega a la raíz de css/; si aparece un
archivo nuevo ahí (como pasó en beta10), este script no lo va a ver, y es lo
esperado -- no un descuido.

Límite conocido de `--update`: graba el estado actual como nuevo punto de
referencia de forma incondicional. No corre la comparación antes de
escribir, así que si hay DRIFT/NUEVO/FALTA/PERDIDA/BASE sin resolver y se
corre `--update` de todos modos, ese estado pendiente queda aceptado como la
nueva línea de base sin ningún aviso. Correr sin argumentos antes de
`--update` sigue siendo responsabilidad de quien lo opera.
"""
import argparse
import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
CSS_ROOT = REPO_ROOT / "shared" / "src" / "main" / "resources" / "css"
MANIFEST = Path(__file__).parent / "theme-sync.json"
THEMES = {"modern": "nogrid", "modern-public": "public", "modern-video": "transparent"}

# Lista blanca de archivos que legítimamente sólo existen en el fork, sin
# ningún archivo base de fábrica equivalente -- ver docstring del módulo.
# Si el fork tiene un archivo fuera de esta lista sin base conocida (ni
# ahora ni en el manifiesto), se reporta como anomalía, no como intencional.
SIN_BASE_ESPERADOS = {"ncurrentathlete.css"}


def blob_sha(path: Path):
    """SHA del blob de git para el contenido actual del archivo en disco, o None si no se puede leer."""
    if not path.is_file():
        return None
    try:
        out = subprocess.run(
            ["git", "hash-object", str(path)],
            capture_output=True, text=True, check=True, cwd=REPO_ROOT,
        )
        return out.stdout.strip()
    except subprocess.CalledProcessError:
        # Existe pero git no pudo leerlo (p.ej. sin permisos de lectura).
        return None


def snapshot():
    """Estado actual: tema -> {base, base_dir_exists, files: {archivo: {base_sha, fork_sha}}, fork_names: [...]}.

    Nota: a diferencia de una versión anterior de este script, un tema SIEMPRE
    aparece en el resultado aunque su carpeta base no exista -- de lo
    contrario la comparación en do_check() no tendría cómo enterarse de que
    la carpeta base entera desapareció (ver categoría BASE).
    """
    state = {}
    for theme, base in THEMES.items():
        base_dir = CSS_ROOT / base
        fork_dir = CSS_ROOT / theme
        base_dir_exists = base_dir.is_dir()

        files = {}
        if base_dir_exists:
            for f in sorted(base_dir.glob("*.css")):
                # base_sha None = el archivo aparece en la carpeta pero su contenido no se
                # puede leer (symlink roto, sin permisos). Se REGISTRA igual, con None, para
                # que entre en la comparación de do_check() como ILEGIBLE. Descartarlo acá
                # (lo que hacía una versión anterior) hacía invisible al caso peor: un
                # archivo ilegible desde que aparece, que nunca estuvo en el manifiesto y por
                # lo tanto tampoco puede caer en PERDIDA -> exit 0 sin una sola mención.
                files[f.name] = {"base_sha": blob_sha(f), "fork_sha": blob_sha(fork_dir / f.name)}

        fork_names = sorted(p.name for p in fork_dir.glob("*.css")) if fork_dir.is_dir() else []

        state[theme] = {
            "base": base,
            "base_dir_exists": base_dir_exists,
            "files": files,
            "fork_names": fork_names,
        }
    return state


def classify_fork_only(fork_names, known_names):
    """Separa los archivos que sólo existen en el fork (sin base ahora ni en el manifiesto)
    entre los declarados como excepción legítima (SIN_BASE_ESPERADOS) y el resto."""
    unaccounted = [n for n in fork_names if n not in known_names]
    esperado = sorted(n for n in unaccounted if n in SIN_BASE_ESPERADOS)
    inesperado = sorted(n for n in unaccounted if n not in SIN_BASE_ESPERADOS)
    return esperado, inesperado


def load_manifest():
    """Lee y parsea el manifiesto. Devuelve (datos, None) o (None, mensaje_de_error)."""
    try:
        text = MANIFEST.read_text()
    except OSError as e:
        return None, f"No se pudo leer el manifiesto en {MANIFEST}: {e}"
    try:
        return json.loads(text), None
    except json.JSONDecodeError as e:
        return None, f"El manifiesto en {MANIFEST} no es JSON válido: {e}"


def do_update(current):
    # Un archivo con base_sha None es ilegible: no hay contenido que registrar como punto
    # de referencia, así que NO entra en el manifiesto (grabar un null lo volvería
    # indistinguible de un archivo legítimo y la comparación siguiente lo daría por bueno:
    # None != None es False). Queda fuera del manifiesto y se avisa acá abajo, de modo que
    # la corrida siguiente lo vuelva a ver como ILEGIBLE en vez de darlo por sincronizado.
    to_write = {
        theme: {
            "base": d["base"],
            "files": {n: v for n, v in d["files"].items() if v["base_sha"] is not None},
        }
        for theme, d in current.items()
    }
    MANIFEST.write_text(json.dumps(to_write, indent=2, sort_keys=True) + "\n")
    total = sum(len(v["files"]) for v in to_write.values())
    print(f"Sync registrado: {len(current)} temas, {total} archivos base.")

    for theme, data in current.items():
        ilegibles = sorted(n for n, v in data["files"].items() if v["base_sha"] is None)
        if ilegibles:
            print(f"  ATENCIÓN {theme}: {len(ilegibles)} archivo(s) de la base "
                  f"'{data['base']}' aparecen en la carpeta pero no se pueden leer "
                  f"(¿symlink roto, sin permisos?): {', '.join(ilegibles)} "
                  f"-- NO se registraron en el manifiesto; se van a seguir reportando "
                  f"como ILEGIBLE hasta que se arreglen.")
        if not data["base_dir_exists"]:
            print(f"  ATENCIÓN: la carpeta base de {theme} ('{data['base']}') no existe -- "
                  f"no se registró ningún archivo base para este tema.")
            continue
        esperado, inesperado = classify_fork_only(data["fork_names"], set(data["files"]))
        if esperado:
            print(f"  {theme}: {len(esperado)} archivo(s) sin base de fábrica esperado "
                  f"(excluido de la comparación): {', '.join(esperado)}")
        if inesperado:
            print(f"  ATENCIÓN {theme}: {len(inesperado)} archivo(s) del fork sin base conocida "
                  f"y fuera de SIN_BASE_ESPERADOS: {', '.join(inesperado)} "
                  f"-- revisar antes de confiar en este sync.")
    return 0


def do_check(current, recorded):
    any_drift = False

    for theme, data in current.items():
        base = data["base"]
        base_dir_exists = data["base_dir_exists"]
        current_files = data["files"]
        rec_files = recorded.get(theme, {}).get("files", {})

        drift, nuevo, falta, editado, perdida, ilegible = [], [], [], [], [], []

        for name in sorted(set(current_files) | set(rec_files)):
            cur = current_files.get(name)
            rec = rec_files.get(name)

            if cur is None:
                # Estaba registrado y ya no aparece en la carpeta base: borrado o renombrado.
                perdida.append(name)
                continue

            if cur["base_sha"] is None:
                # Aparece en la carpeta base pero su contenido no se puede leer. No hay SHA
                # con el que comparar, así que no tiene sentido clasificarlo como NUEVO ni
                # como DRIFT: se reporta como ILEGIBLE y se sigue. Vale igual si nunca
                # estuvo registrado (rec is None), que es justamente el caso que antes
                # quedaba invisible.
                ilegible.append((name, rec is not None))
                continue

            if rec is None:
                nuevo.append(name)
            elif rec.get("base_sha") != cur["base_sha"]:
                drift.append((name, rec.get("base_sha"), cur["base_sha"]))

            if cur["fork_sha"] is None:
                falta.append(name)
            elif rec is not None and rec.get("fork_sha") not in (None, cur["fork_sha"]):
                editado.append(name)

        known_names = set(current_files) | set(rec_files)
        esperado, inesperado = classify_fork_only(data["fork_names"], known_names)

        theme_failed = bool(drift or nuevo or falta or perdida or ilegible or inesperado
                            or not base_dir_exists)
        if theme_failed:
            any_drift = True

        if not (theme_failed or editado or esperado):
            continue  # nada que informar de este tema

        print(f"\n=== {theme} (base: {base}) ===")
        if not base_dir_exists:
            print(f"  BASE     la carpeta base '{base}' no existe -> ¿se renombró o se borró? "
                  f"revisar el tema {theme} completo")
        for name in perdida:
            print(f"  PERDIDA  {base}/{name} ya no aparece en la carpeta base (¿borrado o "
                  f"renombrado?)  ->  revisar si {theme}/{name} sigue vigente")
        for name, was_recorded in ilegible:
            visto = "ya estaba registrado en el último sync" if was_recorded \
                    else "NUNCA estuvo registrado: apareció ya ilegible"
            print(f"  ILEGIBLE {base}/{name} aparece en la carpeta base pero no se puede leer "
                  f"(¿symlink roto, sin permisos de lectura?; {visto})  ->  arreglar la base "
                  f"antes de poder comparar {theme}/{name}")
        for name, old, new in drift:
            old_short = old[:8] if old else "????????"
            print(f"  DRIFT    {base}/{name} cambió ({old_short} -> {new[:8]})  ->  revisar {theme}/{name}")
        for name in nuevo:
            print(f"  NUEVO    {base}/{name} no existía en el último sync  ->  revisar si {theme}/{name} lo necesita")
        for name in falta:
            print(f"  FALTA    {theme}/{name} no existe (la base {base}/{name} sí)")
        for name in editado:
            print(f"  EDITADO  {theme}/{name} cambió desde el último sync (informativo, no es drift)")
        if esperado:
            print(f"  (sin base de fábrica esperado, excluido de la comparación: {', '.join(esperado)})")
        for name in inesperado:
            print(f"  SIN BASE (inesperado)  {theme}/{name} no tiene archivo base conocido y no está "
                  f"en SIN_BASE_ESPERADOS  ->  revisar si es un huérfano (¿base borrada/renombrada?) "
                  f"o agregarlo a la lista si es intencional")

    if not any_drift:
        print("Sin drift: los temas forkeados están al día con sus bases.")
        return 0

    print("\nPortá los cambios señalados (DRIFT/NUEVO/FALTA/PERDIDA/ILEGIBLE/BASE/SIN BASE) "
          "al fork correspondiente y después corré con --update.")
    return 1


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--update", action="store_true",
                     help="registrar el estado actual como nuevo punto de sync")
    args = ap.parse_args()

    if not CSS_ROOT.is_dir():
        print(f"No se encontró {CSS_ROOT}. ¿Estás corriendo esto dentro del repo owlcms4?")
        return 2

    current = snapshot()

    if args.update:
        return do_update(current)

    if not MANIFEST.exists():
        print(f"No hay manifiesto en {MANIFEST}.")
        print("Ejecutá con --update para registrar el punto de sync inicial.")
        return 2

    recorded, err = load_manifest()
    if err:
        print(err)
        print("Corré con --update para regenerar el manifiesto desde el estado actual "
              "(revisá antes qué pasó -- esto no reemplaza esa revisión).")
        return 2

    return do_check(current, recorded)


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""Verifica contraste WCAG de los pares texto/fondo de un colors.css de owlcms."""
import argparse, json, re, sys
from pathlib import Path

# Los 148 nombres de color estándar de CSS Color Module Level 3/4 (los 147 de
# Level 3 más "rebeccapurple", que agregó Level 4), más "transparent". El
# lookup es insensible a mayúsculas: el valor crudo se
# normaliza con .lower() antes de buscar acá, así que las claves quedan en
# minúscula (esto ya cubre variantes como "darkOrange" tal como aparece en
# public/colors.css y transparent/colors.css).
NAMED = {
    "aliceblue": "#f0f8ff", "antiquewhite": "#faebd7", "aqua": "#00ffff",
    "aquamarine": "#7fffd4", "azure": "#f0ffff", "beige": "#f5f5dc",
    "bisque": "#ffe4c4", "black": "#000000", "blanchedalmond": "#ffebcd",
    "blue": "#0000ff", "blueviolet": "#8a2be2", "brown": "#a52a2a",
    "burlywood": "#deb887", "cadetblue": "#5f9ea0", "chartreuse": "#7fff00",
    "chocolate": "#d2691e", "coral": "#ff7f50", "cornflowerblue": "#6495ed",
    "cornsilk": "#fff8dc", "crimson": "#dc143c", "cyan": "#00ffff",
    "darkblue": "#00008b", "darkcyan": "#008b8b", "darkgoldenrod": "#b8860b",
    "darkgray": "#a9a9a9", "darkgreen": "#006400", "darkgrey": "#a9a9a9",
    "darkkhaki": "#bdb76b", "darkmagenta": "#8b008b", "darkolivegreen": "#556b2f",
    "darkorange": "#ff8c00", "darkorchid": "#9932cc", "darkred": "#8b0000",
    "darksalmon": "#e9967a", "darkseagreen": "#8fbc8f", "darkslateblue": "#483d8b",
    "darkslategray": "#2f4f4f", "darkslategrey": "#2f4f4f", "darkturquoise": "#00ced1",
    "darkviolet": "#9400d3", "deeppink": "#ff1493", "deepskyblue": "#00bfff",
    "dimgray": "#696969", "dimgrey": "#696969", "dodgerblue": "#1e90ff",
    "firebrick": "#b22222", "floralwhite": "#fffaf0", "forestgreen": "#228b22",
    "fuchsia": "#ff00ff", "gainsboro": "#dcdcdc", "ghostwhite": "#f8f8ff",
    "gold": "#ffd700", "goldenrod": "#daa520", "gray": "#808080",
    "grey": "#808080", "green": "#008000", "greenyellow": "#adff2f",
    "honeydew": "#f0fff0", "hotpink": "#ff69b4", "indianred": "#cd5c5c",
    "indigo": "#4b0082", "ivory": "#fffff0", "khaki": "#f0e68c",
    "lavender": "#e6e6fa", "lavenderblush": "#fff0f5", "lawngreen": "#7cfc00",
    "lemonchiffon": "#fffacd", "lightblue": "#add8e6", "lightcoral": "#f08080",
    "lightcyan": "#e0ffff", "lightgoldenrodyellow": "#fafad2", "lightgray": "#d3d3d3",
    "lightgreen": "#90ee90", "lightgrey": "#d3d3d3", "lightpink": "#ffb6c1",
    "lightsalmon": "#ffa07a", "lightseagreen": "#20b2aa", "lightskyblue": "#87cefa",
    "lightslategray": "#778899", "lightslategrey": "#778899", "lightsteelblue": "#b0c4de",
    "lightyellow": "#ffffe0", "lime": "#00ff00", "limegreen": "#32cd32",
    "linen": "#faf0e6", "magenta": "#ff00ff", "maroon": "#800000",
    "mediumaquamarine": "#66cdaa", "mediumblue": "#0000cd", "mediumorchid": "#ba55d3",
    "mediumpurple": "#9370db", "mediumseagreen": "#3cb371", "mediumslateblue": "#7b68ee",
    "mediumspringgreen": "#00fa9a", "mediumturquoise": "#48d1cc", "mediumvioletred": "#c71585",
    "midnightblue": "#191970", "mintcream": "#f5fffa", "mistyrose": "#ffe4e1",
    "moccasin": "#ffe4b5", "navajowhite": "#ffdead", "navy": "#000080",
    "oldlace": "#fdf5e6", "olive": "#808000", "olivedrab": "#6b8e23",
    "orange": "#ffa500", "orangered": "#ff4500", "orchid": "#da70d6",
    "palegoldenrod": "#eee8aa", "palegreen": "#98fb98", "paleturquoise": "#afeeee",
    "palevioletred": "#db7093", "papayawhip": "#ffefd5", "peachpuff": "#ffdab9",
    "peru": "#cd853f", "pink": "#ffc0cb", "plum": "#dda0dd",
    "powderblue": "#b0e0e6", "purple": "#800080", "rebeccapurple": "#663399",
    "red": "#ff0000", "rosybrown": "#bc8f8f", "royalblue": "#4169e1",
    "saddlebrown": "#8b4513", "salmon": "#fa8072", "sandybrown": "#f4a460",
    "seagreen": "#2e8b57", "seashell": "#fff5ee", "sienna": "#a0522d",
    "silver": "#c0c0c0", "skyblue": "#87ceeb", "slateblue": "#6a5acd",
    "slategray": "#708090", "slategrey": "#708090", "snow": "#fffafa",
    "springgreen": "#00ff7f", "steelblue": "#4682b4", "tan": "#d2b48c",
    "teal": "#008080", "thistle": "#d8bfd8", "tomato": "#ff6347",
    "turquoise": "#40e0d0", "violet": "#ee82ee", "wheat": "#f5deb3",
    "white": "#ffffff", "whitesmoke": "#f5f5f5", "yellow": "#ffff00",
    "yellowgreen": "#9acd32", "transparent": None,
}

DECL = re.compile(r"--([A-Za-z0-9_-]+)\s*:\s*([^;]+);")

# Estados posibles al resolver un token a color.
RESOLVED = "RESOLVED"
ABSENT = "ABSENT"
TRANSPARENT = "TRANSPARENT"
UNRESOLVED = "UNRESOLVED"


def parse_blocks(text):
    """Devuelve (globales, dark, light): nombre de token -> valor crudo.

    Los temas de owlcms declaran los tokens comunes en un bloque `*` o `.wrapper` y
    los de tabla dentro de `.dark` y `.light`. `.wrapper` cuenta como scope global:
    es el div raíz que los templates Lit renderizan, así que un token declarado ahí
    se hereda a todo el board igual que uno declarado en `*`. Es donde
    `css/public`, `css/transparent` y los tres temas `modern` declaran
    `--videoHeaderBackgroundColor` / `--videoHeaderTextColor`; sin reconocerlo, el
    gate no podría ver esos tokens.

    El selector se compara por igualdad exacta (no por prefijo) para que un futuro
    `.dark-alt` no caiga por error en el scope de `.dark`, y para que un ejemplo por
    plataforma como `.wrapper.JQ` (más específico, no es el default del tema) quede
    deliberadamente fuera del gate.

    LIMITACIÓN: `*` y `.wrapper` se mezclan en un solo diccionario plano, así que
    entre ellos gana el ÚLTIMO en orden de archivo, no el de mayor especificidad.
    En la práctica no hay colisión (ningún token de los temas está declarado en los
    dos scopes), pero si algún día la hubiera, el resultado del gate podría no
    coincidir con lo que resuelve el navegador.
    """
    globals_, dark, light = {}, {}, {}
    for selector, body in re.findall(r"([^{}]+)\{([^{}]*)\}", text):
        sel = selector.strip().split("\n")[-1].strip()
        target = globals_
        if sel == ".dark":
            target = dark
        elif sel == ".light":
            target = light
        elif not (sel == "*" or sel == ".wrapper" or sel.startswith(":root")):
            continue
        for name, value in DECL.findall(body):
            target[name] = value.strip()
    return globals_, dark, light


def find_var_call(text):
    """Busca la primera llamada `var(...)` en `text` y la separa en
    (nombre_del_token, fallback_o_None). Devuelve None si no hay var(...).

    Soporta paréntesis balanceados dentro del fallback (p.ej.
    `var(--x, rgb(1,2,3))`), partiendo en la primera coma de nivel superior.
    """
    m = re.search(r"var\(", text)
    if not m:
        return None
    start = m.end()
    depth, i = 1, start
    while i < len(text) and depth > 0:
        if text[i] == "(":
            depth += 1
        elif text[i] == ")":
            depth -= 1
        i += 1
    if depth != 0:
        return None
    inner = text[start:i - 1]
    depth, comma_at = 0, None
    for j, ch in enumerate(inner):
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        elif ch == "," and depth == 0:
            comma_at = j
            break
    if comma_at is None:
        token_part, fallback = inner, None
    else:
        token_part, fallback = inner[:comma_at], inner[comma_at + 1:].strip()
    tm = re.match(r"\s*--([A-Za-z0-9_-]+)\s*$", token_part)
    if not tm:
        return None
    return tm.group(1), fallback


def resolve_literal(value, raw):
    """Interpreta un valor ya sin var() (nombre de color u hex)."""
    low = value.strip().lower()
    if low in NAMED:
        hexval = NAMED[low]
        return (TRANSPARENT, None, raw) if hexval is None else (RESOLVED, hexval, raw)
    if low.startswith("#"):
        h = low[1:]
        if len(h) == 3:
            h = "".join(c * 2 for c in h)
        if len(h) == 6 and re.fullmatch(r"[0-9a-f]{6}", h):
            return (RESOLVED, "#" + h, raw)
    return (UNRESOLVED, None, raw)


def resolve(name, scope, globals_, seen=None):
    """Resuelve un token a color, siguiendo cadenas de var() (con fallback).

    Devuelve (status, hexcolor_o_None, raw_o_None):
      RESOLVED     -> se pudo interpretar como color hex utilizable.
      ABSENT       -> el token no está definido en este modo (no es un error;
                      el tema simplemente no lo declara).
      TRANSPARENT  -> el token vale `transparent` (contraste no calculable,
                      caso legítimo p.ej. sobre un overlay de video).
      UNRESOLVED   -> el token está definido pero el valor no se pudo
                      interpretar (nombre de color desconocido, rgb()/hsl(),
                      ciclo de var(), etc). Este es el caso peligroso: hay un
                      valor real y no lo entendimos, así que no debe pasar
                      en silencio.
    """
    seen = seen or set()
    if name in seen:
        return (UNRESOLVED, None, None)
    seen.add(name)
    raw = scope.get(name, globals_.get(name))
    if raw is None:
        return (ABSENT, None, None)
    raw = raw.strip()

    call = find_var_call(raw)
    if call:
        ref_name, fallback = call
        if ref_name in scope or ref_name in globals_:
            return resolve(ref_name, scope, globals_, seen)
        if fallback is not None:
            return resolve_literal(fallback, raw)
        return (ABSENT, None, raw)

    return resolve_literal(raw, raw)


def luminance(hexcolor):
    r, g, b = (int(hexcolor[i:i + 2], 16) / 255 for i in (1, 3, 5))
    def lin(c):
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    return 0.2126 * lin(r) + 0.7152 * lin(g) + 0.0722 * lin(b)


def ratio(fg, bg):
    l1, l2 = sorted((luminance(fg), luminance(bg)), reverse=True)
    return (l1 + 0.05) / (l2 + 0.05)


def display(status, hexval, raw):
    """Texto legible para un lado (fg o bg) de una fila, en vez de imprimir None."""
    if status == RESOLVED:
        return hexval
    if status == TRANSPARENT:
        return "transparent"
    if status == ABSENT:
        return "(ausente)"
    return raw if raw else "(valor no interpretable)"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("colors_css")
    ap.add_argument("--mode", choices=["dark", "light", "both"], default="both")
    ap.add_argument("--pairs", default=str(Path(__file__).parent / "pairs.json"))
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    text = Path(args.colors_css).read_text()
    globals_, dark, light = parse_blocks(text)
    pairs = json.loads(Path(args.pairs).read_text())["pairs"]

    modes = ["dark", "light"] if args.mode == "both" else [args.mode]
    results, failed = [], False

    for mode in modes:
        scope = dark if mode == "dark" else light
        for p in pairs:
            fg_status, fg_hex, fg_raw = resolve(p["fg"].lstrip("-"), scope, globals_)
            bg_status, bg_hex, bg_raw = resolve(p["bg"].lstrip("-"), scope, globals_)

            r = None
            if fg_status == UNRESOLVED or bg_status == UNRESOLVED:
                # Hay un valor real que no supimos interpretar: fallar es
                # obligatorio, callarse sería lo peor que podría hacer el gate.
                status = "UNRESOLVED"
                failed = True
            elif fg_status == TRANSPARENT or bg_status == TRANSPARENT:
                status = "SKIP (transparente)"
            elif fg_status == ABSENT or bg_status == ABSENT:
                status = "SKIP (ausente)"
            else:
                r = ratio(fg_hex, bg_hex)
                status = "PASS" if r >= p["min"] else "FAIL"
                if status == "FAIL":
                    failed = True

            results.append({
                "mode": mode, "label": p["label"], "fg": p["fg"], "bg": p["bg"],
                "fg_status": fg_status, "bg_status": bg_status,
                "hex_fg": fg_hex, "hex_bg": bg_hex,
                "raw_fg": fg_raw, "raw_bg": bg_raw,
                "ratio": round(r, 2) if r else None, "min": p["min"],
                "status": status,
            })

    if args.json:
        print(json.dumps(results, indent=2, ensure_ascii=False))
    else:
        for x in results:
            r = f"{x['ratio']:.2f}" if x["ratio"] else "  n/a"
            disp_fg = display(x["fg_status"], x["hex_fg"], x["raw_fg"])
            disp_bg = display(x["bg_status"], x["hex_bg"], x["raw_bg"])
            print(f"{x['status']:19} [{x['mode']:5}] {x['label']:18} "
                  f"ratio={r} min={x['min']}  {disp_fg} on {disp_bg}")
        n_fail = sum(1 for x in results if x["status"] == "FAIL")
        n_unresolved = sum(1 for x in results if x["status"] == "UNRESOLVED")
        n_skip = sum(1 for x in results if x["status"].startswith("SKIP"))
        print(f"\n{len(results)} pares · {n_fail} FAIL · {n_unresolved} UNRESOLVED · {n_skip} SKIP")

    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())

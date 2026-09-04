# Theme Check — herramientas y receta de port de la familia de temas `modern`

Este directorio contiene los cuatro chequeos que sostienen la familia de temas
`modern` de owlcms, y la receta para portarle un cambio del upstream.

## Contexto en una pantalla

`shared/src/main/resources/css/` tiene siete carpetas de temas. Cuatro son de
**fábrica** (upstream de owlcms) y tres son **forks** nuestros:

| fork            | base de fábrica | rol                                        |
|-----------------|-----------------|--------------------------------------------|
| `modern`        | `nogrid`        | tablero normal (sala, pantallas del evento) |
| `modern-public` | `public`        | pantalla pública / streaming               |
| `modern-video`  | `transparent`   | overlay para OBS (página transparente)     |

Los otros tres de fábrica (`nogrid`, `public`, `transparent`) y `grid` **no se
tocan nunca**: la familia `modern` es una copia paralela, no un parche encima.

El riesgo estructural del diseño es uno solo: si el upstream cambia
`nogrid/results.css` y nadie porta el cambio a `modern/results.css`, el fork se
queda viejo **en silencio**. Todo lo que hay acá existe para que eso no pase
callado y para que portar el cambio sea barato.

---

## Las cuatro herramientas

Todas anclan sus rutas al raíz del repo (`Path(__file__).resolve().parents[2]`),
así que se corren desde donde sea. Todas salen con **0** si está todo bien y **1**
si hay algo que revisar (2 si no pudieron ni empezar).

### `drift.py` — ¿cambió la base de fábrica?

```bash
python3 tools/theme-check/drift.py            # comparar contra el manifiesto
python3 tools/theme-check/drift.py --update   # registrar el estado actual como nuevo sync
```

Compara el SHA de blob de git de cada archivo de las tres carpetas base contra
`theme-sync.json`, el manifiesto que guarda el estado del último sync. Categorías:
`DRIFT` (la base cambió), `NUEVO`, `FALTA`, `PERDIDA`, `ILEGIBLE`, `BASE`,
`SIN BASE`, y `EDITADO` (informativo: qué archivo del fork se tocó desde el último
sync). El docstring del script tiene el detalle de cada una y sus límites.

**Este es el que hay que correr primero** cuando llega una versión nueva del
upstream.

### `contrast.py` — ¿la paleta cumple contraste WCAG?

```bash
python3 tools/theme-check/contrast.py shared/src/main/resources/css/modern/colors.css
python3 tools/theme-check/contrast.py .../colors.css --mode dark --json
```

Resuelve los pares texto/fondo de `pairs.json` (siguiendo cadenas de `var()` y sus
fallbacks) en los dos modos, `.dark` y `.light`, y calcula el ratio WCAG. Falla con
`FAIL` (bajo el mínimo del par) y también con `UNRESOLVED` (hay un valor real que el
script no supo interpretar: callarse ahí sería lo peor que podría hacer un gate).

Reconoce los scopes `*`, `:root*`, `.wrapper`, `.dark` y `.light`. `pairs.json`
tiene además una sección `excluded` con los pares que se saltean a propósito, cada
uno con su motivo escrito.

Se corre **una vez por tema** (toma un `colors.css`, no una carpeta).

### `parse.py` — ¿la hoja sigue parseando igual que su base?

```bash
python3 tools/theme-check/parse.py                     # los tres temas modern
python3 tools/theme-check/parse.py modern modern-video
python3 tools/theme-check/parse.py --all               # + los 4 de fábrica
```

El único chequeo que ve **daño estructural invisible en el `git diff`**. Chequea,
por archivo: comentarios sin cerrar, `*/` huérfanos (fuera de un comentario),
llaves desbalanceadas, y que el archivo del fork tenga la **misma cantidad de
bloques `{...}`** que su archivo base.

Existe por un defecto real: al tokenizar una línea se le agregó al final el marcador
`/* modern: tokenizado */`, pero la línea vivía **dentro de un comentario de
bloque**. Los comentarios de CSS no anidan, así que el `*/` del marcador cerró el
comentario grande antes de tiempo y el parser terminó descartando una regla. En el
diff se veía una línea con un comentario prolijo agregado. Ni `contrast.py` (sólo
lee tokens de `colors.css`) ni `drift.py` (sólo compara SHA contra el manifiesto)
pueden ver eso.

`colors.css` está declarado como excepción del conteo de bloques (se reescribe
entero a propósito) y `ncurrentathlete.css` queda fuera de la comparación (no tiene
base de fábrica); los dos siguen recibiendo los chequeos estructurales.

### `tokens.py` — ¿hay `var()` que no resuelven a nada?

```bash
python3 tools/theme-check/tokens.py            # los tres temas modern
python3 tools/theme-check/tokens.py --all      # + los 4 de fábrica
python3 tools/theme-check/tokens.py --strict   # fallar también con los heredados
```

Busca tokens que el tema **usa** con `var()` y no **define** en ninguna de sus
hojas. Un `var(--x)` sin definición y sin fallback descarta la declaración entera,
sin error de sintaxis: el board simplemente no pinta ese color.

Clasifica en cuatro categorías para no tirar todo al mismo balde: `RUNTIME` (owlcms
lo inyecta como `style` inline — el script lo detecta buscando el nombre del token
en el código Java y en los templates Lit), `FALLBACK` (todos los usos pasan un
fallback), `HEREDADO` (también falta en el tema de fábrica del que somos fork: es un
defecto preexistente de owlcms) y `HUERFANO` (una referencia que el fork rompió).
Sólo `HUERFANO` hace fallar por defecto.

Hallazgo que ya dio: `--lightGoodTextColor` y `--lightGoodBackgroundColor` se usan en
`top.css`/`topSinclair.css` de los **siete** temas de `css/` y no se definen en
ninguno. Es un defecto preexistente de owlcms, no de este fork.

### Los archivos de datos

- `theme-sync.json` — manifiesto de `drift.py`. Se regenera con `--update`, no se
  edita a mano.
- `pairs.json` — pares texto/fondo y exclusiones de `contrast.py`.

---

## Receta de port

Cuando llega una versión nueva del upstream, portar los cambios a los tres forks
lleva **20 a 40 minutos** (medido). Los conflictos reales son 0 a 3 y triviales,
porque el fork toca muy pocas líneas de cada archivo (ver el mapa de deltas más
abajo).

### 1. Ver qué cambió

```bash
python3 tools/theme-check/drift.py
```

Si sale `Sin drift`, no hay nada que portar y podés parar acá. Si hay `DRIFT`, la
salida lista exactamente qué archivo base cambió y qué archivo del fork revisar.
`NUEVO` significa que el upstream agregó una hoja: hay que decidir si los forks la
necesitan (si la necesitan, copiarla y tokenizar lo que corresponda). `PERDIDA` /
`BASE` significan que el upstream borró o renombró algo: revisar si el fork todavía
necesita ese contenido.

### 2. Fusionar archivo por archivo, con `git merge-file`

Para cada archivo con `DRIFT`, el merge de tres vías es el camino: la versión vieja
de la base es el ancestro común.

```bash
# SHA de la base en el último sync (está en theme-sync.json):
python3 -c "import json;print(json.load(open('tools/theme-check/theme-sync.json'))['modern']['files']['results.css']['base_sha'])"

BASE=shared/src/main/resources/css/nogrid/results.css
FORK=shared/src/main/resources/css/modern/results.css
git show <base_sha_del_manifiesto> > /tmp/ancestro.css

git merge-file "$FORK" /tmp/ancestro.css "$BASE"
```

`git merge-file` edita `$FORK` en su lugar y sale con la cantidad de conflictos
(0 = limpio). Repetir por cada archivo con `DRIFT` y por cada uno de los tres temas.

### 3. Resolver los conflictos

Son triviales porque siempre son la misma forma: el upstream tocó una línea que
nosotros habíamos tokenizado. La regla de resolución es una sola:

> **Quedate con el cambio del upstream en todo lo que no sea el valor tokenizado, y
> con el `var(--token)` nuestro en el valor.**

Y las dos invariantes que hay que respetar al resolver:

- **Toda línea que difiera de la base lleva un marcador `/* modern: <motivo> */`.**
  Es lo que hace que el próximo port sea barato: un `grep -n "modern:"` sobre un
  archivo lista todo lo que tocamos.
- **Nunca poner un marcador dentro de un comentario de bloque.** Los comentarios de
  CSS no anidan y el `*/` del marcador cierra el comentario grande antes de tiempo.
  Si la línea a tokenizar está comentada, la tokenización es inerte: dejala verbatim.
  (`parse.py` atrapa esto, pero mejor no llegar ahí.)

### Ojo al editar `results.css` y mirar los tableros multi

`resultsMulti.css` hace `@import url('results.css')` **sin versión**. Los `<link>` que
inyecta `stylesheetHref` llevan `?v=<timestamp>`, pero ese `@import` no, así que al
editar `results.css` los tableros `multiRanks`/`publicMultiRanks` siguen viendo la
copia cacheada por más que se recargue con un query nuevo. Se nota porque la regla
nueva no aparece en el CSSOM aunque el archivo servido sí la tenga.

Para forzarlo desde la consola del tablero, antes de recargar:

```js
await fetch('local/css/modern/results.css', { cache: 'reload' });
```

O un hard reload del navegador. No es un problema del tema: pasa igual con las
carpetas de fábrica.

### 4. Verificar

```bash
# contraste, uno por tema
for t in modern modern-public modern-video; do
  python3 tools/theme-check/contrast.py shared/src/main/resources/css/$t/colors.css || echo "FALLO $t"
done

# estructura y conteo de bloques
python3 tools/theme-check/parse.py

# tokens sin definir
python3 tools/theme-check/tokens.py
```

Los tres tienen que salir con 0. Si `parse.py` reporta `REGLAS`, el merge agregó o
borró una regla: revisar si es intencional (el upstream agregó una regla y hay que
aceptarla — en ese caso el conteo nuevo es el correcto y coincide con la base, así
que el chequeo pasa solo) o si es daño (un comentario mal cerrado).

Y las cuatro carpetas de fábrica tienen que seguir **byte-idénticas**:

```bash
git diff --stat -- shared/src/main/resources/css/{nogrid,public,transparent,grid}/
# tiene que salir vacío
```

### 5. Registrar el nuevo punto de sync

```bash
python3 tools/theme-check/drift.py --update
python3 tools/theme-check/drift.py     # tiene que salir 0 y sin EDITADO
```

`--update` graba el estado actual **de forma incondicional**: no corre la
comparación antes de escribir. Correr el paso 1 antes de esto es responsabilidad de
quien lo opera.

---

## Mapa de deltas: qué difiere cada tema de su base

La disciplina del fork es **editar valores, no agregar reglas**. Por eso los
conflictos de port son pocos. Concretamente, sobre los 49 archivos de los tres temas:

| archivo | `modern` vs `nogrid` | `modern-public` vs `public` | `modern-video` vs `transparent` |
|---|---|---|---|
| `attemptboard.css` | 1 línea | 1 línea | 1 línea |
| `colors.css` | reescrito | reescrito | reescrito |
| `currentathlete.css` | 1 línea | 1 línea | 1 línea |
| `decisionboard.css` | 1 línea | 1 línea | 1 línea |
| `eventmonitor.css` | idéntico | idéntico | idéntico |
| `jurydecisions.css` | 1 línea | 1 línea | 1 línea |
| `ncurrentathlete.css` | archivo nuevo | archivo nuevo | archivo nuevo |
| `publicresultsCustomization.css` | idéntico | idéntico | idéntico |
| `results.css` | 6 tokenizadas + 6 declaraciones + 2 selectores | 8 tokenizadas + 8 declaraciones + 7 selectores | 8 tokenizadas + 8 declaraciones + 7 selectores |
| `resultsCustomization.css` | 2 declaraciones quitadas + 1 selector | 2 declaraciones quitadas + 1 selector | 2 declaraciones quitadas + 1 selector |
| `resultsDecisionSection.css` | (no existe en esta familia) | idéntico | (no existe; ver `@import` abajo) |
| `resultsMedalsCustomization.css` | idéntico | 1 línea | 1 línea |
| `resultsMulti.css` | idéntico | idéntico | 1 `@import` |
| `resultsMultiCustomization.css` | 2 declaraciones quitadas + 1 selector | 2 declaraciones quitadas + 1 selector | 2 declaraciones quitadas + 1 selector |
| `startListCustomization.css` | 1 línea | 1 línea | 1 línea |
| `top.css` | 1 línea | 1 línea | 1 línea |
| `topSinclair.css` | 1 línea | 1 línea | 1 línea |

Y las líneas son casi siempre la misma cosa:

**Tipografía (una línea por archivo, 8 archivos).** Cada `font-family` literal de
fábrica pasa a `var(--boardFontFamily)`. La regla `@font-face` de Archivo **no** vive
en ningún `colors.css`: las hojas de tema se cargan dentro del shadow root de los
componentes Lit y ahí un `font-face` no registra la familia. Vive en
`owlcms/src/main/resources/META-INF/resources/styles.css`, que es document-scope
(`AppShell: @StyleSheet("styles.css")`), junto con los `.woff2` en
`owlcms/src/main/resources/fonts/`.

**Geometría (`results.css`, 3 tokenizadas + 6 declaraciones).** Tres `grid-gap: 1px`
pasan a `var(--cellGap)` — ojo, esos tres son del **recuadro de récords**, no de la
tabla de resultados. En la tabla, la separación del estilo D se consigue con
`column-gap: var(--cellGap)` en la regla `table`, y **solo en columnas**: agregar
`row-gap` cuesta filas visibles en sesiones grandes (con 30 atletas queda ~1.3px de
aire por fila). Por el mismo motivo la regla `th, td` agrega `align-items: center`
pero **no** un `min-height`: un piso de altura en px anula el knob `?em=`
del operador (`BaseResults.pushEmSize` empuja `--tableFontSize` en `em`) y recorta
filas con grupos grandes, porque la grilla es
`repeat(var(--top), min-content)`. Medido a 1440×626 con 40 atletas y `?em=0.5`: con
un piso de 46px entran 10 de 40 filas; sin piso, 39 de 40, y el `?em=` vuelve a
funcionar (13.59px de celda contra 46px fijos).

El `border-radius: var(--cellRadius)` va en las **cuatro reglas de celdas con color
propio** (`td.good`, `td.fail`, `td.best`/`th.best`, `td.total`/`th.total`), **no** en
la regla genérica `th, td`. En las celdas planas producía muescas: como no hay
`row-gap` se tocan verticalmente, y sus esquinas redondeadas dejaban ver el fondo de
página; el `column-gap` las destapaba como una línea de rombos. Puestas ahí, los
chips de color se leen como pastillas y las celdas planas forman tiras verticales
limpias.

**Columnas de `rank` colapsadas (`resultsCustomization.css`, 2 declaraciones quitadas).**
Ese archivo abre con un bloque `* { … }` y de fábrica declara ahí
`--rankWidth: var(--liftResultWidth)` y `--rankVisibility: visible`. Como `*` matchea
cada `th`/`td` **directamente**, y una declaración propia siempre le gana a un valor
heredado, las celdas `.rank` nunca veían el `0`/`hidden` que la tabla toma de
`table.results.noranks`: la pista del grid colapsaba a 0px pero la celda seguía con
`min-width: 6ch` y `visibility: visible`, y desbordaba. Con `column-gap: 0` las celdas
opacas vecinas tapaban ese desborde; con el `column-gap` de este tema se asomaba como
una marca clara al lado de cada `vspacer` del encabezado. Sin declararlas, las celdas
heredan de la tabla y el switch `ranks`/`noranks` funciona como fue diseñado; la media
query de portrait de más abajo las sigue apagando por `*`, así que ese camino no
cambia. Quitarlas es neutro cuando los ranks están encendidos, porque `table.results`
declara exactamente la misma expresión. Verificado con `noranks` en
`/displays/resultsLeaders`: `th.rank` y `td.rank` quedan en `visibility: hidden` /
`min-width: 0`, y `totalRank` sigue visible en 53px.

**Slot de la bandera del equipo (`resultsCustomization.css`, 1 selector).** De fábrica,
`td.flags div.flags` reserva un ancho fijo (`flex: 0 0 calc(var(--flagHeight)*1.3 + 2vh)`
más el `width` equivalente) **siempre**, haya o no una imagen de bandera. Con datos sin
banderas eso deja un hueco muerto — medido, 48.2px — a la izquierda del nombre del
equipo: la celda está en `justify-content: center`, pero lo que centra es "slot vacío +
texto", así que el texto parece alineado a la derecha. El selector pasa a
`table.results:has(td.club.flags img) td.flags div.flags`, o sea la reserva se activa
solo si el tablero tiene alguna bandera. Es a nivel de **tabla**, no de celda, a
propósito: por celda, un tablero mixto (algunos equipos con archivo de bandera y otros
sin) pondría el texto en dos posiciones distintas según la fila. Mismo patrón que
owlcms ya usa en `results.css` con
`table.results:has(td.club.flags.longTeam)`. Ojo al portar: **`:empty` no sirve** para
detectar el slot vacío, el div trae un espacio. Medido en las dos ramas: sin banderas,
los 9 slots en 0px y márgenes 3.3/3.3, con la columna bajando de 111.4px a 63.1px (esos
48px vuelven a la columna Name); con una bandera inyectada en una sola celda, los 9
slots vuelven a 48.2px, valor único.

**Encabezado de rank en `public`/`transparent` (`results.css`, 1 selector + 2
declaraciones — solo `modern-public` y `modern-video`).** Las tres bases **no** son
equivalentes acá, y es una trampa fácil: en `nogrid` la regla de rank es
`td.rank, th.rank` con `min-width: var(--rankWidth)`, pero en `public` y `transparent`
es **solo `td.rank`** y **sin `min-width`**. Consecuencia con la clase `noranks`: la
celda de datos se oculta, pero el `th` del encabezado nunca recibe el
`visibility: hidden` y, sin piso de ancho, se dimensiona por contenido — desborda su
pista de grid de 0px y pinta una marca clara al lado de cada `vspacer`. Con
`column-gap: 0` lo tapaban las celdas opacas vecinas. Los dos temas alinean ahora la
regla con la de `nogrid`. Verificado en `/displays/publicScoreboard` y
`/displays/resultsLeaders/video`: `th.rank` en `visibility: hidden` con
`min-width: 0px`.

**Alineación del equipo en `public`/`transparent` (`results.css`, 4 selectores — solo
`modern-public` y `modern-video`).** Estas dos bases traen cuatro reglas que `nogrid`
no tiene: `:host .wrapper.Results …` y `:host([ranking-order]) …` sobre `td.club` y
sobre `div.clubName`, con `justify-content: flex-start !important` y un `gap`. Están
pensadas para "bandera + nombre" y de fábrica se aplican **siempre**, así que sin
banderas cargadas el nombre queda pegado al borde izquierdo mientras el encabezado
"Team" sigue centrado. Se condicionan con `:has(td.club.flags img)`, igual que el slot
de bandera. Sin banderas el fallback es el `justify-content: center` de la regla
genérica de celdas (que `public` ya define); con banderas se recupera exactamente el
comportamiento de fábrica. Medido en `/displays/publicScoreboard`: sin banderas,
`justify-content: center` y márgenes simétricos (57/57, 50.5/50.5, 59.3/59.3); con una
bandera inyectada por sonda, las cuatro celdas vuelven a `flex-start`.

**Logos (`results.css`, 2 líneas).** `url('../../logos/left.png')` y `right.png` pasan
a `var(--eventLogo)` y `var(--federationLogo)`. Los tokens apuntan por defecto a los
mismos archivos, así que el render no cambia; lo que se gana es el punto de
personalización.

**`@import` (`modern-video/resultsMulti.css`).** La base `transparent` importaba
`../public/resultsDecisionSection.css`, una hoja de la carpeta **de fábrica** — una
fuga entre familias. Ahora apunta a `../modern-public/`, que es byte-idéntica, y la
familia queda autocontenida.

**`colors.css` (reescrito).** Es la hoja de paleta: define la paleta `modern` entera.
Los tres archivos siguen una invariante de capas:

- El **cuerpo** de `modern-public/colors.css` y el de `modern-video/colors.css` son
  **byte-idénticos** al de `modern/colors.css`.
- Toda diferencia vive en un **bloque de overrides al final**, apilado, que gana por
  orden en la cascada. `modern-public` traduce a la paleta `modern` los tokens en que
  `public` difiere de `nogrid`; `modern-video` agrega arriba de eso la transparencia
  de la página (`--pageBackgroundColor: transparent`) y el corte de cadena de
  `--RecordNameBackground` en `.dark`.
- Corolario práctico: **nunca editar un valor dentro del cuerpo** de
  `modern-public`/`modern-video`. Se apila un bloque al final. Editar el cuerpo rompe
  la invariante y la próxima persona no puede confiar en la cabecera del archivo.

**Scope de los tokens del encabezado de video.** `--videoHeaderBackgroundColor` y
`--videoHeaderTextColor` se declaran en `.wrapper`, **no** en `*`, en los tres temas.
Esto es una **divergencia deliberada** respecto de `nogrid` (que los declara en `*`),
alineada con lo que ya hacen `public` y `transparent` de fábrica: owlcms inyecta el
override de branding en runtime como `style` inline sobre el div `.wrapper`
(`StylesDirSelection.overrideColors` → propiedad `colorOverride`, consumida por los
templates Lit). Declarados en `*`, la regla matchea cada descendiente de `.wrapper` y
le gana al valor heredado del inline, así que el knob queda inerte. En `.wrapper` el
inline gana y el valor se hereda. Si algún día se porta un cambio del upstream que
los mueva de vuelta a `*`, **no aceptarlo**.

**`ncurrentathlete.css` (archivo nuevo).** `NCurrentAthlete.js` lo carga pero ningún
tema de fábrica lo provee. Los tres temas lo tienen **idéntico salvo la cabecera**.
Está declarado en `SIN_BASE_ESPERADOS` en `drift.py` y `parse.py` para que no se
confunda con un huérfano.

---

## Defectos preexistentes de owlcms que se encontraron por el camino

No son regresiones de este fork: están igual en las carpetas de fábrica. Se listan
acá para que nadie los persiga como si fueran nuestros.

- `--lightGoodTextColor` / `--lightGoodBackgroundColor` se usan en
  `top.css`/`topSinclair.css` de los siete temas y no se definen en ninguno
  (`tokens.py --all` los lista).
- `--RecordCatBackground` y `--RecordCatText` se definen en los temas de fábrica y no
  se consumen en ninguna hoja. En los tres temas `modern` se borró
  `--RecordCatBackground`; `--RecordCatText` sigue ahí, heredado.
- `publicresultsCustomization.css` es un **archivo muerto**: cero referencias en todo
  el repo (ningún `stylesheetHref`, ningún Java, ningún JS lo menciona). Está en las
  4 carpetas de fábrica y por simetría también en las 3 nuestras.
- `resultsMultiCustomization.css` fuerza `--pageBackgroundColor: black`, por eso
  `multiRanks` ignora la paleta del tema. Es byte-idéntico a la fábrica en los tres
  temas.
- `transparent/resultsMulti.css` importa una hoja de la carpeta `public` (fuga entre
  familias). En `modern-video` está corregido; en la carpeta de fábrica sigue así.
- El bloque `* { … }` de los `*Customization.css` le gana a los switches de la tabla.
  Esos archivos declaran en `*` tokens que las variantes (`table.results.noranks`,
  `.nototalRank`, …) redefinen sobre `table.results`. Como `*` matchea las celdas
  directamente, la celda nunca hereda el switch: se queda visible y con ancho mientras
  su pista del grid vale 0, y desborda. Sin `column-gap` no se nota, porque las celdas
  vecinas opacas tapan el desborde. En `resultsCustomization.css` está corregido en
  los tres temas (ver el mapa de deltas). Queda **sin corregir**, igual que en
  fábrica, en dos archivos: `publicresultsCustomization.css` — que es un archivo
  muerto, ver arriba — y `resultsMultiCustomization.css`, donde el valor del bloque
  `*` (`3ch`) **no** coincide con el de la tabla (`3em`), así que quitarlo cambiaría
  el ancho visible de los ranks en `multiRanks`: no es una sustitución neutra y hay
  que medirla en ese tablero antes de tocarla. El mismo defecto afecta a
  `--totalRankWidth`/`--totalRankVisibility`; hoy no se manifiesta porque los tableros
  en uso no apagan el rank total.
  **Corregido también en `resultsMultiCustomization.css`** (tablero `multiRanks`), donde
  el bloque `*` declaraba `3ch` contra el `3em` de `table.results.ranks`. Se midió antes
  de tocarlo: `3ch` = 27.6px y `3em` = 46.4px, así que con los ranks encendidos la pista
  manda y el `min-width` de la celda nunca era vinculante — quitarlo del `*` es neutro y
  además alinea el `min-width` con la pista. En `modern-public`/`modern-video` el bloque
  `*` ya decía `3em`, el mismo valor de la tabla, así que ahí es trivialmente neutro.
  **Sin corregir**, a propósito, en `resultsMedalsCustomization.css` y
  `startListCustomization.css`: esos dos **no** definen `--rankWidth` a nivel de tabla,
  solo lo consumen en `grid-template-columns`, así que quitarlo del `*` dejaría el token
  indefinido y rompería la grilla. Ahí tampoco hay defecto: celda y pista salen del mismo
  valor, así que no desbordan.
- Los encabezados de rank por categoría de `ResultsMulti.js` se emiten **sin clase**
  (el texto es el nombre de la categoría, p. ej. "Open"). Con los ranks apagados su
  pista del grid colapsa, pero al no tener clase ninguna regla de fábrica los oculta:
  medido en `multiRanks`, caja de 6.6px con 2.32px de padding por lado — 2px de
  contenido — con el texto de 38.1px centrado y `overflow: hidden`, o sea una tajada de
  2px asomándose por el `column-gap`. **Corregido en los tres temas** con un tercer
  selector en la regla de rank de `results.css`:
  `:host table.results tr.head th.best + th:not([class]):not([style])`. `th.best +` lo
  distingue de los otros `th` sin clase de esa fila y `:not([style])` descarta los
  encabezados de grupo (Snatch / Clean&Jerk / Total), que son sin clase pero llevan un
  `grid-column: span` inline. Medido: matchea exactamente 1 elemento en `multiRanks` y
  **0** en los tableros de una sola categoría, donde después de `th.best` viene
  `th.rank`, que sí tiene clase. Darle una clase en el template sigue siendo el arreglo
  de fondo y es candidato a PR upstream; mientras tanto el selector alcanza.
  Limitación conocida: si `--nbRanks` fuera mayor a 1 y el template emitiera varios sin
  clase seguidos, el selector solo alcanza al primero.
- En el subencabezado de `ResultsMulti.js`, la columna del rank **total** lleva
  `class="rank"` en el `th` pero `class="totalRank"` en el `td`. Con `noranks` +
  `totalRank` — ranks por levantamiento apagados, total encendido, que es la
  configuración habitual — las dos mitades de la misma columna siguen switches
  distintos: el `td` queda visible con su dato y el `th` se oculta, dejando una columna
  con datos y **sin rótulo**. **Corregido en los tres temas** agregando
  `:host table.results tr.head th.rank:has(+ .sinclairVspacer)` a la regla de
  `totalRank` en `results.css`. Ese spacer extra existe solo en el encabezado de
  `ResultsMulti.js` (lo dice el comentario de cabecera de `resultsMulti.css`), y el
  `th.rank` del grupo Total es el único que lo tiene como hermano siguiente. Medido:
  alcanza 1 elemento en `multiRanks` y **0** en los tableros de una sola categoría,
  donde `.sinclairVspacer` no existe y el `th.totalRank` ya está bien etiquetado
  ("Ubic.", visible). Corregir la clase en el template es el arreglo de fondo;
  candidato a PR upstream.
- El slot de la bandera del equipo se reserva aunque no haya bandera. `td.flags
  div.flags` fija `flex-basis` y `width` sin condicionar a que exista la imagen, así
  que un tablero sin banderas muestra 48.2px de hueco muerto en cada celda de equipo.
  En `resultsCustomization.css` está corregido en los tres temas (ver el mapa de
  deltas); sigue igual que en fábrica en `startListCustomization.css`,
  `resultsMedalsCustomization.css` y `publicresultsCustomization.css`. En
  `resultsMultiCustomization.css` **ya está corregido en los tres temas**, pero con dos
  selectores distintos, y esta es una trampa al portar: la variante de `nogrid` usa
  `td.flags div.flags`, mientras que las de `public`/`transparent` usan el más amplio
  **`td.flags div`** — cualquier div dentro de la celda. Como el `td` lleva las clases
  `club flags`, ese selector le aplica el ancho fijo del slot **también al
  `div.ellipsis` del nombre del equipo**, que además de correr el texto lo **trunca**
  (medido en `multiRanks` con `modern-video`: hueco de 55.3px, márgenes 85 contra 29.7,
  y "NORTH" recortado a "NORT"). Buscar `td.flags div.flags` no encuentra esa variante;
  hay que buscar `td.flags div`. Corregido condicionándolo igual, con
  `table.results:has(td.club.flags img)`. Verificado en `multiRanks?video=true`
  (`modern-video`: 50.5/50.5, slot 0 sin banderas y 55.3 con una, transparencia del
  `.wrapper` intacta) y en `publicMultiRanks` (`modern-public`: 4.8/4.8, slot 0). `startListCustomization.css` no
  necesita arreglo: su `td.flags div.flags` no declara `width` ni `flex`, así que no
  reserva nada. El de medals tiene un juego de reglas distinto y su tabla es
  `table.results.medals`; hay que medirlo con medallas cargadas antes de tocarlo.
- En `public` y `transparent`, la regla de rank es solo `td.rank` y sin `min-width`, así
  que la clase `noranks` **no** oculta el `th` del encabezado: queda visible y sin piso
  de ancho, desbordando su pista de 0px. En `nogrid` la misma regla sí cubre `th.rank`.
  Corregido en `modern-public`/`modern-video` alineando con `nogrid`.
- En `public` y `transparent`, las reglas `.wrapper.Results` / `[ranking-order]` alinean
  el equipo a la izquierda con `!important` **siempre**, no solo cuando hay banderas.
  Corregido en `modern-public`/`modern-video` condicionándolas a que haya banderas.

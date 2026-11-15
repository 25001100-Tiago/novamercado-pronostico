# Decisiones de diseño — NovaMercado

## 1. Política de reparar / advertir / rechazar

Principio: **reparar solo lo inequívoco, advertir cuando se supone algo, rechazar cuando
cualquier respuesta podría ser incorrecta.** Un pronóstico silenciosamente equivocado es
peor que un 422 claro, pero rechazar algo que tiene una sola lectura posible solo
entorpece la operación de las tiendas. Toda decisión queda en `calidad.observaciones`
(y en la tabla `correcciones`); los rechazos devuelven **todos** los errores a la vez.

| Situación | Acción | Justificación |
|---|---|---|
| `tienda_id` `"5"`, `"05"`, `"T05"`, `"tienda_5"`, `5.0` (E01) | reparar | Un único entero posible; se valida luego contra `tiendas.csv`. |
| Familia `"LÁCTEOS"`, `"Frutas y Verduras"`, `"cuidado-personal"` (E02) | reparar | Mayúsculas, tildes y separadores no cambian el significado; se compara con id y nombre de `familias.csv`. |
| Error tipográfico leve (`"abarotes"`, `"lacteso"`) | reparar | Damerau-Levenshtein ≤ 1–2 con **una sola** familia candidata; si hay empate o está lejos, se rechaza. |
| Números como texto `"8"`, `8.0`, `"994.0"` (E03) | reparar | Valor entero inequívoco. |
| `"1,292"` (miles) y `"50,0"` (coma decimal) (E10) | reparar | Con 3 dígitos tras la coma, la lectura decimal (1.292) no es entera: la única lectura válida para un conteo es 1292. |
| `"994.000"` | rechazar | Puede ser 994 o 994 000: ambigüedad real. |
| Fecha `DD/MM/AAAA`, `AAAA/MM/DD`, `DD-MM-AAAA`, ISO con hora, `AAAAMMDD` (E04) | reparar | Formato reconocible; `11/17/2025` también, porque 17 solo puede ser el día. |
| `05/11/2025` (día y mes ≤ 12) | advertir | Se asume DD/MM (convención guatemalteca) y se informa. |
| Campo renombrado con sinónimo conocido (`tienda`, `Fecha`) (E07) | reparar | Mapeo explícito de alias; si el alias y el campo oficial traen valores distintos, se rechaza. |
| Faltan familias (E05) | advertir | Se pronostica lo pedido; inventar la promoción de lo no pedido sería suponer demasiado. |
| Familia repetida (E06) | idénticas: reparar · distintas: advertir y conservar la última | La última línea suele ser la corrección del sistema emisor. |
| `en_promocion` nulo o ausente | advertir, asumir 0 | Es el valor más frecuente y el efecto de un error es acotado. |
| Valor extremo (> máximo histórico) | advertir | Plausible (promociones, temporada). Inverosímil (> 20× el máximo de ventas o > 10× el de promociones) → rechazar. |
| Campo desconocido | advertir e ignorar | No afecta al modelo; avisar ayuda a corregir al emisor. |
| Ventas negativas (E08), valores no enteros, tienda inexistente o ≤ 0, familia irreconocible, fecha inexistente o anterior a la apertura de la tienda, listas vacías, campos obligatorios ausentes | rechazar (422) | No hay reparación segura. Una devolución no es una venta negativa. |
| Envío repetido (E09) | aceptar | La BD hace el guardado idempotente: el segundo envío devuelve `registros_guardados: 0`. |

**Nunca se usa el reloj del sistema** (el laboratorio opera con fechas simuladas). Las
referencias temporales son la fecha de apertura de cada tienda y el último día con datos
en la BD, que actúa como "hoy" simulado para advertir pronósticos a más de 366 días.
Hay una prueba que impide introducir `today()` o `now()` en el motor de limpieza.

Defensa en dos capas: `limpieza.py` repara y decide sobre el JSON crudo, y los modelos
Pydantic estrictos (`StrictInt`, sin campos extra, familias únicas del catálogo) validan
la salida antes de que llegue al modelo o a la BD. Los endpoints reciben el cuerpo crudo
porque, si FastAPI validara primero, rechazaría casos reparables.

## 2. Features sin fuga temporal

Para un objetivo con fecha `D` solo se usan observaciones con fecha `< D`. Se construye
una rejilla diaria completa por (tienda, familia) y toda feature histórica sale de la serie
desplazada al menos un día. **La misma función** (`modelo.construir_features`) se usa al
entrenar y al servir, así que no hay diferencias entre ambos. Una prueba altera las ventas
desde una fecha de corte y comprueba que ninguna feature hasta ese día cambia; otra
prueba de la API inserta datos del mismo día y del futuro y verifica que el pronóstico no se mueve.

| Grupo | Features |
|---|---|
| Del propio día (conocidas al pedir) | `en_promocion` de la solicitud, día de semana, día del mes, mes, semana ISO, quincena/fin de mes, fin de semana |
| Feriados (`feriados.csv`) | feriado, comercial, pago, medio día y víspera de feriado; aplica si `ambito == 'nacional'` o `ambito == ciudad` de la tienda (`tiendas.csv`) |
| Historia (< D) | lags 1, 7, 14 y 28; medias móviles 7 y 28; desviación 28; media de los últimos 4 mismos días de la semana; promoción media 28 y su diferencia con la de hoy; último valor observado y días desde él (para huecos); tendencia media7/media28 |
| Tienda / familia | `tienda_id`, tipo de tienda, días desde la apertura y familia, como categóricas nativas del HGB |

En producción la API lee de PostgreSQL las observaciones de la tienda anteriores a `D`
(últimos 60 días con datos), así que cada observación nueva mejora el pronóstico del día siguiente.

## 3. Modelos y `cantidad_sugerida`

- **Baseline**: media de los últimos 4 mismos días de la semana por tienda y familia (si no hay, se usa la media de 28 días).
- **Modelo ML**: `HistGradientBoostingRegressor` con pérdida Poisson (ventas = conteos
  no negativos), 300 iteraciones. Entrena en unos 8 s con todo el histórico.
- **Cantidad sugerida**: el costo por familia es
  `C_f · max(real − q, 0) + C_s · max(q − real, 0)`. El óptimo teórico es el cuantil
  `C_f / (C_f + C_s)` de la demanda (razón crítica: licores 0,95, limpieza 0,91,
  panadería 0,29…). Para obtenerlo se busca, en una **ventana de calibración fuera de
  muestra**, el factor por familia `k ∈ [0,50; 2,50]` que minimiza el costo real de
  `q = round(venta_esperada · k)`. Así se optimiza exactamente la cantidad entera enviada.
  Los factores obtenidos siguen la razón crítica (licores 1,39 y panadería 0,81).
  `cantidad_sugerida` es siempre un entero ≥ 0.
- Resultado con el histórico publicado (validación del 01 al 28 de febrero de 2026): costo
  **89 153** del HGB frente a **134 756** del baseline (−34 %); MAE 37,8 frente a 45,9.

Se registran en MLflow (experimento `novamercado-ventas`) los parámetros, el linaje (rango
de fechas, filas, huella de los datos, ventanas, ejecución), MAE, RMSE,
`costo_total_validacion` (total y por familia) y las métricas del baseline. El modelo se
registra como `novamercado-pronostico` (pyfunc con el artefacto joblib).

## 4. Criterio de reemplazo del modelo (compuerta)

Las ventanas se derivan de la última fecha con datos `F`:
calibración = 28 días previos a la validación y validación = `[F−27, F]`. El modelo
desplegado se ajusta con datos anteriores a la validación y **se despliega exactamente el
artefacto evaluado**, sin reajustarlo después.

En cada reentrenamiento (`compuerta_y_promocion` del DAG):

1. se carga el `@champion` vigente y el candidato (`@challenger`);
2. ambos se evalúan sobre **la misma ventana de validación reciente** y con las mismas
   features calculadas desde PostgreSQL;
3. se promueve el candidato a `@champion` **solo si su `costo_total_validacion` es
   estrictamente menor**. Si empata o pierde, se conserva el vigente y la razón queda en `motivo`.

Como el vigente se ajustó antes de su propia ventana de validación, en un reentrenamiento
posterior la ventana nueva queda fuera de muestra para ambos modelos y la comparación es
justa. Ninguno de los dos se evalúa con datos que vio al entrenar. Si no hay datos nuevos,
el candidato es idéntico y no se promueve.

## 5. Otras decisiones de operación

- **Idempotencia**: un único `INSERT … ON CONFLICT DO UPDATE … WHERE ventas <> excluded.ventas RETURNING`.
  `registros_guardados` cuenta exactamente las filas nuevas o con ventas distintas, y la operación es atómica.
- **Hot-reload y caché**: la API consulta `@champion` cada 20 s. Si cambia, descarga el
  artefacto, lo reemplaza en memoria y actualiza la caché en disco (`os.replace` atómico).
  Al arrancar carga primero la caché, así que puede predecir aunque MLflow esté caído.
- **Salud**: chequeo en segundo plano cada 15 s (timeout de 3 s) de PostgreSQL, MLflow y
  Airflow. Sin modelo → 503. Con modelo y alguna dependencia caída → 200 `degradado`
  con `motivo`. Las predicciones siguen funcionando con el modelo en memoria.
- **Airflow 3**: la API dispara el DAG por la REST API v2 (token JWT del SimpleAuthManager)
  con `conf={"ejecucion_id": …}`. Las tareas ejecutan el código del producto en un entorno
  virtual propio dentro de la imagen, para no mezclar sus dependencias con las de Airflow.
  Si una tarea falla, `registrar_fallo` marca la ejecución como `fallido`.
- **MLflow** sirve los artefactos (`--serve-artifacts`) desde su volumen persistente. Los
  clientes (API, Airflow y bootstrap) los suben y bajan por HTTP, sin compartir sistemas de archivos.
- **Imagen de Airflow**: el enunciado indica `airflow/apache:3.3.2-python3.12`, que no existe
  en Docker Hub. Se usa la imagen oficial `apache/airflow:3.3.2-python3.12`.
- **Datos fuera de Git**: los archivos publicados se colocan en `data/raw/` (ver README).
  Las pruebas se omiten con un aviso si no están.

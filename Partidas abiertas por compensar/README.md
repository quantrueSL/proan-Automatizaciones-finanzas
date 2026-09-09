# Reporte diario de partidas pendientes de compensar

Cada dia, de lunes a sabado a las 10:40 de Mexico, lista las partidas de cuentas de mayor
que siguen sin compensar en 16 sociedades, guarda una foto en BigQuery y envia un correo
por sociedad mas uno consolidado. Sustituye el reporte que se sacaba a mano de SAP
(`reportesEspeciales > reportePartidasPendientes`).

## Que es compensar, y por que importa

Compensar es **casar dos o mas apuntes que deben anularse entre si**. El caso tipico es
una factura y su pago: cuando SAP los empareja escribe en ambos el documento de
compensacion (`AUGBL`) y los dos **salen de la tabla de partidas abiertas**.

En cuentas de mayor esto se usa para las cuentas que funcionan por parejas: traspasos
entre bancos, cuentas puente, devengos de intereses, retenciones. **Una partida que sigue
abierta es una pata sin su contraparte**: o el movimiento no llego, o se registro dos
veces, o nadie las emparejo.

Por eso este reporte no es de saldos: es de **trabajo pendiente**. Cada linea es algo que
alguien tiene que perseguir, y lo que importa es **cuanto tiempo lleva abierta**.

## De donde sale el dato

`D00_SANDBOX.bsis_real_time`, espejo de **BSIS**: el indice de partidas **abiertas** de
cuentas de mayor. Es el hermano de `BSIK`, que indexa por proveedor y alimenta el reporte
de anticipos; este indexa por cuenta contable.

**Entran todas las clases de documento (`BLART`).** Antes solo se mostraba `'ZR'`
(traspasos y movimientos de banco), pero el cliente quiere ver el resto tambien. `BLART`
se muestra en el reporte como columna `Clase`, para poder distinguirlas.

**No hace falta filtrar por `AUGBL`.** De las 1.487 filas de la tabla solo una tiene
documento de compensacion, y no es de clase `ZR`: el espejo no arrastra partidas ya
compensadas.

Como en `BSIK`, el espejo lo reescribe entero un replicador de SAP externo cada pocas
horas, asi que la tabla no guarda historia.

El **nombre de cada sociedad** sale de `D20_DIMENSION.dm_company`, cruzando `company_code`
con `BUKRS` para obtener `company_name`. Ahi `company_code` **es unico** —87 filas y 87
codigos—, asi que el cruce no necesita deduplicar, al contrario que el de `dm_vendors` en
anticipos. La columna `company` de esa tabla esta vacia en las 87 filas: la buena es
`company_name`.

### Campos que se usan

| Campo | |
|---|---|
| `BUKRS` | Sociedad |
| `HKONT` | Cuenta de mayor. **Terminada en `E` es egreso, en `I` es ingreso** |
| `GJAHR` | Ejercicio. Parte de la clave |
| `BELNR` / `BUZEI` | Documento contable y posicion |
| `BLART` | Clase de documento. Se muestra en el reporte (columna `Clase`) |
| `BUDAT` | Fecha de contabilizacion, texto `YYYYMMDD`. De aqui salen los dias abierta |
| `SHKZG` | Debe (`S`) o haber (`H`) |
| `DMBTR` | Importe en moneda local, siempre pesos |
| `GSBER` | Division. Se muestra en el reporte (columna `Div.`) |
| `ZUONR` | Campo de asignacion. Libre: a veces una fecha, a veces una referencia |
| `SGTXT` | Texto del apunte |
| `AUGBL` / `AUGDT` | Documento y fecha de compensacion. Vacios: si tuvieran valor, la partida no estaria abierta |

## La consulta

```sql
SELECT
  BUKRS AS sociedad,
  IFNULL(HKONT, '') AS cuenta,
  IF(ENDS_WITH(IFNULL(HKONT, ''), 'I'), 'Ingreso', 'Egreso') AS tipo,
  IFNULL(BLART, '') AS clase,
  GJAHR AS ejercicio,
  BELNR AS documento,
  BUZEI AS posicion,
  IFNULL(GSBER, '') AS division,
  IFNULL(ZUONR, '') AS asignacion,
  SAFE.PARSE_DATE('%Y%m%d', BUDAT) AS fecha_contabilizacion,
  DATE_DIFF(CURRENT_DATE('America/Mexico_City'),
            SAFE.PARSE_DATE('%Y%m%d', BUDAT), DAY) AS dias_abierta,
  ROUND(CASE WHEN SHKZG = 'S' THEN  CAST(DMBTR AS NUMERIC)
                              ELSE -CAST(DMBTR AS NUMERIC) END, 2) AS importe,
  IFNULL(SGTXT, '') AS texto
FROM `proan-quantrue.D00_SANDBOX.bsis_real_time`
WHERE BUKRS IN UNNEST(@sociedades)
ORDER BY sociedad, cuenta, dias_abierta DESC, documento, posicion
```

Cuatro detalles que no son opcionales:

- **`GJAHR` forma parte de la clave.** Hay un par de lineas que comparten sociedad,
  documento y posicion en ejercicios distintos. Un `SELECT DISTINCT` sin el ejercicio las
  colapsa y una desaparece en silencio.
- **`SAFE.PARSE_DATE`, no `PARSE_DATE`.** SAP admite valores como `00000000` en fechas no
  informadas: con la version normal, una sola fila mal formada tumba la consulta entera.
- **`CAST(DMBTR AS NUMERIC)`.** En el espejo `DMBTR` es `FLOAT`, y sumar dinero en coma
  flotante arrastra error. `NUMERIC` es aritmetica decimal exacta.
- **No se filtra por sufijo de cuenta.** Entran `E` e `I`. Esta convencion solo se
  verifico para las partidas `ZR`: al entrar el resto de clases de documento puede haber
  cuentas que no sigan el patron y aun asi se clasifiquen como Egreso por defecto. El
  sufijo se usa para derivar la columna Tipo, y se deja asi a proposito.

## Es un listado, no un motor de conciliacion

Se estudio si `ZUONR` permitia emparejar automaticamente las dos patas de cada operacion.
**No**: de 182 asignaciones, **ninguna tiene pata `E` e `I` a la vez dentro de la misma
sociedad**. Ignorando la sociedad aparecen dos, y son traspasos entre empresas del grupo.

`ZUONR` es un campo libre: de las 264 filas, 144 son numericas y solo 23 parecen una
fecha; el resto son referencias con letras. Cada proceso mete lo que quiere.

**Este analisis es de cuando el reporte solo cubria `ZR`**; no se ha repetido tras ampliar
a todas las clases de documento.

Asi que el reporte **agrupa por cuenta y lista**, como el reporte manual. Emparejar es
trabajo de la persona. Dentro de cada cuenta se ordena **de mas antigua a mas reciente**,
porque el valor esta en lo viejo, no en lo de ayer.

## Notas sobre columnas

**`Div.` sale de `GSBER`.** En las partidas `ZR`, `GSBER` (y `WERKS`, `PRCTR`, `KOSTL`)
estaban vacios al 100%, por eso antes no habia columna de division. Ahora que entran todas
las clases de documento se muestra `GSBER` como columna `Div.`, pero no esta verificado que
porcentaje de las otras clases lo trae relleno: puede seguir saliendo en blanco para
muchas filas.

**No hay columna de moneda.** `DMBTR` es el importe en moneda local, siempre pesos
mexicanos. Hay tres documentos emitidos en USD, y el reporte manual muestra su importe en
pesos con la etiqueta `USD` al lado, lo que induce a error. Se dice una vez en el pie del
correo y se quita la columna.

## Control de frescura

Antes de calcular nada, el proceso mira `MAX(_ingested_at)` y **falla** si el espejo tiene
mas de `PARTIDAS_MAX_ANTIGUEDAD_HORAS` horas. Si el replicador de SAP se para, la tabla no
se vacia ni avisa: se queda con la ultima copia buena. Un Cloud Run Job en rojo se ve; un
correo con datos viejos, no.

**El umbral son 20 horas, no 6 como en anticipos, y el motivo importa:** los espejos no van
todos al mismo ritmo. Medido el 30/07/2026 a las 14:32 UTC:

| Tabla | Ultima carga | Antiguedad |
|---|---|---|
| `bsid_real_time` | 13:02 UTC | 1,5 h |
| `bsik_real_time` | 13:06 UTC | 1,4 h |
| **`bsis_real_time`** | **06:57 UTC** | **7,6 h** |

`BSIK` y `BSID` se reescriben cada dos horas, a los minutos `:06` y `:02`. **`BSIS` cargo a
las 06:57 UTC —las 00:57 de Mexico— y no se movio en el resto del dia.** Minuto distinto,
pipeline distinto. Con eso, a las 10:00 de Mexico el dato de BSIS tiene unas 9 horas, asi
que un umbral de 6 lo rechazaria todos los dias.

20 horas funciona en las dos hipotesis —carga diaria o mas frecuente— y sigue cazando un
dia entero sin carga, que a la hora del reporte serian unas 33 horas.

**Queda por confirmar** si BSIS carga una vez al dia por diseno o si su replicacion se
rompio ese dia despues de las 06:57. Dos lecturas separadas por hora y media no lo
distinguen. Si con el tiempo se ve que la carga es siempre nocturna, el umbral esta bien; si
resulta que deberia ir cada dos horas, hay que avisar a quien lleve el DWH.

## Sociedades

Las 16 del Excel de correos:

```
PAN DBC ROMM PRA MPE MAL HEGP ISE PIN SAP ABP AME CCP PAL PAT BAG
```

**`ADE` queda fuera a proposito.** Tiene partidas `ZR` abiertas —y son las mas antiguas del
sistema, de diciembre de 2010— pero no esta en el Excel, asi que no hay a quien enviarselas.
Si algun dia se quiere cubrir, basta anadirla a `SOCIEDADES` y crearle su grupo en la lista
de correo.

No todas las sociedades tienen partidas pendientes cada dia. Las que no, **reciben su
correo igualmente**, con un «Sin partidas pendientes de compensar»: el silencio no se
distingue de un proceso roto.

## Tabla de salida

`proan-quantrue.D60_REPORTING.Partidas_pendientes_evolucion`, particionada por dia en
`fecha_reporte` y agrupada por `sociedad` y `cuenta`.

| Campo | Tipo | |
|---|---|---|
| `fecha_reporte` | DATE | Fecha de Mexico de la ejecucion |
| `sociedad` | STRING | `BUKRS` |
| `cuenta` | STRING | `HKONT` |
| `tipo` | STRING | `Ingreso` o `Egreso`, del sufijo de la cuenta |
| `clase_documento` | STRING | `BLART` |
| `ejercicio` | STRING | `GJAHR` |
| `documento` / `posicion` | STRING | `BELNR` / `BUZEI` |
| `division` | STRING | `GSBER` |
| `asignacion` | STRING | `ZUONR` |
| `fecha_contabilizacion` | DATE | `BUDAT` |
| `dias_abierta` | INT64 | Dias desde la contabilizacion |
| `importe` | NUMERIC | Con signo: debe positivo, haber negativo |
| `texto` | STRING | `SGTXT` |
| `actualizado_en` | DATETIME | Hora de Mexico de la ejecucion |

**Es la unica historia que existe.** Cuando una partida se compensa **desaparece de BSIS**
sin dejar marca, y el espejo se reescribe cada pocas horas. Sin esta tabla no hay forma de
saber cuanto tiempo estuvo abierta, cuando se resolvio, ni como evoluciona la bolsa de
pendientes.

Se escribe con el **decorador de particion** (`Partidas_pendientes_evolucion$YYYYMMDD`) y
`WRITE_TRUNCATE`, que reemplaza la foto del dia entera de forma atomica. No sirve un
`MERGE` por clave: una partida que se compenso a media manana **tiene que desaparecer** de
la foto, y un `MERGE` actualiza e inserta pero no borra lo que dejo de existir.

## El correo

Cada sociedad aparece con su **codigo y su razon social**: «Sociedad DBC - Distribuidora de
Basicos…», en el titulo del bloque, en la cabecera del correo y en la tabla resumen del
consolidado. El asunto se queda solo con el codigo, para no alargarlo, y el nombre del PDF
tambien.

**Si el maestro de sociedades falla, el reporte sale con los codigos a secas.** El nombre es
una comodidad de lectura, no un dato del reporte: no tiene sentido dejar a finanzas sin su
correo porque una tabla de referencia no responda. Si el maestro responde pero le falta un
codigo concreto, ese aparece como «(sin nombre en la maestra)».

Cada sociedad se presenta con **una tabla por cuenta de mayor**, con su subtotal, y el
total de la sociedad al final —que solo aparece si hay mas de una cuenta, porque con una
sola seria repetir el mismo numero—. Las columnas son fecha, dias abierta, tipo, clase,
documento, division, asignacion, texto e importe.

**Las partidas de 90 dias o mas van destacadas en rojo.** No es una regla contable: es un
umbral para que lo viejo salte a la vista en un listado que puede pasar de cien filas. Se
cambia en la constante `DIAS_PARA_AVISAR`.

Los subtotales **pueden salir negativos**, porque el signo sigue al debe y al haber: una
cuenta con mas egresos que ingresos da negativo. Es correcto, no un error.

Se envian dos tipos de correo:

- **Uno por sociedad**, con sus cuentas en el propio cuerpo del correo.
- **Uno consolidado** con las 16. **El cuerpo de este correo lleva solo el resumen**
  —partidas, cuentas, dias de la mas antigua e importe neto por sociedad— con una nota de
  que el detalle esta en el PDF adjunto, no las 16 sociedades una detras de otra en el
  propio correo.

### El grafico de evolucion

Cada correo lleva ademas un grafico de linea con los ultimos **7 dias CON foto**
(`EVOL_DIAS`, `consultar_evolucion_reciente`), no 7 dias de calendario: si un domingo
no hay particion (el Job corre de lunes a sabado) o un run cualquiera falla, ese dia se
salta en vez de dibujarse como una caida a cero que no paso.

- **Correo consolidado**: el importe neto total de las 16 sociedades como grafico
  grande de cabecera, y debajo una rejilla con un mini-grafico por sociedad — **cada
  uno a su propia escala**, para que una sociedad con mucho importe y otra con poco se
  lean igual de bien en vez de que la pequeña salga como una raya plana. Una sociedad
  sin ninguna partida en toda la ventana no sale en la rejilla.
- **Correo por sociedad**: la serie de esa sociedad como grafico grande, sin el
  problema de escala anterior.

**El grafico grande** (importe neto total del consolidado, o serie del correo por
sociedad) lleva el eje de fechas debajo de cada punto y, encima o debajo de la propia
linea, el valor de ese punto en formato abreviado (1.1M, 859.2k): en un correo no se
puede pasar el raton por encima de un punto para verlo, asi que el dato va escrito, con
un halo blanco detras para que no se pierda cruzado por la propia linea.

**El mini-grafico de la rejilla no lleva ejes ni etiquetas por punto** —no hay sitio—;
en su lugar, la cabecera de cada tarjeta muestra el primer y el ultimo valor de la
ventana, tambien abreviados (ej. `859.2k → 1.1M`), como referencia minima sin necesidad
de interactividad.

**El eje de cada grafico encuadra el rango real de sus valores, no se fuerza a incluir
el cero.** La linea punteada de referencia en cero solo aparece si el cero cae dentro de
ese rango — ahi si importa, porque marca un cruce real: el signo sigue al debe y al
haber, asi que un importe neto puede pasar de positivo a negativo de un dia a otro.

**Se genera como imagen (PNG con matplotlib), no como SVG dentro del HTML**, por la
misma razon que el resto del correo: que se vea igual en el cuerpo del correo (donde
SVG inline no es fiable en todos los clientes, Outlook de escritorio el primero) y en
el PDF. Si la consulta de evolucion falla entera, el correo sale igual, sin esta
seccion.

### El PDF adjunto

Cada correo lleva adjunto un PDF: `partidas_pendientes_DBC_20260730.pdf`, o
`partidas_pendientes_todas_las_sociedades_20260730.pdf` para el consolidado. Fecha en
formato ISO para que al guardarlos en una carpeta se ordenen solos.

**Se genera con WeasyPrint a partir del MISMO HTML que se usaria para el correo.** Eso es
lo importante del diseno: hay una sola definicion del layout para cada bloque (resumen,
evolucion, seccion de sociedad, tabla de cuenta), asi que un cambio ahi no puede dejar el
PDF con una columna que el correo no tenga o al reves. La diferencia entre correo y PDF
esta solo en **cuales de esos bloques se incluyen**: en el consolidado, el PDF junta el
resumen, la evolucion y los 16 bloques completos; el cuerpo del correo lleva el resumen y
la evolucion, pero no los 16 bloques.

Encima de ese HTML se aplica una hoja de estilos que solo existe para el PDF
(`_estilos_pdf`): margenes de pagina, numeracion, se desmonta el marco de tarjeta —que en
papel roba ancho— y **se repite la fila de encabezado en cada hoja**. Eso ultimo aqui no es
un detalle: el reporte de `DBC` pasa de cien filas, y sin encabezados repetidos a partir de
la segunda pagina no se sabria que columna es cada una.

Va en **A4 horizontal**, al contrario que anticipos: son nueve columnas y una de ellas es
texto libre, que en vertical saldria partido en tres lineas.

Las tipografias del correo (Barlow, Segoe UI) no existen en el contenedor, asi que el
Dockerfile instala **Liberation Sans**, compatible en metricas con Arial —el ultimo recurso
de la pila del correo—, y **Pango**, que es lo que WeasyPrint usa para maquetar texto. Sin
fuentes instaladas el PDF saldria con cuadraditos.

**Si la generacion del PDF falla, el correo sale igual, sin adjunto y con un aviso en el
cuerpo.** El dato vale mas que el adjunto: un problema de tipografias no deberia dejar a
finanzas sin su reporte del dia. El motivo queda en el log.

## Filtro de fecha: partidas de ayer hacia atrás

Por defecto, el reporte incluye todas las partidas abiertas sin importar la fecha de
contabilización. Si estableces `PARTIDAS_SOLO_HASTA_AYER=true`, el proceso excluye las
partidas de hoy (fecha_contabilización = hoy), bajo la premisa de que cualquier partida
abierta hoy es un error de entrada reciente y no debería estar abierta aún.

Este filtro es reversible: es solo una variable de entorno, sin cambios al datos ni a
BigQuery. Úsalo con `gcloud run jobs execute` para una prueba:

```bash
gcloud run jobs execute partidas-pendientes-diario --region us-west4 \
  --update-env-vars PARTIDAS_SOLO_HASTA_AYER=true --wait
```

Si te gusta el resultado, lo activas permanentemente en el Job redeployando con
`deploy.sh` y agregando `export PARTIDAS_SOLO_HASTA_AYER=true` al `.env`.

### Destinatarios

Documento Firestore `lists/partidas_pendientes` en la base `proan-lista-mails`, con el
mismo modelo que `anticipos`:

| Campo | Tipo | |
|---|---|---|
| `globales` | array | Reciben **un** correo con las 16 sociedades |
| `por_sociedad` | map sociedad → array | Un correo por sociedad |
| `segmentada` | bool | `true`. Lo usa la app de Mailing-lists para editarla por grupos |
| `emails` | array | La union. **El proceso la ignora** |

La lista se gestiona desde la app de Mailing-lists, que ya entiende estos campos.

**Si Firestore no esta disponible** se cae a `PARTIDAS_EMAIL_TO` y luego a los
destinatarios por defecto del codigo, y en ese caso **se envia solo el correo global**:
nunca se adivina quien debe recibir los datos de una sociedad concreta.

El envio es por SendGrid, con el remitente en `to` y los destinatarios reales en `CC`.

### Horario

`0 10 * * 1-6` en `America/Mexico_City`: **de lunes a sabado a las 10:00 de Mexico**, media
hora despues del reporte de anticipos (a las 9:30). Si los dos salieran a la vez llegarian
mas de veinte correos de golpe y costaria distinguir cual es cual.

Mexico va a **UTC−6 todo el ano** desde 2022, asi que las 10:00 de Mexico son las
**16:00 UTC** y las **18:00 en Espana** en verano.

## Operacion

| Variable | Por defecto | |
|---|---|---|
| `SENDGRID_API_KEY` | — | Obligatoria salvo en dry run |
| `SENDGRID_FROM_EMAIL` | `noreply@proan.com` | Remitente verificado en SendGrid |
| `PARTIDAS_EMAIL_DRY_RUN` | `false` | `true` calcula y no envia |
| `PARTIDAS_ONLY_SOCIEDADES` | *(vacio)* | Recorta la ejecucion, para pruebas |
| `PARTIDAS_EMAIL_TO` | — | Solo si Firestore no tiene lista |
| `PARTIDAS_MAX_ANTIGUEDAD_HORAS` | `20` | Antiguedad tolerable del espejo. No es 6 como en anticipos: ver arriba |
| `PARTIDAS_SOLO_HASTA_AYER` | `false` | `true` excluye partidas de hoy (que deberían estar compensadas) |
| `PARTIDAS_DRY_RUN_DIR` | `salida_dry_run` | Donde deja el HTML en dry run |
| `FIRESTORE_DATABASE_ID` | `proan-lista-mails` | |
| `FIRESTORE_LISTS_COLLECTION` | `lists` | |
| `PARTIDAS_LIST_ID` | `partidas_pendientes` | |

### Probar sin enviar nada

`PARTIDAS_EMAIL_DRY_RUN=true` calcula, guarda en BigQuery y deja cada correo como un
fichero HTML en `salida_dry_run/`. Con `PARTIDAS_ONLY_SOCIEDADES=DBC,PAN` la prueba son tres
correos y no diecisiete.

En Cloud Run los ficheros se escriben pero mueren con el contenedor: alli el dry run vale
para validar el log, no para revisar el HTML. Para eso, ejecutarlo en local.

### Deploy

```bash
cp .env.example .env   # y rellena SENDGRID_API_KEY
bash deploy.sh
```

Construye la imagen, despliega el Cloud Run Job `partidas-pendientes-diario`, le inyecta
las variables y crea o actualiza el Cloud Scheduler.

**Cambiar `.env` no cambia nada en produccion hasta volver a ejecutar `deploy.sh`.**
Ejecutar el Job a mano usa la configuracion ya desplegada:

```bash
gcloud run jobs execute partidas-pendientes-diario --region us-west4 --wait
```

Para parar los envios sin desmontar nada:

```bash
gcloud scheduler jobs pause  partidas-pendientes-diario-scheduler --location us-west4
gcloud scheduler jobs resume partidas-pendientes-diario-scheduler --location us-west4
```

La *service account* del Job necesita leer `D00_SANDBOX`, escribir en `D60_REPORTING` y
leer Firestore.

## Pendiente

- **Completar los destinatarios reales** desde `CORREOS PARTIDAS ABIERTAS.xlsx`. Hoy la
  lista solo tiene direcciones de prueba.
- **Decidir si `ADE` entra.** Hoy no, y eso deja fuera las partidas mas antiguas del
  sistema, abiertas desde 2010.
- **Revisar el umbral de 90 dias** con quien use el reporte.

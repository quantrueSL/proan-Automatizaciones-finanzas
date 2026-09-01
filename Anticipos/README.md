# Reporte diario de anticipos

Cada dia, de lunes a sabado a las 9:30 de Mexico, calcula los anticipos a proveedores de
16 sociedades, guarda una foto en BigQuery y envia un correo por sociedad mas uno
consolidado. Sustituye el reporte que se sacaba a mano de SAP (`reportesEspeciales >
reportePartidasPendientes > Reporte anticipos`).

## Que es un anticipo

Un anticipo es dinero entregado a un proveedor **antes** de que exista factura que lo
justifique. Su cuenta queda con **saldo deudor**: es el proveedor quien debe, en forma de
mercancia o servicio pendiente de entregar. Contablemente es un **activo**.

El saldo de un proveedor se calcula con el indicador de debe o haber, `SHKZG`:

```
saldo = SUMA( +DMBTR si SHKZG='S' (debe) ,  -DMBTR si SHKZG='H' (haber) )
```

`DMBTR` va siempre en **moneda local**, pesos mexicanos, aunque el documento original
estuviera en dolares o euros. Por eso se pueden sumar apuntes de distintas divisas sin
convertir nada. Entran tanto los saldos positivos como los negativos: el cliente quiere
ver tambien los anticipos que salen en negativo, aunque no representen dinero pendiente
de aplicar. Solo se excluye un saldo exactamente en cero.

## Solo entran los anticipos formales (`UMSKZ = 'A'`)

`UMSKZ` es el indicador de cuenta especial de SAP, y es lo que distingue conceptos que no
se pueden mezclar:

| `UMSKZ` | Que es | Cuentas | En el reporte |
|---|---|---|---|
| *(vacio)* | **Partida normal de proveedor.** Facturas y pagos corrientes. Su saldo neto es deudor solo si se ha pagado de mas | **Pasivo**: `20101xx`, `2020xxx`, `2111xx` | **No** — se quito el 2026-08-27 a peticion del usuario (antes salia como «Saldos deudores en cuentas de proveedor») |
| `A` | **Anticipo formal.** Registrado en SAP declarandolo como anticipo | **Activo**: `10801xx`, `0000140110` | **Si**, como «Anticipos a proveedores», incluidos los que salen con saldo negativo |
| `F` | **Solicitud de anticipo.** Apunte estadistico para planificar pagos. No representa dinero movido | Las mismas que `A` | **No** |
| `H` | Otros indicadores especiales | `0000140810` | **No** |

Los **`'F'`** quedan fuera porque son una anotacion, no un saldo: sumarlos a un `'A'` real
seria contar el mismo anticipo dos veces.

Hasta 2026-08-27 el reporte tambien incluia los saldos deudores con `UMSKZ` vacio
(anticipos de hecho: nadie los declaro, simplemente se pago mas de lo debido). Se
quitaron para que el reporte sea solo de los anticipos formales.

## De donde sale el dato

| | |
|---|---|
| Partidas | `D00_SANDBOX.bsik_real_time`, espejo de **BSIK** de SAP |
| Nombres de proveedor | `D20_DIMENSION.dm_vendors`, campo `razon_social` |
| Nombres de sociedad | `D20_DIMENSION.dm_company`, `company_code` → `company_name` |

**BSIK contiene solo partidas abiertas.** Cuando una factura se paga o un anticipo se
aplica, el apunte **desaparece** de BSIK: no se marca como cerrado.


### Campos que se usan

| Campo | |
|---|---|
| `BUKRS` | Sociedad |
| `LIFNR` | Numero de acreedor, con ceros por delante: `0000019801`. `LTRIM` lo deja en `19801` |
| `HKONT` | Cuenta de mayor |
| `UMSKZ` | Indicador de cuenta especial |
| `SHKZG` | Debe (`S`) o haber (`H`) |
| `DMBTR` | Importe en moneda local |
| `_ingested_at` | Cuando el replicador escribio la fila |

## La consulta

```sql
WITH saldos AS (
  SELECT
    BUKRS AS sociedad,
    IFNULL(HKONT, '') AS cuenta,
    LTRIM(LIFNR, '0') AS proveedor,
    ROUND(SUM(
      CASE WHEN SHKZG = 'S' THEN  CAST(DMBTR AS NUMERIC)
           ELSE                  -CAST(DMBTR AS NUMERIC)
      END
    ), 2) AS saldo_neto
  FROM `proan-quantrue.D00_SANDBOX.bsik_real_time`
  WHERE UMSKZ = 'A'
    AND BUKRS IN UNNEST(@sociedades)
  GROUP BY sociedad, cuenta, proveedor
),
proveedores AS (
  SELECT
    LTRIM(id_proveedor, '0') AS proveedor,
    ANY_VALUE(razon_social) AS razon_social
  FROM `proan-quantrue.D20_DIMENSION.dm_vendors`
  WHERE razon_social IS NOT NULL AND razon_social != ''
  GROUP BY proveedor
)
SELECT s.sociedad,
       'anticipo' AS tipo,
       s.cuenta, s.proveedor,
       IFNULL(p.razon_social, '(sin nombre en la maestra)') AS nombre_proveedor,
       s.saldo_neto
FROM saldos s
LEFT JOIN proveedores p USING (proveedor)
WHERE s.saldo_neto != 0
ORDER BY s.sociedad, s.saldo_neto DESC
```

Cuatro detalles que no son opcionales:

- **Entran positivos y negativos.** Solo se excluye un saldo exactamente en cero, que no
  es nada que reportar. El cliente quiere ver tambien los anticipos que salen en negativo.
- **`CAST(DMBTR AS NUMERIC)`.** En el espejo `DMBTR` es `FLOAT`, y sumar dinero en coma
  flotante arrastra error. `NUMERIC` es aritmetica decimal exacta.
- **`dm_vendors` se deduplica antes de cruzar.** Tiene una fila por direccion, no por
  proveedor: 25.147 filas para 23.155 proveedores. Sin el `GROUP BY`, el cruce
  multiplicaria filas e inflaria los totales del correo.
- **No se filtra por cuenta de mayor.** El anticipo lo define el signo del saldo. Las
  cuentas que aparezcan en un reporte concreto son las que tenian saldo ese dia en esa
  sociedad, no una lista cerrada. La cuenta se muestra como columna informativa.

**`UMSKZ` ya no hace falta en el `GROUP BY`.** Hasta 2026-08-27 el filtro admitia `UMSKZ`
vacio o `'A'`, y agrupar solo por cuenta habria mezclado un anticipo formal con su propia
solicitud (`'F'`, que comparte cuenta con `'A'`). Al filtrar ya `UMSKZ = 'A'` en el propio
`WHERE`, las filas `'F'` ni entran en el calculo.

## Control de frescura

Antes de calcular nada, el proceso mira `MAX(_ingested_at)` y **falla** si el espejo tiene
mas de `ANTICIPOS_MAX_ANTIGUEDAD_HORAS` horas (6 por defecto).

Si el replicador de SAP se para, la tabla no se vacia ni avisa: se queda con la ultima
copia buena. Sin este control el reporte saldria cada dia con la misma cara. Un Cloud Run
Job en rojo se ve; un correo con datos viejos, no.

## Sociedades

Las 16 del Excel de correos, en ese orden:

```
PAN DBC ROMM PRA MPE MAL HEGP ISE PIN SAP ABP AME CCP PAL PAT BAG
```

En `bsik_real_time` hay 23; quedan fuera a proposito `ADE`, `FAG`, `FEF`, `GSI`, `PFO`,
`SCO` y `SCO1`.

Una sociedad sin anticipos **recibe su correo igualmente**, con un «Sin anticipos
pendientes»: el silencio no se distingue de un proceso roto.

## Las facturas pendientes de pago no son de este reporte

Las partidas de proveedor con saldo neto negativo y `UMSKZ` vacio son **facturas
pendientes de pago**, no anticipos. No se llegan a consultar: el filtro de este reporte
es `UMSKZ = 'A'`, y esas partidas tienen `UMSKZ` vacio. Corresponden a la automatizacion
`Partidas abiertas por compensar`, que va por otro camino (`bsis_real_time`, todas las
clases de documento, cuentas terminadas en `I`).

## Tabla de salida

`proan-quantrue.D60_REPORTING.Anticipos_evolucion`, particionada por dia en
`fecha_reporte` y agrupada por `sociedad`.

| Campo | Tipo | |
|---|---|---|
| `fecha_reporte` | DATE | Fecha de Mexico de la ejecucion |
| `sociedad` | STRING | `BUKRS` |
| `tipo` | STRING | Siempre `anticipo`. Se conserva por continuidad historica: las filas anteriores a 2026-08-27 tambien tenian `saldo_deudor` |
| `cuenta` | STRING | `HKONT`. Cadena vacia si el apunte no la trae |
| `proveedor` | STRING | `LIFNR` sin ceros de relleno |
| `nombre_proveedor` | STRING | `razon_social` de `dm_vendors` |
| `saldo_neto` | NUMERIC | Positivo o negativo |
| `actualizado_en` | DATETIME | Hora de Mexico de la ejecucion |

**Es la unica historia que existe.** BSIK solo tiene partidas abiertas, el espejo se
reescribe cada dos horas y `bsak_real_time` esta vacia: sin esta tabla no hay forma de
saber que un anticipo existio ni cuanto tiempo estuvo abierto. Cuesta del orden de decenas
de filas al dia.

Se escribe con el **decorador de particion** (`Anticipos_evolucion$YYYYMMDD`) y
`WRITE_TRUNCATE`, que reemplaza la foto del dia entera de forma atomica. No sirve un
`MERGE` por clave: si un anticipo estaba esta manana y ya no esta, su fila **tiene que
desaparecer** de la foto, y un `MERGE` actualiza e inserta pero no borra lo que dejo de
existir.

**Tambien se lee**, no solo se escribe: la columna «Total ayer» del resumen del correo
consolidado (ver «El correo» mas abajo) sale de releer esta misma tabla con
`fecha_reporte = ayer`, agrupado por sociedad.

## El correo

Cada sociedad aparece con su **codigo y su razon social**: «Sociedad PAN - Proteina Animal
SA de CV», en el titulo del bloque, en la cabecera del correo y en la tabla resumen del
consolidado. El asunto se queda solo con el codigo, para no alargarlo, y el nombre del PDF
tambien.

El nombre sale de `dm_company`. Ahi `company_code` **es unico** —87 filas y 87 codigos—,
asi que el cruce no necesita deduplicar, al contrario que el de `dm_vendors`. La columna
`company` de esa tabla esta vacia en las 87 filas: la buena es `company_name`.

**Si el maestro de sociedades falla, el reporte sale con los codigos a secas.** El nombre
es una comodidad de lectura, no un dato del reporte: no tiene sentido dejar a finanzas sin
su correo porque una tabla de referencia no responda. Si el maestro responde pero le falta
un codigo concreto, ese aparece como «(sin nombre en la maestra)», igual que se hace con los
proveedores.

Cada bloque de sociedad presenta el detalle de sus anticipos — cuenta, proveedor, nombre y
saldo, ordenado de mayor a menor —, su total, y el **total de ayer** de esa sociedad. Si
no tiene ningun anticipo hoy, sale un «Sin anticipos pendientes» seguido igualmente del
total de ayer: que hoy este vacio y ayer no lo estuviera es justo el cambio que se quiere
ver de un vistazo.

Se envian dos tipos de correo:

- **Uno por sociedad**, con el bloque de detalle de esa sociedad (y su total de ayer) en
  el propio cuerpo del correo.
- **Uno consolidado** con las 16. **El cuerpo de este correo lleva solo el resumen**
  (sociedad, total de hoy y total de ayer) con una nota de que el detalle esta en el PDF
  adjunto — no los 16 bloques uno detras de otro, que harian un correo kilometrico para
  quien sigue todas las sociedades a la vez. El PDF adjunto si lleva el resumen y las 16
  bloques completos, exactamente igual que si se mandaran los 16 correos individuales
  seguidos.

**«Total ayer» esta a nivel de sociedad, no de linea**: comparar linea a linea exigiria
cruzar por proveedor y cuenta entre dos dias, y como los anticipos aparecen y se resuelven
todo el tiempo, la mayoria de lineas saldrian sin dato. A nivel de sociedad el numero si
es estable y comparable dia a dia.

Sale de releer `Anticipos_evolucion` con `fecha_reporte = ayer` (ver «Tabla de salida»
mas arriba). Una sociedad sin fila para ayer se trata como que no tenia anticipos ese
dia (0,00), no como un error. **Si la relectura entera falla**, la columna y todas las
lineas de «Total ayer» salen con «-»: el resto del correo se envia igual, sin dato de ayer
no deja de ser el reporte de hoy.

### El grafico de evolucion

Cada correo lleva ademas un grafico de linea con los ultimos **7 dias CON foto**
(`EVOL_DIAS`, `consultar_evolucion_reciente`), no 7 dias de calendario: si un domingo
no hay particion (el Job corre de lunes a sabado) o un run cualquiera falla, ese dia se
salta en vez de dibujarse como una caida a cero que no paso.

- **Correo consolidado**: el total de las 16 sociedades como grafico grande de
  cabecera, y debajo una rejilla con un mini-grafico por sociedad — **cada uno a su
  propia escala**. Es la solucion al problema de fondo: PAN puede andar en cientos de
  millones y HEGP en cientos de pesos el mismo dia, y un unico grafico con las 16
  lineas dejaria a HEGP como una raya plana pegada al cero. Con un panel por sociedad,
  cada una se lee bien sola. Una sociedad sin ningun anticipo en toda la ventana no
  sale en la rejilla.
- **Correo por sociedad**: la serie de esa sociedad como grafico grande, sin el
  problema anterior —solo hay una escala de por medio.

**El grafico grande** (total del consolidado, o serie del correo por sociedad) lleva el
eje de fechas debajo de cada punto y, encima o debajo de la propia linea, el valor de
ese punto en formato abreviado (1.1M, 859.2k): en un correo no se puede pasar el raton
por encima de un punto para verlo, asi que el dato va escrito, con un halo blanco detras
para que no se pierda cruzado por la propia linea.

**El mini-grafico de la rejilla no lleva ejes ni etiquetas por punto** —no hay sitio—;
en su lugar, la cabecera de cada tarjeta muestra el primer y el ultimo valor de la
ventana, tambien abreviados (ej. `859.2k → 1.1M`), como referencia minima sin necesidad
de interactividad.

**El eje de cada grafico encuadra el rango real de sus valores, no se fuerza a incluir
el cero.** Una serie que se mueve entre 990M y 1040M tiene que verse como una linea que
sube y baja, no como un hilo aplastado contra el techo de un eje que llega hasta cero.
La linea punteada de referencia en cero solo aparece si el cero cae dentro de ese rango
— ahi si importa, porque marca un cruce real (saldo que pasa de positivo a negativo).

**Se genera como imagen (PNG con matplotlib), no como SVG dentro del HTML.** El SVG
inline no es fiable en todos los clientes de correo —Outlook de escritorio el
primero—, y generar la imagen una sola vez evita que el cuerpo del correo y el PDF
puedan acabar con dos dibujos ligeramente distintos.

Si la consulta de evolucion falla entera, el correo sale igual, sin esta seccion: es un
complemento del reporte, no un dato que valga la pena bloquear el envio por el.

### El PDF adjunto

Cada correo lleva adjunto un PDF: `anticipos_PAL_20260730.pdf`, o
`anticipos_todas_las_sociedades_20260730.pdf` para el consolidado. Fecha en formato ISO para
que al guardarlos en una carpeta se ordenen solos.

**Se genera con WeasyPrint a partir del MISMO HTML que se usaria para el correo.** Eso es
lo importante del diseno: hay una sola definicion del layout para cada bloque (resumen,
evolucion, seccion de sociedad, tabla de detalle), asi que un cambio ahi no puede dejar
el PDF con una columna que el correo no tenga o al reves. La unica diferencia entre
correo y PDF es **cuales de esos bloques se incluyen**: en el consolidado, el PDF junta
el resumen, la evolucion y los 16 bloques completos; el cuerpo del correo lleva el
resumen y la evolucion, pero no los 16 bloques, para no mandar un correo kilometrico a
quien sigue las 16 sociedades a la vez.

Encima de ese HTML se aplica una hoja de estilos que solo existe para el PDF
(`_estilos_pdf`): margenes de pagina, numeracion, se desmonta el marco de tarjeta —que en
papel roba ancho— y **se repite la fila de encabezado en cada hoja**, porque a partir de la
segunda pagina las columnas se quedarian sin nombre. Va en **A4 vertical**: con cuatro
columnas cabe de sobra.

Las tipografias del correo (Barlow, Segoe UI) no existen en el contenedor, asi que el
Dockerfile instala **Liberation Sans**, compatible en metricas con Arial —el ultimo recurso
de la pila del correo—, y **Pango**, que es lo que WeasyPrint usa para maquetar texto. Sin
fuentes instaladas el PDF saldria con cuadraditos.

**Si la generacion del PDF falla, el correo sale igual, sin adjunto y con un aviso en el
cuerpo.** El dato vale mas que el adjunto: un problema de tipografias no deberia dejar a
finanzas sin su reporte del dia. El motivo queda en el log.

### Destinatarios

Documento Firestore `lists/anticipos` en la base `proan-lista-mails`:

| Campo | Tipo | |
|---|---|---|
| `globales` | array | Reciben **un** correo con las 16 sociedades |
| `por_sociedad` | map sociedad → array | Un correo por sociedad |
| `emails` | array | La union. **El proceso la ignora**; existe para que la interfaz de Mailing-lists considere la lista activa |
| `kind` | string | `mailing` |
| `enabled` | bool | |

Hay direcciones que estan en todas las sociedades. Esas van en `globales` y **reciben un
unico correo con todas las sociedades juntas**, en vez de uno por cada una.

Quien esta en `globales` se declara, no se deduce de `por_sociedad`, para que el
comportamiento no cambie solo porque alguien entre o salga de una sociedad.

Las direcciones se normalizan al leerlas, asi que la lista acepta tanto
`alguien@proan.com` como `Nombre Apellido <alguien@proan.com>`. Se descartan las repetidas
sin distinguir mayusculas, las vacias y las que no son una direccion.

**Si Firestore no esta disponible** se cae a `ANTICIPOS_EMAIL_TO` y luego a los
destinatarios por defecto del codigo, y en ese caso **se envia solo el correo global**:
nunca se adivina quien debe recibir los datos de una sociedad concreta.

El envio es por SendGrid, con el remitente en `to` y los destinatarios reales en `CC`,
igual que en `Cambio divisa`.

### Horario

`30 9 * * 1-6` en `America/Mexico_City`. Mexico va a **UTC−6 todo el ano** desde 2022, asi
que las 9:30 de Mexico son las **15:30 UTC** y las **17:30 en Espana** en verano. El
espejo se recarga cada dos horas, asi que a esa hora el dato es del mismo dia.

## Operacion

| Variable | Por defecto | |
|---|---|---|
| `SENDGRID_API_KEY` | — | Obligatoria salvo en dry run |
| `SENDGRID_FROM_EMAIL` | `noreply@proan.com` | Remitente verificado en SendGrid |
| `ANTICIPOS_EMAIL_DRY_RUN` | `false` | `true` calcula y no envia |
| `ANTICIPOS_ONLY_SOCIEDADES` | *(vacio)* | Recorta la ejecucion, para pruebas |
| `ANTICIPOS_EMAIL_TO` | — | Solo si Firestore no tiene lista |
| `ANTICIPOS_MAX_ANTIGUEDAD_HORAS` | `6` | Antiguedad tolerable del espejo |
| `ANTICIPOS_DRY_RUN_DIR` | `salida_dry_run` | Donde deja el HTML en dry run |
| `FIRESTORE_DATABASE_ID` | `proan-lista-mails` | |
| `FIRESTORE_LISTS_COLLECTION` | `lists` | |
| `ANTICIPOS_LIST_ID` | `anticipos` | |

### Probar sin enviar nada

`ANTICIPOS_EMAIL_DRY_RUN=true` calcula, guarda en BigQuery y deja cada correo como un
fichero HTML en `salida_dry_run/`. Con `ANTICIPOS_ONLY_SOCIEDADES=PAL,PAN` la prueba son
tres correos y no diecisiete.

En Cloud Run los ficheros se escriben pero mueren con el contenedor: alli el dry run vale
para validar el log, no para revisar el HTML. Para eso, ejecutarlo en local.

### Deploy

```bash
cp .env.example .env   # y rellena SENDGRID_API_KEY
bash deploy.sh
```

Construye la imagen, despliega el Cloud Run Job `anticipos-diario`, le inyecta las
variables y crea o actualiza el Cloud Scheduler.

**Cambiar `.env` no cambia nada en produccion hasta volver a ejecutar `deploy.sh`.**
Ejecutar el Job a mano usa la configuracion ya desplegada:

```bash
gcloud run jobs execute anticipos-diario --region us-west4 --wait
```

Para parar los envios sin desmontar nada:

```bash
gcloud scheduler jobs pause  anticipos-diario-scheduler --location us-west4
gcloud scheduler jobs resume anticipos-diario-scheduler --location us-west4
```

La *service account* del Job necesita leer `D00_SANDBOX` y `D20_DIMENSION`, escribir en
`D60_REPORTING` y leer Firestore.

## Pendiente

- **Avisar a quien reciba el correo de que ya no incluye los saldos deudores** (`UMSKZ`
  vacio), que se quitaron el 2026-08-27 a peticion del usuario. El reporte ahora es solo
  de anticipos formales (`UMSKZ = 'A'`), y el importe total va a bajar respecto a lo que
  llegaba antes.
- **Parchear la app de Mailing-lists** para que gestione `globales` y `por_sociedad`.
  Mientras no lo haga: **no abrir la lista `anticipos` en la interfaz y darle a Guardar**,
  porque `save_list` escribe el documento completo con `set()` sin `merge` y borraria los
  dos campos, dejando el reporte sin destinatarios en silencio. El aviso esta tambien en el
  `comment` del documento.
- **Completar los destinatarios reales.** Hoy la lista solo tiene direcciones de prueba. Al
  pasarlas del Excel hay tres cosas que revisar: una direccion con el dominio mal escrito,
  un correo personal de gmail entre los destinatarios, y alguna con un espacio al final. El
  proceso normaliza espacios y formato, pero un dominio con errata no lo puede adivinar.

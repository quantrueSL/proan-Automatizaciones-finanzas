# Reporte diario de anticipos

Cada dia, de lunes a sabado a las 10:00 de Mexico, calcula los anticipos a proveedores de
16 sociedades, guarda una foto en BigQuery y envia un correo por sociedad mas uno
consolidado. Sustituye el reporte que se sacaba a mano de SAP (`reportesEspeciales >
reportePartidasPendientes > Reporte anticipos`).

## Que es un anticipo

Un anticipo es dinero entregado a un proveedor **antes** de que exista factura que lo
justifique, o pagado **de mas**. Su cuenta queda con **saldo deudor**: es el proveedor
quien debe, en forma de mercancia o servicio pendiente de entregar. Contablemente es un
**activo**.

El saldo de un proveedor se calcula con el indicador de debe o haber, `SHKZG`:

```
saldo = SUMA( +DMBTR si SHKZG='S' (debe) ,  -DMBTR si SHKZG='H' (haber) )
```

`DMBTR` va siempre en **moneda local**, pesos mexicanos, aunque el documento original
estuviera en dolares o euros. Por eso se pueden sumar apuntes de distintas divisas sin
convertir nada. **Si el saldo sale positivo, hay anticipo.**

## Los cuatro valores de `UMSKZ`

`UMSKZ` es el indicador de cuenta especial de SAP, y es lo que distingue conceptos que no
se pueden mezclar:

| `UMSKZ` | Que es | Cuentas | En el reporte |
|---|---|---|---|
| *(vacio)* | **Partida normal de proveedor.** Facturas y pagos corrientes. Su saldo neto es deudor solo si se ha pagado de mas | **Pasivo**: `20101xx`, `2020xxx`, `2111xx` | **Si**, como «Saldos deudores en cuentas de proveedor» |
| `A` | **Anticipo formal.** Registrado en SAP declarandolo como anticipo | **Activo**: `10801xx`, `0000140110` | **Si**, como «Anticipos a proveedores» |
| `F` | **Solicitud de anticipo.** Apunte estadistico para planificar pagos. No representa dinero movido | Las mismas que `A` | **No** |
| `H` | Otros indicadores especiales | `0000140810` | **No** |

Las dos que entran son conceptos distintos y van en **secciones separadas del correo**,
cada una con su total:

- Los **`'A'`** son anticipos declarados: alguien los registro como tal, en cuentas de
  activo de anticipos a proveedores.
- Los **saldos deudores con `UMSKZ` vacio** son anticipos de hecho: nadie los declaro,
  simplemente se pago mas de lo debido y una cuenta de pasivo quedo en positivo. 

Los **`'F'`** quedan fuera porque son una anotacion, no un saldo: sumarlos a un `'A'` real
seria contar el mismo anticipo dos veces.

## De donde sale el dato

| | |
|---|---|
| Partidas | `D00_SANDBOX.bsik_real_time`, espejo de **BSIK** de SAP |
| Nombres | `D20_DIMENSION.dm_vendors`, campo `razon_social` |

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
    IFNULL(UMSKZ, '') AS umskz,
    IFNULL(HKONT, '') AS cuenta,
    LTRIM(LIFNR, '0') AS proveedor,
    ROUND(SUM(
      CASE WHEN SHKZG = 'S' THEN  CAST(DMBTR AS NUMERIC)
           ELSE                  -CAST(DMBTR AS NUMERIC)
      END
    ), 2) AS saldo_neto
  FROM `proan-quantrue.D00_SANDBOX.bsik_real_time`
  WHERE IFNULL(UMSKZ, '') IN ('', 'A')
    AND BUKRS IN UNNEST(@sociedades)
  GROUP BY sociedad, umskz, cuenta, proveedor
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
       IF(s.umskz = 'A', 'anticipo', 'saldo_deudor') AS tipo,
       s.cuenta, s.proveedor,
       IFNULL(p.razon_social, '(sin nombre en la maestra)') AS nombre_proveedor,
       s.saldo_neto
FROM saldos s
LEFT JOIN proveedores p USING (proveedor)
WHERE s.saldo_neto > 0
ORDER BY s.sociedad, tipo, s.saldo_neto DESC
```

Cuatro detalles que no son opcionales:

- **`UMSKZ` va en el `GROUP BY`, no solo en el `WHERE`.** `'A'` y `'F'` comparten cuenta de
  mayor, asi que agrupar solo por cuenta mezclaria un anticipo con su propia solicitud.
- **`CAST(DMBTR AS NUMERIC)`.** En el espejo `DMBTR` es `FLOAT`, y sumar dinero en coma
  flotante arrastra error. `NUMERIC` es aritmetica decimal exacta.
- **`dm_vendors` se deduplica antes de cruzar.** Tiene una fila por direccion, no por
  proveedor: 25.147 filas para 23.155 proveedores. Sin el `GROUP BY`, el cruce
  multiplicaria filas e inflaria los totales del correo.
- **No se filtra por cuenta de mayor.** El anticipo lo define el signo del saldo. Las
  cuentas que aparezcan en un reporte concreto son las que tenian saldo ese dia en esa
  sociedad, no una lista cerrada. La cuenta se muestra como columna informativa.

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

Una sociedad sin anticipos de ninguno de los dos tipos **recibe su correo igualmente**, con
un «Sin anticipos pendientes»: el silencio no se distingue de un proceso roto.

## Los saldos negativos no son de este reporte

Al separar por signo, el lado negativo resulta ser dos o tres ordenes de magnitud mayor y
con muchas mas filas: son las **facturas pendientes de pago**. Corresponden a la
automatizacion `Partidas abiertas por compensar`, que va por otro camino
(`bsis_real_time`, clase `ZR`, cuentas terminadas en `I`).

## Tabla de salida

`proan-quantrue.D60_REPORTING.Anticipos_evolucion`, particionada por dia en
`fecha_reporte` y agrupada por `sociedad`.

| Campo | Tipo | |
|---|---|---|
| `fecha_reporte` | DATE | Fecha de Mexico de la ejecucion |
| `sociedad` | STRING | `BUKRS` |
| `tipo` | STRING | `anticipo` (`UMSKZ = 'A'`) o `saldo_deudor` (`UMSKZ` vacio) |
| `cuenta` | STRING | `HKONT`. Cadena vacia si el apunte no la trae |
| `proveedor` | STRING | `LIFNR` sin ceros de relleno |
| `nombre_proveedor` | STRING | `razon_social` de `dm_vendors` |
| `saldo_neto` | NUMERIC | Siempre positivo |
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

## El correo

Cada sociedad se presenta con sus dos secciones — **Anticipos a proveedores** y **Saldos
deudores en cuentas de proveedor** — cada una con detalle de cuenta, proveedor, nombre y
saldo, ordenado de mayor a menor, y su total. Debajo, el total combinado, que solo aparece
si hay las dos secciones.

Se envian dos tipos de correo:

- **Uno por sociedad**, con las dos secciones de esa sociedad.
- **Uno consolidado** con las 16, que empieza con un resumen (sociedad, total de anticipos,
  total de saldos deudores, total combinado y total general) y sigue con el detalle.

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

`0 10 * * 1-6` en `America/Mexico_City`. Mexico va a **UTC−6 todo el ano** desde 2022, asi
que las 10:00 de Mexico son las **16:00 UTC** y las **18:00 en Espana** en verano. El
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

- **Avisar a contabilidad de que el reporte incluye los `UMSKZ = 'A'`**, que el manual no
  mostraba. El importe total es un orden de magnitud mayor que el de siempre, y conviene
  que lo sepan antes de encontrarselo. Las dos secciones estan separadas para que se pueda
  comparar con lo que llegaba antes.
- **Parchear la app de Mailing-lists** para que gestione `globales` y `por_sociedad`.
  Mientras no lo haga: **no abrir la lista `anticipos` en la interfaz y darle a Guardar**,
  porque `save_list` escribe el documento completo con `set()` sin `merge` y borraria los
  dos campos, dejando el reporte sin destinatarios en silencio. El aviso esta tambien en el
  `comment` del documento.
- **Completar los destinatarios reales.** Hoy la lista solo tiene direcciones de prueba. Al
  pasarlas del Excel hay tres cosas que revisar: una direccion con el dominio mal escrito,
  un correo personal de gmail entre los destinatarios, y alguna con un espacio al final. El
  proceso normaliza espacios y formato, pero un dominio con errata no lo puede adivinar.

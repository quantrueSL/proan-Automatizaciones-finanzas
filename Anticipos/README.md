# Reporte diario de anticipos

Sustituye el reporte que se sacaba a mano de SAP (`reportesEspeciales >
reportePartidasPendientes > Reporte anticipos`). Calcula los anticipos por sociedad,
guarda una foto diaria en BigQuery y envia el resultado por correo.

## Que se considera un anticipo

**El saldo deudor de un proveedor en partidas abiertas**: un proveedor al que se le ha
pagado mas de lo que se le debe.

Se calcula sobre `D00_SANDBOX.bsik_real_time` (partidas abiertas de acreedores),
agrupando por sociedad + cuenta de mayor + proveedor, con el signo que marca `SHKZG`
(`S` debe suma, `H` haber resta), y quedandose solo con los saldos positivos.

## Decisiones y por que

### Solo partidas normales: se excluye `UMSKZ`

SAP maneja dos conceptos distintos bajo la palabra anticipo:

| `UMSKZ` | Que es | Cuentas | Incluido |
|---|---|---|---|
| *(vacio)* | Partidas normales de proveedor | `2010102`, `2010103`, `2010104`… | **Si** |
| `A` | Anticipo formal, *down payment* | `1080102`, `1080103`, `1080100` | No |
| `F` | Solicitud de anticipo, apunte estadistico | las mismas que `A` | No |

El reporte manual que se automatiza **no incluye los `UMSKZ = 'A'`**, y este proceso
tampoco, para dar exactamente el mismo numero que hoy circula por finanzas. Los `'A'`
son anticipos en el sentido contable estricto y son unas 592 partidas, asi que
**merece la pena que contabilidad revise esta decision**. Si deben entrar, es anadir
una seccion al reporte.

Si algun dia se incluyen: `'A'` y `'F'` **comparten cuenta de mayor**, asi que agrupar
sin distinguir `UMSKZ` sumaria un anticipo con su propia solicitud de anticipo y
contaria doble. Se comprobo que hoy pasaria en 42 grupos.

### No se filtra por cuenta de mayor

El reporte manual muestra `2010102/2010103/2010104`, pero esas son simplemente las
cuentas donde caen los saldos deudores hoy, no una definicion. Al revisarlo aparecieron
5 filas de anticipo en cuentas que ese filtro dejaria fuera (`2010300`, `2010100`,
`2010150`, `2020203`). Se filtra por signo y la cuenta se muestra como columna, asi que
una cuenta nueva entra sin tocar codigo.

### El nombre del proveedor sale de `dm_vendors`

`D20_DIMENSION.dm_vendors` cubre el 100% de los proveedores de BSIK y tiene un nombre de
tabla estable. La alternativa, `LFA1`, vive en snapshots con la fecha en el nombre
(`proan_LFA1_20260728`, mas de 400 de ellos), que obligaria a construir el nombre de
tabla en cada ejecucion.

**`dm_vendors` tiene una fila por direccion, no por proveedor**: 25.147 filas para
23.155 proveedores. Por eso se deduplica antes de cruzar. Sin ese `GROUP BY` el cruce
multiplicaria filas de anticipo e inflaria los totales del correo.

### `DMBTR` se convierte a `NUMERIC` antes de sumar

En la tabla espejo `DMBTR` es `FLOAT`. Sumar dinero en coma flotante arrastra error;
`NUMERIC` es aritmetica decimal exacta.

### Se aborta si el espejo esta caducado

`bsik_real_time` **no la carga el Airflow del DWH**. El DAG `proan_produccion` solo la
lee; la escribe un replicador de SAP externo que **reescribe la tabla entera cada dos
horas** (todas las filas comparten marca de `_ingested_at`, y no hay ni un dia de
historia). Si ese replicador se para, la tabla se queda con datos viejos sin avisar.

Antes de enviar nada se mira la antiguedad de la ultima carga y el proceso **falla** si
pasa de `ANTICIPOS_MAX_ANTIGUEDAD_HORAS` (6 por defecto), en vez de mandar un reporte
caducado como si fuera del dia.

Por la misma razon **no se usa `D30_INTEGRATION.sap_bsik_open_items`**, que es la version
curada: cuando se reviso iba dos dias por detras.

## Tabla de salida

`proan-quantrue.D60_REPORTING.Anticipos_evolucion`, particionada por dia en
`fecha_reporte` y agrupada por `sociedad`.

| Campo | Tipo | |
|---|---|---|
| `fecha_reporte` | DATE | Fecha de Mexico en la que se ejecuta |
| `sociedad` | STRING | `BUKRS` |
| `cuenta` | STRING | `HKONT`. Cadena vacia si el apunte no la trae |
| `proveedor` | STRING | `LIFNR` sin los ceros de relleno |
| `nombre_proveedor` | STRING | `razon_social` de `dm_vendors` |
| `saldo_neto` | NUMERIC | Siempre positivo |
| `actualizado_en` | DATETIME | Hora de Mexico de la ejecucion |

**Es la unica historia que existe.** BSIK solo contiene partidas **abiertas**: cuando un
anticipo se compensa la fila desaparece, el espejo se reescribe cada dos horas y
`bsak_real_time` (donde SAP guardaria las compensadas) esta **vacia** en BigQuery. Sin
esta tabla no hay forma de saber que un anticipo existio ni cuanto tiempo estuvo abierto.

La escritura usa el decorador de particion (`tabla$YYYYMMDD`) con `WRITE_TRUNCATE`, asi
que **reejecutar el proceso el mismo dia reemplaza la foto del dia entera**, sin
duplicados ni restos de un calculo anterior.

## Sociedades

Las 16 del reporte, en el orden de las columnas del Excel de correos:

```
PAN DBC ROMM PRA MPE MAL HEGP ISE PIN SAP ABP AME CCP PAL PAT BAG
```

En `bsik_real_time` hay 23 sociedades; las 7 restantes (`ADE`, `FAG`, `FEF`, `GSI`,
`PFO`, `SCO`, `SCO1`) quedan fuera a proposito.

Una sociedad sin anticipos **recibe su correo igualmente**, indicando que no hay
ninguno. Es informacion, no un fallo, y el silencio no se distingue de un proceso roto.

## Destinatarios

Documento Firestore `lists/anticipos` en la base `proan-lista-mails`, con dos bloques
**declarados de forma explicita**:

| Campo | Tipo | |
|---|---|---|
| `globales` | array | Reciben **un** correo con las 16 sociedades |
| `por_sociedad` | map sociedad → array | Un correo por sociedad |

Se declara en vez de deducirse. La alternativa era mirar quien aparece en las 16
sociedades y mandarle uno solo, pero entonces **el dia que alguien sale de una sociedad
su comportamiento cambiaria en silencio de un correo a quince**.

Hace falta porque hay direcciones en las 16 columnas del Excel de origen
(`divisas@proan.com`, `tesoreria@proan.com`, `luisenrique.romo@proan.com`): con un correo
por sociedad recibirian 16 cada manana.

Las direcciones se normalizan al leerlas, asi que acepta tanto `alguien@proan.com` como
`Nombre Apellido <alguien@proan.com>`, que es el formato del Excel. Se descartan las
repetidas sin distinguir mayusculas y las que no son una direccion.

Si Firestore no esta disponible se cae a `ANTICIPOS_EMAIL_TO` y luego a los
destinatarios por defecto del codigo, y en ese caso **se envia solo el correo global**:
nunca se adivina quien debe recibir los datos de una sociedad concreta.

El envio es por SendGrid, con el remitente en `to` y los destinatarios reales en `CC`,
igual que en `Cambio divisa`.

## Frecuencia

`0 10 * * 1-6` en `America/Mexico_City`: **de lunes a sabado a las 10:00 de Mexico**. El
espejo se recarga cada dos horas, asi que a esa hora el dato es del mismo dia.

## Variables de entorno

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

## Probar sin enviar nada

`ANTICIPOS_EMAIL_DRY_RUN=true` calcula, guarda en BigQuery y **deja cada correo como un
fichero HTML** en `salida_dry_run/` para abrirlo en el navegador, sin mandar nada.
Combinado con `ANTICIPOS_ONLY_SOCIEDADES=PAL,PAN` la prueba son dos correos y no
diecisiete.

En Cloud Run el sistema de ficheros es de solo lectura fuera de `/tmp`, asi que ahi la
copia local no se escribe: se avisa en el log y el resto del dry run funciona igual.

## Deploy

```bash
cp .env.example .env   # y rellena SENDGRID_API_KEY
bash deploy.sh
```

`deploy.sh` construye la imagen, despliega el Cloud Run Job `anticipos-diario`, le
inyecta las variables y crea o actualiza el Cloud Scheduler.

**Cambiar `.env` no cambia nada en produccion hasta volver a ejecutar `deploy.sh`.**
Ejecutar el Job a mano usa la configuracion que ya estaba desplegada:

```bash
gcloud run jobs execute anticipos-diario --region us-west4 --wait
```

La *service account* del Job necesita leer `D00_SANDBOX` y `D20_DIMENSION`, escribir en
`D60_REPORTING` y leer Firestore.

## Pendiente

- Poblar `lists/anticipos` en Firestore. Los campos `globales` y `por_sociedad` **no los
  gestiona todavia la interfaz de Mailing-lists**: hay que anadirlos a `firestore_payload`
  o se perderan en cada guardado desde la app. Hasta entonces, se editan en la consola.
- Confirmar con contabilidad la exclusion de `UMSKZ = 'A'`.

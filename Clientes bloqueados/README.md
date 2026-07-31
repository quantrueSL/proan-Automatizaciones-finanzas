# Reporte diario de clientes en riesgo de bloqueo

Cada dia lista los clientes bloqueados, a punto de bloquearse o exentos de bloqueo, de
23 sociedades, y envia un correo por sociedad mas uno consolidado. A diferencia de
Anticipos y Partidas, **no escribe nada en BigQuery**: solo lee una tabla que ya
mantiene otro proceso y manda los correos.

## Que es un bloqueo de credito

Cuando un cliente acumula facturas vencidas, SAP puede cortarle el credito: mientras
esta bloqueado no se le puede facturar ni entregar mercancia nueva. El indicador vive en
la maestra de clientes, `KNA1.AUFSD = '01'`.

Hay clientes que nunca se bloquean aunque deban, porque su clave de grupo
(`KNA1.KONZS`) los declara exentos: `GRUPO` (empresas del propio grupo Proan) o
`AUTO`/`ADMON` (otra excepcion administrativa). `KONZS` tambien clasifica clientes por
zona o sucursal -tiene mas de 90 valores distintos, la mayoria nombres de plaza- asi que
solo esos tres valores concretos importan para el bloqueo.

## Las cinco categorias

Ya vienen calculadas en el origen. Son mutuamente excluyentes: `KONZS` solo puede tener
un valor, y el indicador de SAP (`AUFSD`) solo entra en la primera.

| Categoria | Que significa |
|---|---|
| **Bloqueados** | `AUFSD = '01'` y no esta en un grupo exento. Credito cortado hoy. |
| **Bloqueo esperado** | Vencido hace mas de un dia, no exento, pero SAP todavia no lo bloqueo. Deberia estar bloqueado y no lo esta. |
| **Proximos a bloqueo** | Acaba de vencer (0 o 1 dias) y tiene alguna factura vencida. Al borde del caso anterior. |
| **No bloqueados por grupo** | `KONZS = 'GRUPO'`. No se bloquea nunca, sea cual sea su mora. |
| **No bloqueados** | `KONZS` en (`AUTO`, `ADMON`). Tampoco se bloquea, por otro motivo. |

Un cliente sin factura vencida y sin grupo exento no cae en ninguna categoria: no tiene
nada que reportar, y el proceso lo descarta.

## De donde sale el dato, y por que este proceso no escribe en BigQuery

Todo el calculo -deuda vencida, dias de demora, las cinco categorias- ya esta hecho y
persistido en `D60_REPORTING.clientes_bloqueados` por **otro proceso**: a juzgar por el
`CREATE OR REPLACE TABLE` con plantilla de Airflow que hay en `backup/clientes_bloqueados.sql`,
un DAG ajeno a este repo. Esa tabla no esta particionada: cada corrida la reemplaza
entera, sin historia.

A diferencia de Anticipos y Partidas, aqui no se construye una tabla propia de
evolucion -decision explicita, no un olvido-: el dato ya tiene un dueno (el DAG que lo
calcula), y anadir una segunda tabla solo para historizar algo que este proceso ni
calcula habria sido una automatizacion sobre otra automatizacion. Si algun dia hace
falta ver la evolucion de un cliente en el tiempo, hay que fotografiar
`clientes_bloqueados` desde fuera de este script.

Este proceso solo **lee** dos tablas y envia correos:

| | |
|---|---|
| Categorias, deuda, dias de demora | `D60_REPORTING.clientes_bloqueados` |
| Nombre completo de la sociedad | `D20_DIMENSION.dm_company`, campo `company_name` |

### Por que se descartan los clientes con `company_code = '-'`

Son clientes de `KNA1` sin ninguna partida en `BSID`: no tienen sociedad asignable, y un
correo "por sociedad" no tiene donde meterlos. Son la mayoria de las filas de la tabla
origen -unas 20.000 de 23.500- precisamente por eso.

## Sociedades

23, mas amplia que las 16 de Anticipos/Partidas:

```
ABP  ADE  AME  BAG  CCP  DBC  FAG  FEF  GSI  HEGP  ISE
MAL  MPE  PAL  PAN  PAT  PFO  PIN  PRA  ROMM  SAP  SCO  SCO1
```

Se comprobo por consulta agregada que, de las sociedades que Anticipos excluye a
proposito (`ADE, FAG, FEF, GSI, PFO, SCO, SCO1`), aqui **si tienen actividad real**:
`SCO1` tiene 213 clientes con datos, `GSI` 117. Solo `PFO` no tiene ninguna fila hoy, y
aun asi se incluye para que su correo diga "sin clientes en riesgo" en vez de
desaparecer sin explicacion.

`SCO` y `SCO1` comparten el mismo nombre comercial en `dm_company` ("Superdoña
Comercial") pero son sociedades distintas: van con su propio correo cada una.

El nombre completo de cada sociedad sale de `dm_company.company_name`, igual patron que
`nombre_proveedor` via `dm_vendors` en Anticipos. Si un codigo no aparece en
`dm_company`, el correo dice `(sin nombre en la maestra)`.

## Control de frescura

`clientes_bloqueados` no tiene columna `_ingested_at`: la sustituye entera un
`CREATE OR REPLACE TABLE` externo. En su lugar, el proceso comprueba la **fecha de
modificacion de la tabla** (metadata de BigQuery, `client.get_table().modified`) y
**falla** si tiene mas de `BLOQUEADOS_MAX_ANTIGUEDAD_HORAS` horas (30 por defecto).

**El umbral es una primera aproximacion.** A diferencia de `bsik_real_time` (se
confirmo que recarga cada dos horas) o `bsis_real_time` (carga de madrugada, se
confirmo un patron de ~20 horas), no se conoce el ritmo real del DAG que mantiene
`clientes_bloqueados`. Al comprobarlo el 31/07/2026, la ultima carga tenia algo menos
de 24 horas. Conviene revisar el umbral cuando se tengan varios dias de datos.

## El correo

Cada sociedad se presenta como "Sociedad `CODIGO` - `Nombre completo`", con una seccion
por categoria activa -bloqueados, bloqueo esperado, proximos a bloqueo, no bloqueados
por grupo, no bloqueados-, cada una con su detalle (cliente, area, dias de demora,
facturas vencidas, dias de credito, saldo vencido) y su subtotal. **No hay un total
combinado entre categorias**: sumar el saldo de un bloqueado con el de un exento por
grupo mezclaria poblaciones que no son comparables.

Una sociedad sin ninguna categoria activa **recibe su correo igualmente**, con un "sin
clientes en riesgo ni exentos con mora": el silencio no se distingue de un proceso roto.

Se envian dos tipos de correo, igual que Anticipos y Partidas:

- **Uno por sociedad**, con sus categorias.
- **Uno consolidado** con las 23, que empieza con un resumen -conteo por categoria y
  saldo vencido en riesgo (bloqueados + bloqueo esperado + proximos) por sociedad- y
  sigue con el detalle.

### El PDF adjunto

Mismo patron que Anticipos y Partidas: WeasyPrint sobre el mismo HTML del correo, con
una hoja de estilos que solo existe para el PDF. Va en **A4 horizontal**, como
Partidas: seis columnas no caben con comodidad en vertical.

Si la generacion del PDF falla, el correo sale igual, sin adjunto y con un aviso en el
cuerpo.

### Destinatarios

Documento Firestore `lists/clientes_bloqueados` en la base `proan-lista-mails`, mismo
modelo que Anticipos y Partidas:

| Campo | Tipo | |
|---|---|---|
| `segmentada` | bool | `true`. Lo usa la app de Mailing-lists para editarla por grupos |
| `globales` | array | Reciben **un** correo con las 23 sociedades |
| `por_sociedad` | map sociedad → array | Un correo por sociedad |
| `emails` | array | La union. El proceso la ignora; existe para que la interfaz de Mailing-lists considere la lista activa |
| `kind` | string | `mailing` |
| `enabled` | bool | |

La lista se gestiona desde la app de Mailing-lists (`segmentada: true` esta soportado en
el codigo: `save_list` conserva `globales`/`por_sociedad` aunque no vengan en el
payload, ver `utils.py`). Solo la **creacion** del documento es manual, en la consola de
Firestore -es la convencion del repo para toda lista nueva, no una precaucion especial
de este reporte.

**Si Firestore no esta disponible** se cae a `BLOQUEADOS_EMAIL_TO` y luego a los
destinatarios por defecto del codigo, y en ese caso **se envia solo el correo global**.

### Horario

`20 10 * * 1-6` en `America/Mexico_City`: lunes a sabado a las 10:20 de Mexico, diez
minutos despues de Partidas para que los tres reportes no lleguen de golpe.

## Operacion

| Variable | Por defecto | |
|---|---|---|
| `SENDGRID_API_KEY` | — | Obligatoria salvo en dry run |
| `SENDGRID_FROM_EMAIL` | `noreply@proan.com` | Remitente verificado en SendGrid |
| `BLOQUEADOS_EMAIL_DRY_RUN` | `false` | `true` calcula y no envia |
| `BLOQUEADOS_ONLY_SOCIEDADES` | *(vacio)* | Recorta la ejecucion, para pruebas |
| `BLOQUEADOS_EMAIL_TO` | — | Solo si Firestore no tiene lista |
| `BLOQUEADOS_MAX_ANTIGUEDAD_HORAS` | `30` | Antiguedad tolerable de la tabla, ver arriba |
| `BLOQUEADOS_DRY_RUN_DIR` | `salida_dry_run` | Donde deja el HTML en dry run |
| `FIRESTORE_DATABASE_ID` | `proan-lista-mails` | |
| `FIRESTORE_LISTS_COLLECTION` | `lists` | |
| `BLOQUEADOS_LIST_ID` | `clientes_bloqueados` | |

### Probar sin enviar nada

`BLOQUEADOS_EMAIL_DRY_RUN=true` lee `clientes_bloqueados` y `dm_company`, y deja cada
correo como un fichero HTML en `salida_dry_run/`. Con
`BLOQUEADOS_ONLY_SOCIEDADES=PAN,GSI` la prueba son tres correos y no veinticuatro.

**Ojo:** en dry run local el HTML/PDF de prueba contiene datos reales de clientes
(nombre, saldo vencido). `salida_dry_run/` esta excluida del repo por `.gitignore`, pero
eso es una red de seguridad, no un permiso: no hay que compartir esos ficheros fuera de
este equipo.

### Deploy

```bash
cp .env.example .env   # y rellena SENDGRID_API_KEY
bash deploy.sh
```

**Desplegado.** Job `clientes-bloqueados-diario` en `us-west4`, Scheduler
`clientes-bloqueados-diario-scheduler` con el horario de arriba, `BLOQUEADOS_EMAIL_DRY_RUN=false`
-envio real desde el primer dia-. La lista Firestore `lists/clientes_bloqueados` existe,
con las 23 sociedades y el correo global apuntando de momento a `pcoma@quantrue.com` en
todos los grupos: hasta que se cambie, ese es quien recibe los 24 correos diarios.

La *service account* del Job necesita leer `D60_REPORTING` y `D20_DIMENSION`, y leer
Firestore. No necesita permiso de escritura en BigQuery.

## Pendiente

- **Sustituir `pcoma@quantrue.com` por los destinatarios reales** en
  `lists/clientes_bloqueados` (globales y cada sociedad), desde la app de Mailing-lists.
- **Confirmar el ritmo real de actualizacion de `clientes_bloqueados`** durante unos
  dias, para ajustar `BLOQUEADOS_MAX_ANTIGUEDAD_HORAS` con datos en vez de una
  suposicion.
- **Confirmar con el equipo de credito** si las cinco categorias y su agrupacion
  (riesgo real vs. exentos) coinciden con como ellos leen hoy el dashboard manual.

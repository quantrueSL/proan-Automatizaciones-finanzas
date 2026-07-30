# Automatizacion diaria de tipos de cambio

## Alcance

Se dispone de un proceso automatico para obtener diariamente los tipos de cambio oficiales publicados por Banco de Mexico y dejarlos preparados para su uso en reporting interno.

El proceso cubre:

- Extraccion del dato oficial desde Banco de Mexico
- Calculo de conversiones derivadas necesarias para reporting
- Carga automatica de la informacion en BigQuery
- Preparacion de la base para su incorporacion al reporte de direccion

## Datos obtenidos

La fuente utilizada es la API oficial de Banco de Mexico. A partir de ella se obtienen:

- `USD/MXN`
- `EUR/MXN`

Con estos valores se calculan tambien:

- `EUR/USD`
- `USD/EUR`

## Tabla de salida

La informacion se almacena en la tabla:

`proan-quantrue.ZZ_PRUEBAS.Cambio_divisa_diario`

La tabla guarda:

- Fecha oficial del dato publicado por Banco de Mexico
- Tipo de cambio peso/dolar
- Tipo de cambio peso/euro
- Paridad euro/dolar calculada
- Paridad dolar/euro calculada
- Fecha y hora local de Mexico en la que se actualiza la tabla

## Frecuencia y hora

La actualizacion se ejecuta automaticamente de lunes a viernes a las `08:50` hora de Mexico.

Banco de Mexico publica el tipo de cambio FIX a partir de las 12:00 horas de Mexico en dias habiles bancarios. Por tanto:

- Al ejecutarse la extraccion a las `08:50`, el dato disponible corresponde normalmente al ultimo dato oficial publicado por Banco de Mexico
- En la practica, eso implica que el valor cargado en la tabla suele ser el del dia habil bancario anterior
- La tabla conserva tanto la fecha oficial del dato (`rate_date`) como la fecha y hora local de Mexico en la que se realiza la actualizacion (`updated_at_mexico`)

## Integracion con el reporte de direccion

La tabla en BigQuery permite alimentar automaticamente el reporte de direccion que actualmente requiere esta informacion, eliminando la consulta manual y la introduccion manual del tipo de cambio.

La integracion puede realizarse de forma sencilla leyendo desde BigQuery la ultima fila disponible o la fila correspondiente a la fecha oficial deseada e incorporando esos valores al reporte final.

## Envio automatico a destinatarios

El mismo Cloud Run Job envia un unico correo HTML automaticamente al terminar la escritura en BigQuery.
El destinatario principal es el remitente generico configurado en `SENDGRID_FROM_EMAIL` y los destinatarios reales van en copia (`CC`).

Origen de destinatarios:

- Primero intenta leer Firestore en la base `proan-lista-mails`, coleccion `lists`, documento `cambio_divisa`.
- Si Firestore no existe, esta deshabilitado o no tiene emails validos, usa `CAMBIO_DIVISA_EMAIL_TO`.
- Si tampoco hay valor en entorno, usa los destinatarios por defecto hardcodeados.

Destinatarios por defecto hardcodeados:

- `pcoma@quantrue.com`
- `fromeo@quantrue.com`

La configuracion se toma del entorno:

- `BANXICO_API_TOKEN`: token de acceso a la API del SIE de Banxico. Se carga desde `.env` durante el deploy.
- `SENDGRID_API_KEY`: API key de SendGrid. Se carga desde `.env` durante el deploy.
- `SENDGRID_FROM_EMAIL`: remitente verificado en SendGrid. Por defecto `noreply@proan.com`.
- `CAMBIO_DIVISA_EMAIL_TO`: fallback de destinatarios separados por coma.
- `CAMBIO_DIVISA_EMAIL_DRY_RUN`: si vale `true`, no envia correo real.
- `FIRESTORE_DATABASE_ID`: base Firestore. Por defecto `proan-lista-mails`.
- `FIRESTORE_LISTS_COLLECTION`: coleccion de listas. Por defecto `lists`.
- `CAMBIO_DIVISA_LIST_ID`: id de lista a leer. Por defecto `cambio_divisa`.

Para desplegar, crea un `.env` local siguiendo `.env.example` y ejecuta:

```bash
bash deploy.sh
```

El `.env` queda excluido del build mediante `.gcloudignore`. La API key se inyecta al Cloud Run Job como variable de entorno durante el deploy para evitar depender de permisos de IAM sobre Secret Manager.

Si cambias `.env`, debes volver a ejecutar `bash deploy.sh`; ejecutar manualmente el Cloud Run Job solo usa la configuracion que ya estaba desplegada.

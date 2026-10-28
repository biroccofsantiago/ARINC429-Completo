# ARINC 429 Completo

Base inicial en Flask para registrar envíos, asociarlos a un instrumento y generar la palabra ARINC 429 de 32 bits.

## Puesta en marcha

Se requiere Python 3, MySQL y una base vacía llamada `arinc429`. Instalar dependencias y configurar la conexión:

```sh
python3 -m pip install -r requirements.txt
export DATABASE_URL='mysql+pymysql://arinc_user:change_me@localhost:3306/arinc429'
python3 app.py
```

La aplicación crea las tablas al iniciar. `GET /api/instrumentos` lista instrumentos y `POST /api/instrumentos` registra uno con `nombre`, `etiqueta_octal`, `resolucion` y `unidad`. `GET` y `POST /api/envios` listan y crean envíos; `/api/envios/<id>` admite `GET`, `PUT` y `DELETE`. Un envío se crea con `instrumento_id` y `valor`; opcionalmente acepta `sdi` y `ssm`.

Las pruebas usan SQLite temporal: `python3 -m pytest -q`.

## Alcance del código ARINC

La codificación implementada asume datos BNR con escala definida por `resolucion`, etiqueta en octal, campos SDI/SSM y paridad impar. La palabra generada se guarda en la base y se devuelve en hexadecimal y binario. Antes de usarla con un equipo real hay que contrastar formato, escala, orientación de bits y asignación de etiquetas con la especificación del instrumento y del adaptador ARINC 429.

La app todavía no transmite por puerto serial ni genera salida de audio. Un puerto UART común no proporciona por sí mismo la señal eléctrica ARINC 429; hace falta el transmisor/adaptador correspondiente y su protocolo de entrada. La salida de auriculares tampoco debe conectarse directamente a un servo: para esa etapa hacen falta el circuito y los componentes concretos, con entrada de alta impedancia y acondicionamiento/aislamiento apropiado.

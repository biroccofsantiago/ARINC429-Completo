# ARINC 429 Completo

Aplicación Flask para administrar instrumentos y envíos, generar palabras ARINC 429 BNR de 32 bits y transmitirlas a un Arduino por puerto serie.

## Puesta en marcha

Se requiere Python 3 y MySQL (o SQLite para desarrollo). Instalar dependencias y configurar la conexión:

```sh
python3 -m pip install -r requirements.txt
export DATABASE_URL='mysql+pymysql://arinc_user:change_me@localhost:3306/arinc429'
python3 app.py
```

La aplicación crea las tablas al iniciar y añade los campos de límites a una tabla `instrumento` existente. Cada instrumento tiene nombre, etiqueta octal, resolución, unidad y límites `valor_minimo`/`valor_maximo`; las etiquetas deben ser únicas. El CRUD está disponible en `GET`/`POST /api/instrumentos` y `GET`/`PUT`/`DELETE /api/instrumentos/<id>`. No se puede borrar un instrumento que ya tenga envíos. Si una integración antigua omite los límites al crear un instrumento, se usa todo el rango BNR permitido para esa resolución. Al cambiar una etiqueta o resolución, las palabras guardadas se vuelven a generar; la actualización se rechaza si los límites nuevos excluyen algún envío existente.

`GET`/`POST /api/envios` listan y crean envíos; `/api/envios/<id>` admite `GET`, `PUT` y `DELETE`. Para crear un envío se requieren `instrumento_id` y `valor`; `sdi` y `ssm` son opcionales. Se rechazan valores que exceden los límites configurados o el rango representable BNR.

## Alcance del código ARINC

La codificación implementada asume datos BNR con escala definida por `resolucion`, etiqueta en octal, campos SDI/SSM y paridad impar. La palabra generada se guarda en la base y se devuelve en hexadecimal y binario.

## Puerto serie y Arduino

Configurar `SERIAL_PORT` y, opcionalmente, `SERIAL_BAUDRATE` (9600 por defecto) en el entorno de la aplicación. Por ejemplo, usar `/dev/ttyACM0` en Linux o el puerto COM que corresponda en Windows. `SERIAL_STARTUP_DELAY` (2 segundos por defecto) espera el reinicio automático que suele ocurrir al abrir el puerto USB de una placa Uno/Nano. El botón **Transmitir** envía la palabra ARINC como ocho dígitos hexadecimales ASCII seguidos de `\n`; por ejemplo, `1234ABCD\n`. La ruta `POST /api/envios/<id>/transmitir` realiza la misma operación. Si el puerto no está configurado o no se puede abrir, la API devuelve un error explícito.

Abrir `arduino/ARINC429Receiver/ARINC429Receiver.ino` en Arduino IDE e instalar la biblioteca `LiquidCrystal_I2C`. El ejemplo está preparado para una placa tipo Uno/Nano, una pantalla LCD 16x2 con adaptador I2C en dirección `0x27` y 9600 baudios. Conectar SDA/SCL a los pines I2C de la placa; la salida digital de un bit 1 es el pin 13 y la de un bit 0 es el pin 12. Ambas salidas generan un pulso HIGH de 5 ms por cada bit y permanecen LOW en reposo.

El firmware verifica que la trama contenga ocho dígitos hexadecimales, que tenga paridad impar, que la etiqueta esté registrada y que el valor decodificado esté dentro de límites. La tabla `instruments` del sketch debe mantenerse sincronizada con los instrumentos de la base (etiqueta octal, resolución, unidad, mínimo y máximo); esos metadatos no caben en la palabra ARINC de 32 bits. El ejemplo incluido es **Altitud**, etiqueta `203`, resolución `0.5`, rango `-1000` a `20000 ft`; reemplazarlo por la configuración real antes de usarlo.

Los pines 12 y 13 son salidas lógicas de demostración, no una interfaz eléctrica ARINC 429. No conectar esas salidas directamente a un bus ARINC ni a cargas que excedan la corriente de los pines: para transmitir ARINC 429 se necesita el transceptor apropiado, y las conexiones deben respetar los niveles eléctricos de la placa y de la pantalla.

## Validación

Las pruebas usan SQLite temporal: `python3 -m pytest -q`.

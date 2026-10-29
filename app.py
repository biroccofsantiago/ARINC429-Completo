import os
from datetime import datetime, timezone
from math import isclose, isfinite
from time import sleep

from flask import Flask, jsonify, render_template, request
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import inspect, select, text
from sqlalchemy.exc import IntegrityError

db = SQLAlchemy()


class Instrumento(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(80), nullable=False, unique=True)
    etiqueta_octal = db.Column(db.String(3), nullable=False)
    resolucion = db.Column(db.Float, nullable=False)
    unidad = db.Column(db.String(24), nullable=False, default="")
    valor_minimo = db.Column(db.Float, nullable=True)
    valor_maximo = db.Column(db.Float, nullable=True)


class Envio(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    instrumento_id = db.Column(db.Integer, db.ForeignKey("instrumento.id"), nullable=False)
    valor = db.Column(db.Float, nullable=False)
    sdi = db.Column(db.Integer, nullable=False, default=0)
    ssm = db.Column(db.Integer, nullable=False, default=0)
    palabra_arinc = db.Column(db.BigInteger, nullable=False)
    creado_en = db.Column(db.DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    instrumento = db.relationship(Instrumento)


def _reverse_bits(value, width):
    reversed_value = 0
    for bit_index in range(width):
        reversed_value = (reversed_value << 1) | ((value >> bit_index) & 1)
    return reversed_value


def generar_palabra_arinc(etiqueta_octal, valor, resolucion, sdi=0, ssm=0):
    """Genera una palabra ARINC 429 BNR con paridad impar."""
    label = int(str(etiqueta_octal), 8)
    if not 0 <= label <= 0o377:
        raise ValueError("La etiqueta octal debe estar entre 000 y 377.")
    if resolucion <= 0:
        raise ValueError("La resolución debe ser mayor que cero.")
    if not 0 <= sdi <= 3 or not 0 <= ssm <= 3:
        raise ValueError("SDI y SSM deben estar entre 0 y 3.")

    raw_data = round(valor / resolucion)
    if not -(1 << 18) <= raw_data < (1 << 18):
        raise ValueError("El valor queda fuera del rango BNR de 19 bits.")

    word = _reverse_bits(label, 8) | (sdi << 8) | ((raw_data & 0x7FFFF) << 10) | (ssm << 29)
    if word.bit_count() % 2 == 0:
        word |= 1 << 31
    return word


def _error(message, status):
    return jsonify({"error": message}), status


def _shipment_json(shipment):
    return {
        "id": shipment.id,
        "instrumento": {
            "id": shipment.instrumento.id,
            "nombre": shipment.instrumento.nombre,
            "etiqueta_octal": shipment.instrumento.etiqueta_octal,
            "unidad": shipment.instrumento.unidad,
        },
        "valor": shipment.valor,
        "sdi": shipment.sdi,
        "ssm": shipment.ssm,
        "palabra_arinc_hex": f"0x{shipment.palabra_arinc:08X}",
        "palabra_arinc_bits": f"{shipment.palabra_arinc:032b}",
        "creado_en": shipment.creado_en.isoformat(),
    }


def _instrument_json(instrument):
    minimum, maximum = _default_bounds(instrument.resolucion)
    return {
        "id": instrument.id,
        "nombre": instrument.nombre,
        "etiqueta_octal": instrument.etiqueta_octal,
        "resolucion": instrument.resolucion,
        "unidad": instrument.unidad,
        "valor_minimo": instrument.valor_minimo if instrument.valor_minimo is not None else minimum,
        "valor_maximo": instrument.valor_maximo if instrument.valor_maximo is not None else maximum,
    }


def _default_bounds(resolucion):
    return -(1 << 18) * resolucion, ((1 << 18) - 1) * resolucion


def _value_is_valid_for_instrument(instrument, value):
    settings = _instrument_json(instrument)
    return _value_is_valid(
        value,
        instrument.resolucion,
        settings["valor_minimo"],
        settings["valor_maximo"],
    )


def _value_is_valid(value, resolution, minimum, maximum):
    encoded_value = round(value / resolution) * resolution
    return (
        minimum <= value <= maximum
        and (
            encoded_value >= minimum
            or isclose(encoded_value, minimum, rel_tol=1e-12, abs_tol=1e-12)
        )
        and (
            encoded_value <= maximum
            or isclose(encoded_value, maximum, rel_tol=1e-12, abs_tol=1e-12)
        )
    )


def _instrument_data(data, existing=None):
    try:
        nombre = str(data.get("nombre", existing.nombre if existing else "")).strip()
        label = str(data.get("etiqueta_octal", existing.etiqueta_octal if existing else "")).strip()
        resolucion = float(data.get("resolucion", existing.resolucion if existing else 0))
        unidad = str(data.get("unidad", existing.unidad if existing else "")).strip()
        default_minimum, default_maximum = _default_bounds(resolucion)
        minimum = float(data.get(
            "valor_minimo",
            existing.valor_minimo if existing and existing.valor_minimo is not None else default_minimum,
        ))
        maximum = float(data.get(
            "valor_maximo",
            existing.valor_maximo if existing and existing.valor_maximo is not None else default_maximum,
        ))
        label_value = int(label, 8)
        if (
            not nombre or len(nombre) > 80 or len(unidad) > 24
            or not 0 < label_value <= 0o377 or len(label) > 3
            or not isfinite(resolucion) or resolucion <= 0
            or not isfinite(minimum) or not isfinite(maximum) or minimum > maximum
        ):
            raise ValueError
        # Reject configured limits that could never fit in the 19-bit BNR data field.
        if not -(1 << 18) <= round(minimum / resolucion) <= round(maximum / resolucion) < (1 << 18):
            raise ValueError
    except (TypeError, ValueError, OverflowError):
        raise ValueError(
            "Se requieren nombre, etiqueta octal válida, resolución positiva y límites mínimo/máximo válidos."
        ) from None
    return {
        "nombre": nombre,
        "etiqueta_octal": f"{label_value:03o}",
        "resolucion": resolucion,
        "unidad": unidad,
        "valor_minimo": minimum,
        "valor_maximo": maximum,
    }


def _validate_instrument_label(label, instrument_id=None):
    label_value = int(label, 8)
    instruments = db.session.execute(select(Instrumento)).scalars()
    if any(
        item.id != instrument_id and int(item.etiqueta_octal, 8) == label_value
        for item in instruments
    ):
        return _error("La etiqueta octal ya está asignada a otro instrumento.", 409)
    return None


def _migrate_instrument_bounds():
    columns = {column["name"] for column in inspect(db.engine).get_columns("instrumento")}
    for column in ("valor_minimo", "valor_maximo"):
        if column not in columns:
            db.session.execute(text(f"ALTER TABLE instrumento ADD COLUMN {column} FLOAT"))
    db.session.commit()


def create_app(test_config=None):
    app = Flask(__name__)
    app.config.from_mapping(
        SQLALCHEMY_DATABASE_URI=os.getenv("DATABASE_URL", "sqlite:///arinc429.db"),
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
        SERIAL_PORT=os.getenv("SERIAL_PORT") or None,
        SERIAL_BAUDRATE=int(os.getenv("SERIAL_BAUDRATE", "9600")),
        SERIAL_STARTUP_DELAY=float(os.getenv("SERIAL_STARTUP_DELAY", "2")),
    )
    if test_config:
        app.config.update(test_config)
    db.init_app(app)

    @app.get("/")
    def inicio():
        return render_template("index.html")

    @app.get("/api/instrumentos")
    def listar_instrumentos():
        instrumentos = db.session.execute(select(Instrumento).order_by(Instrumento.nombre)).scalars()
        return jsonify([_instrument_json(item) for item in instrumentos])

    @app.post("/api/instrumentos")
    def crear_instrumento():
        data = request.get_json(silent=True) or {}
        try:
            fields = _instrument_data(data)
        except ValueError as error:
            return _error(str(error), 400)
        label_error = _validate_instrument_label(fields["etiqueta_octal"])
        if label_error:
            return label_error
        instrumento = Instrumento(**fields)
        db.session.add(instrumento)
        try:
            db.session.commit()
        except IntegrityError as error:
            db.session.rollback()
            app.logger.error("No se pudo guardar el instrumento: %s", error)
            return _error("No se pudo crear el instrumento; verificá que el nombre no esté repetido.", 409)
        return jsonify(_instrument_json(instrumento)), 201

    @app.get("/api/instrumentos/<int:instrumento_id>")
    def obtener_instrumento(instrumento_id):
        instrumento = db.session.get(Instrumento, instrumento_id)
        if instrumento is None:
            return _error("No existe el instrumento.", 404)
        return jsonify(_instrument_json(instrumento))

    @app.put("/api/instrumentos/<int:instrumento_id>")
    def actualizar_instrumento(instrumento_id):
        instrumento = db.session.get(Instrumento, instrumento_id)
        if instrumento is None:
            return _error("No existe el instrumento.", 404)
        try:
            fields = _instrument_data(request.get_json(silent=True) or {}, instrumento)
        except ValueError as error:
            return _error(str(error), 400)
        label_error = _validate_instrument_label(fields["etiqueta_octal"], instrumento.id)
        if label_error:
            return label_error
        shipments = db.session.execute(
            select(Envio).where(Envio.instrumento_id == instrumento.id)
        ).scalars().all()
        updated_words = []
        for shipment in shipments:
            if not _value_is_valid(
                shipment.valor,
                fields["resolucion"],
                fields["valor_minimo"],
                fields["valor_maximo"],
            ):
                return _error(
                    "Los nuevos límites o resolución no son compatibles con todos los envíos existentes.",
                    409,
                )
            try:
                updated_words.append(generar_palabra_arinc(
                    fields["etiqueta_octal"],
                    shipment.valor,
                    fields["resolucion"],
                    sdi=shipment.sdi,
                    ssm=shipment.ssm,
                ))
            except (ValueError, OverflowError):
                return _error(
                    "La nueva configuración no puede codificar todos los envíos existentes.",
                    409,
                )
        for field, value in fields.items():
            setattr(instrumento, field, value)
        for shipment, word in zip(shipments, updated_words):
            shipment.palabra_arinc = word
        try:
            db.session.commit()
        except IntegrityError as error:
            db.session.rollback()
            app.logger.error("No se pudo actualizar el instrumento: %s", error)
            return _error("No se pudo actualizar el instrumento; verificá que el nombre no esté repetido.", 409)
        return jsonify(_instrument_json(instrumento))

    @app.delete("/api/instrumentos/<int:instrumento_id>")
    def eliminar_instrumento(instrumento_id):
        instrumento = db.session.get(Instrumento, instrumento_id)
        if instrumento is None:
            return _error("No existe el instrumento.", 404)
        if db.session.execute(
            select(Envio.id).where(Envio.instrumento_id == instrumento_id).limit(1)
        ).first():
            return _error("No se puede eliminar un instrumento con envíos registrados.", 409)
        db.session.delete(instrumento)
        db.session.commit()
        return "", 204

    @app.get("/api/envios")
    def listar_envios():
        envios = db.session.execute(select(Envio).order_by(Envio.id)).scalars()
        return jsonify([_shipment_json(item) for item in envios])

    @app.post("/api/envios")
    def crear_envio():
        data = request.get_json(silent=True) or {}
        try:
            instrumento_id = int(data["instrumento_id"])
            valor = float(data["valor"])
            sdi = int(data.get("sdi", 0))
            ssm = int(data.get("ssm", 0))
        except (KeyError, TypeError, ValueError):
            return _error("Se requieren instrumento_id y valor numérico.", 400)

        instrumento = db.session.get(Instrumento, instrumento_id)
        if instrumento is None:
            return _error("No existe el instrumento seleccionado.", 404)
        if not isfinite(valor):
            return _error("El valor debe ser un número finito.", 400)
        if not _value_is_valid_for_instrument(instrumento, valor):
            return _error("El valor está fuera del rango permitido para el instrumento.", 400)
        try:
            word = generar_palabra_arinc(
                instrumento.etiqueta_octal,
                valor,
                instrumento.resolucion,
                sdi=sdi,
                ssm=ssm,
            )
        except (ValueError, OverflowError) as error:
            return _error(str(error), 400)

        envio = Envio(
            instrumento=instrumento,
            valor=valor,
            sdi=sdi,
            ssm=ssm,
            palabra_arinc=word,
        )
        db.session.add(envio)
        db.session.commit()
        return jsonify(_shipment_json(envio)), 201

    @app.get("/api/envios/<int:envio_id>")
    def obtener_envio(envio_id):
        envio = db.session.get(Envio, envio_id)
        if envio is None:
            return _error("No existe el envío.", 404)
        return jsonify(_shipment_json(envio))

    @app.put("/api/envios/<int:envio_id>")
    def actualizar_envio(envio_id):
        envio = db.session.get(Envio, envio_id)
        if envio is None:
            return _error("No existe el envío.", 404)
        data = request.get_json(silent=True) or {}
        try:
            instrumento_id = int(data.get("instrumento_id", envio.instrumento_id))
            valor = float(data.get("valor", envio.valor))
            sdi = int(data.get("sdi", envio.sdi))
            ssm = int(data.get("ssm", envio.ssm))
        except (TypeError, ValueError):
            return _error("instrumento_id y valor deben ser válidos.", 400)

        instrumento = db.session.get(Instrumento, instrumento_id)
        if instrumento is None:
            return _error("No existe el instrumento seleccionado.", 404)
        if not isfinite(valor):
            return _error("El valor debe ser un número finito.", 400)
        if not _value_is_valid_for_instrument(instrumento, valor):
            return _error("El valor está fuera del rango permitido para el instrumento.", 400)
        try:
            word = generar_palabra_arinc(
                instrumento.etiqueta_octal,
                valor,
                instrumento.resolucion,
                sdi=sdi,
                ssm=ssm,
            )
        except (ValueError, OverflowError) as error:
            return _error(str(error), 400)

        envio.instrumento = instrumento
        envio.valor = valor
        envio.sdi = sdi
        envio.ssm = ssm
        envio.palabra_arinc = word
        db.session.commit()
        return jsonify(_shipment_json(envio))

    @app.delete("/api/envios/<int:envio_id>")
    def eliminar_envio(envio_id):
        envio = db.session.get(Envio, envio_id)
        if envio is None:
            return _error("No existe el envío.", 404)
        db.session.delete(envio)
        db.session.commit()
        return "", 204

    @app.post("/api/envios/<int:envio_id>/transmitir")
    def transmitir_envio(envio_id):
        envio = db.session.get(Envio, envio_id)
        if envio is None:
            return _error("No existe el envío.", 404)
        port = app.config.get("SERIAL_PORT")
        if not port:
            return _error("Configurá SERIAL_PORT para conectar el Arduino.", 503)
        try:
            import serial
        except ImportError:
            app.logger.exception("Falta instalar pyserial para transmitir por puerto serie")
            return _error("La transmisión serie requiere instalar pyserial.", 503)
        try:
            with serial.Serial(
                port=port,
                baudrate=app.config.get("SERIAL_BAUDRATE", 9600),
                timeout=1,
                write_timeout=2,
            ) as connection:
                sleep(app.config.get("SERIAL_STARTUP_DELAY", 2))
                connection.write(f"{envio.palabra_arinc:08X}\n".encode("ascii"))
                connection.flush()
        except (serial.SerialException, OSError, ValueError) as error:
            app.logger.error("Error al transmitir por %s: %s", port, error)
            return _error("No se pudo transmitir al puerto serie configurado.", 503)
        return jsonify({
            "mensaje": "Palabra transmitida.",
            "palabra_arinc_hex": f"0x{envio.palabra_arinc:08X}",
        })

    return app


if __name__ == "__main__":
    application = create_app()
    with application.app_context():
        db.create_all()
        _migrate_instrument_bounds()
    application.run(debug=os.getenv("FLASK_DEBUG") == "1")
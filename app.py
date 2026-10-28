import os
from datetime import datetime, timezone
from math import isfinite

from flask import Flask, jsonify, render_template, request
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import select

db = SQLAlchemy()


class Instrumento(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(80), nullable=False, unique=True)
    etiqueta_octal = db.Column(db.String(3), nullable=False)
    resolucion = db.Column(db.Float, nullable=False)
    unidad = db.Column(db.String(24), nullable=False, default="")


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


def create_app(test_config=None):
    app = Flask(__name__)
    app.config.from_mapping(
        SQLALCHEMY_DATABASE_URI=os.getenv("DATABASE_URL", "sqlite:///arinc429.db"),
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
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
        return jsonify([
            {
                "id": item.id,
                "nombre": item.nombre,
                "etiqueta_octal": item.etiqueta_octal,
                "resolucion": item.resolucion,
                "unidad": item.unidad,
            }
            for item in instrumentos
        ])

    @app.post("/api/instrumentos")
    def crear_instrumento():
        data = request.get_json(silent=True) or {}
        try:
            nombre = str(data["nombre"]).strip()
            label = str(data["etiqueta_octal"])
            resolucion = float(data["resolucion"])
            unidad = str(data.get("unidad", ""))
            int(label, 8)
            if not nombre or not 0 < int(label, 8) <= 0o377 or not isfinite(resolucion) or resolucion <= 0:
                raise ValueError
        except (KeyError, TypeError, ValueError):
            return _error("Se requieren nombre, etiqueta_octal válida y resolución positiva.", 400)

        instrumento = Instrumento(
            nombre=nombre,
            etiqueta_octal=label,
            resolucion=resolucion,
            unidad=unidad,
        )
        db.session.add(instrumento)
        try:
            db.session.commit()
        except Exception:
            db.session.rollback()
            return _error("No se pudo crear el instrumento; verificá que el nombre no esté repetido.", 409)
        return jsonify({"id": instrumento.id, "nombre": instrumento.nombre}), 201

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

    return app


if __name__ == "__main__":
    application = create_app()
    with application.app_context():
        db.create_all()
    application.run(debug=os.getenv("FLASK_DEBUG") == "1")
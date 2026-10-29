import sys
from types import SimpleNamespace

import pytest

from app import create_app, db, generar_palabra_arinc


@pytest.fixture
def client():
    app = create_app({
        "TESTING": True,
        "SQLALCHEMY_DATABASE_URI": "sqlite://",
    })
    with app.app_context():
        db.create_all()
    with app.test_client() as test_client:
        yield test_client
    with app.app_context():
        db.drop_all()


def test_arinc_word_is_32_bits_with_odd_parity():
    word = generar_palabra_arinc("203", 12.5, 0.5)

    assert 0 <= word < (1 << 32)
    assert word.bit_count() % 2 == 1


def test_shipment_crud_generates_arinc_word(client):
    instrument = client.post("/api/instrumentos", json={
        "nombre": "Altitud",
        "etiqueta_octal": "203",
        "resolucion": 0.5,
        "unidad": "ft",
    })
    assert instrument.status_code == 201
    instrument_id = instrument.json["id"]

    created = client.post("/api/envios", json={
        "instrumento_id": instrument_id,
        "valor": 12.5,
        "sdi": 2,
        "ssm": 1,
    })
    assert created.status_code == 201
    envio_id = created.json["id"]
    assert len(created.json["palabra_arinc_bits"]) == 32
    assert created.json["sdi"] == 2
    assert created.json["ssm"] == 1

    updated = client.put(f"/api/envios/{envio_id}", json={"valor": 20})
    assert updated.status_code == 200
    assert updated.json["valor"] == 20
    assert updated.json["sdi"] == 2
    assert updated.json["ssm"] == 1
    assert client.get(f"/api/envios/{envio_id}").status_code == 200
    assert client.delete(f"/api/envios/{envio_id}").status_code == 204
    assert client.get(f"/api/envios/{envio_id}").status_code == 404


def test_instrument_crud_enforces_unique_labels_and_protects_used_instruments(client):
    payload = {
        "nombre": "Altitud",
        "etiqueta_octal": "203",
        "resolucion": 0.5,
        "unidad": "ft",
        "valor_minimo": -100,
        "valor_maximo": 100,
    }
    created = client.post("/api/instrumentos", json=payload)
    assert created.status_code == 201
    instrument_id = created.json["id"]
    assert created.json["valor_minimo"] == -100
    assert client.get(f"/api/instrumentos/{instrument_id}").json["nombre"] == "Altitud"

    duplicate = client.post("/api/instrumentos", json={**payload, "nombre": "Duplicado"})
    assert duplicate.status_code == 409

    updated = client.put(f"/api/instrumentos/{instrument_id}", json={
        "nombre": "Altitud corregida",
        "valor_maximo": 150,
    })
    assert updated.status_code == 200
    assert updated.json["nombre"] == "Altitud corregida"
    assert updated.json["valor_maximo"] == 150

    shipment = client.post("/api/envios", json={
        "instrumento_id": instrument_id,
        "valor": 50,
    })
    assert shipment.status_code == 201
    old_word = shipment.json["palabra_arinc_hex"]
    reconfigured = client.put(f"/api/instrumentos/{instrument_id}", json={
        "etiqueta_octal": "206",
        "resolucion": 1,
    })
    assert reconfigured.status_code == 200
    updated_shipment = client.get(f"/api/envios/{shipment.json['id']}").json
    assert updated_shipment["palabra_arinc_hex"] != old_word
    assert updated_shipment["instrumento"]["etiqueta_octal"] == "206"
    assert client.delete(f"/api/instrumentos/{instrument_id}").status_code == 409
    assert client.delete(f"/api/envios/{shipment.json['id']}").status_code == 204
    assert client.delete(f"/api/instrumentos/{instrument_id}").status_code == 204


def test_instrument_and_shipment_values_must_fit_configured_bounds(client):
    instrument = client.post("/api/instrumentos", json={
        "nombre": "Temperatura",
        "etiqueta_octal": "204",
        "resolucion": 1,
        "unidad": "C",
        "valor_minimo": -20,
        "valor_maximo": 80,
    })
    assert instrument.status_code == 201
    instrument_id = instrument.json["id"]

    invalid_instrument = client.post("/api/instrumentos", json={
        "nombre": "Rango inválido",
        "etiqueta_octal": "205",
        "resolucion": 1,
        "valor_minimo": 20,
        "valor_maximo": -20,
    })
    assert invalid_instrument.status_code == 400

    outside_range = client.post("/api/envios", json={
        "instrumento_id": instrument_id,
        "valor": 81,
    })
    assert outside_range.status_code == 400
    assert "rango" in outside_range.json["error"]


def test_serial_transmission_sends_32_bit_word_as_hex_line(client, monkeypatch):
    instrument = client.post("/api/instrumentos", json={
        "nombre": "Altitud",
        "etiqueta_octal": "203",
        "resolucion": 0.5,
        "unidad": "ft",
    })
    shipment = client.post("/api/envios", json={
        "instrumento_id": instrument.json["id"],
        "valor": 12.5,
    })
    client.application.config["SERIAL_PORT"] = "/dev/test-serial"
    client.application.config["SERIAL_STARTUP_DELAY"] = 0
    captured = {}

    class FakeSerial:
        def __init__(self, **kwargs):
            captured["kwargs"] = kwargs

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def write(self, payload):
            captured["payload"] = payload

        def flush(self):
            pass

    monkeypatch.setitem(
        sys.modules,
        "serial",
        SimpleNamespace(Serial=FakeSerial, SerialException=OSError),
    )
    response = client.post(f"/api/envios/{shipment.json['id']}/transmitir")

    assert response.status_code == 200
    assert captured["payload"] == f"{shipment.json['palabra_arinc_hex'][2:]}\n".encode("ascii")
    assert captured["kwargs"]["baudrate"] == 9600
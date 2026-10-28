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
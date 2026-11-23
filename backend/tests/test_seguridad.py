"""
Pruebas de seguridad: endpoints protegidos, perfil propio, cambio de clave
verificado y regla de contraseña segura (adaptadas para pytest).
"""
import os
import sys
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCR_DIR = os.path.join(BACKEND_DIR, "scr")
if SCR_DIR not in sys.path:
    sys.path.insert(0, SCR_DIR)

import Conexion.database as database  # noqa: E402
import Modelos.models as models  # noqa: E402
from Utilidades.seguridad import hashear_clave  # noqa: E402
import main as app_module  # noqa: E402

CLAVE = "Clave1234!"


def _poblar_datos_seguridad(session_factory):
    db = session_factory()
    try:
        for rol_id, nombre in [(1, "Administrador"), (2, "Productor"), (3, "Comprador")]:
            db.add(models.Rol(id=rol_id, nombre=nombre, descripcion=nombre))
        db.add(models.TipoDocumento(codigo="CC", nombre="Cedula"))
        db.commit()

        for uid, nombre, correo, rol_id in [
            (1, "Admin", "admin@t.com", 1),
            (2, "Prod", "prod@t.com", 2),
            (3, "Comp", "comp@t.com", 3),
        ]:
            db.add(
                models.Usuario(
                    id=uid,
                    nombre=nombre,
                    correo=correo,
                    telefono=f"300000000{uid}",
                    clave=hashear_clave(CLAVE),
                    estado="Activo",
                    rol_id=rol_id,
                    tipo_documento="CC",
                    numero_documento=f"1000000{uid}",
                    ciudad="Bogotá",
                    direccion="Calle secreta 123",
                )
            )
        db.commit()
    finally:
        db.close()


@pytest.fixture(scope="module")
def seguridad_ctx():
    mp = pytest.MonkeyPatch()

    engine_sqlite = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    @event.listens_for(engine_sqlite, "connect")
    def _fk_on(conn, _rec):
        conn.execute("PRAGMA foreign_keys=ON")

    session_factory = sessionmaker(autocommit=False, autoflush=False, bind=engine_sqlite)

    mp.setattr(database, "engine", engine_sqlite)
    mp.setattr(database, "SessionLocal", session_factory)

    database.Base.metadata.create_all(bind=engine_sqlite)
    _poblar_datos_seguridad(session_factory)

    client = TestClient(app_module.app)

    def _auth(correo: str, clave: str = CLAVE) -> dict[str, str]:
        resp = client.post("/auth/login", json={"correo": correo, "clave": clave})
        assert resp.status_code == 200, resp.text
        return {"Authorization": f"Bearer {resp.json()['data']['token']}"}

    ctx: dict[str, Any] = {
        "client": client,
        "auth": _auth,
        "admin": _auth("admin@t.com"),
        "prod": _auth("prod@t.com"),
        "comp": _auth("comp@t.com"),
    }

    yield ctx

    client.close()
    database.Base.metadata.drop_all(bind=engine_sqlite)
    engine_sqlite.dispose()
    mp.undo()


def test_get_usuarios_y_perfil_propio(seguridad_ctx):
    client = seguridad_ctx["client"]
    admin = seguridad_ctx["admin"]
    comp = seguridad_ctx["comp"]

    assert client.get("/usuarios").status_code == 401
    assert client.get("/usuarios", headers=comp).status_code == 403
    assert client.get("/usuarios", headers=admin).status_code == 200

    assert client.get("/usuarios/me").status_code == 401
    r = client.get("/usuarios/me", headers=comp)
    assert r.status_code == 200 and r.json()["data"]["correo"] == "comp@t.com", r.text


def test_datos_publicos_sin_informacion_personal(seguridad_ctx):
    client = seguridad_ctx["client"]

    r = client.get("/usuarios/productores")
    assert r.status_code == 200
    campos = set(r.json()["data"][0].keys())
    assert not (campos & {"correo", "telefono", "numero_documento", "direccion"}), str(campos)

    r_resumen = client.get("/usuarios/resumen-publico")
    assert r_resumen.status_code == 200 and r_resumen.json()["data"]["compradores"] == 1, r_resumen.text


def test_compras_ventas_e_historiales(seguridad_ctx):
    client = seguridad_ctx["client"]
    admin = seguridad_ctx["admin"]
    prod = seguridad_ctx["prod"]
    comp = seguridad_ctx["comp"]

    for ruta in ("/compras", "/ventas"):
        assert client.get(ruta).status_code == 401
        assert client.get(ruta, headers=comp).status_code == 403
        assert client.get(ruta, headers=admin).status_code == 200

    for ruta in ("/historial_seguimiento", "/historial_reservas"):
        assert client.get(ruta).status_code == 401
        assert client.get(ruta, headers=comp).status_code == 403
        assert client.get(ruta, headers=prod).status_code == 200
        assert client.get(ruta, headers=admin).status_code == 200


def test_cambiar_clave_y_regla_contrasena_segura(seguridad_ctx):
    client = seguridad_ctx["client"]
    comp = seguridad_ctx["comp"]
    nueva = "NuevaClave2026!"

    assert client.post("/auth/cambiar-clave", json={"clave_actual": CLAVE, "clave_nueva": nueva}).status_code == 401

    r = client.post("/auth/cambiar-clave", headers=comp, json={"clave_actual": "Incorrecta1!", "clave_nueva": nueva})
    assert r.status_code == 400, r.text

    r = client.post("/auth/cambiar-clave", headers=comp, json={"clave_actual": CLAVE, "clave_nueva": CLAVE})
    assert r.status_code == 400, r.text

    r = client.post("/auth/cambiar-clave", headers=comp, json={"clave_actual": CLAVE, "clave_nueva": "debil"})
    assert r.status_code in (400, 422), r.text

    r = client.post("/auth/cambiar-clave", headers=comp, json={"clave_actual": CLAVE, "clave_nueva": nueva})
    assert r.status_code == 200, r.text

    assert client.post("/auth/login", json={"correo": "comp@t.com", "clave": nueva}).status_code == 200
    assert client.post("/auth/login", json={"correo": "comp@t.com", "clave": CLAVE}).status_code == 401

    base = {
        "id": 50,
        "tipo_documento": "CC",
        "numero_documento": "55555555",
        "nombre": "Nuevo",
        "correo": "nuevo@t.com",
        "telefono": "3011111111",
        "rol_id": 3,
    }
    for clave in ("corta1!", "sinmayuscula1!", "SinNumero!!", "SinEspecial12"):
        r_reg = client.post("/usuarios", json={**base, "clave": clave})
        assert r_reg.status_code in (400, 422) and "contraseña" in r_reg.text, r_reg.text

    r_ok = client.post("/usuarios", json={**base, "clave": "Segura2026!"})
    assert r_ok.status_code in (200, 201), r_ok.text


def test_logout_invalida_token_y_nuevo_login(seguridad_ctx):
    client = seguridad_ctx["client"]
    auth = seguridad_ctx["auth"]

    h1 = auth("admin@t.com")
    assert client.post("/auth/logout", headers=h1).status_code == 200
    assert client.get("/usuarios/me", headers=h1).status_code == 401

    h2 = auth("admin@t.com")
    assert h2 != h1 and client.get("/usuarios/me", headers=h2).status_code == 200
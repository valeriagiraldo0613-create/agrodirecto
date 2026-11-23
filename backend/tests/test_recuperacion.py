"""
Pruebas de la recuperación de contraseña SIMULADA (sin correo/SMTP)
adaptadas para pytest.
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
from Utilidades.seguridad import crear_token, hashear_clave  # noqa: E402
import main as app_module  # noqa: E402

CORREO = "usuario@ejemplo.com"
CLAVE_ORIGINAL = "ClaveOriginal1!"
CLAVE_NUEVA = "ClaveNueva2026!"


def _poblar_datos_recuperacion(session_factory):
    db = session_factory()
    try:
        db.add(models.Rol(id=1, nombre="Comprador", descripcion="Comprador"))
        db.add(models.TipoDocumento(codigo="CC", nombre="Cedula de Ciudadania"))
        db.commit()

        for uid, correo, estado, tel in [
            (999, CORREO, "Activo", "3001234567"),
            (998, "inactivo@ejemplo.com", "Inactivo", "3009999999"),
        ]:
            db.add(
                models.Usuario(
                    id=uid,
                    nombre="Usuario Prueba",
                    correo=correo,
                    telefono=tel,
                    clave=hashear_clave(CLAVE_ORIGINAL),
                    estado=estado,
                    rol_id=1,
                    tipo_documento="CC",
                    numero_documento=str(10000000 + uid),
                )
            )
        db.commit()
    finally:
        db.close()


@pytest.fixture(scope="module")
def recuperacion_ctx():
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
    _poblar_datos_recuperacion(session_factory)

    client = TestClient(app_module.app)

    def _login(correo: str, clave: str):
        return client.post("/auth/login", json={"correo": correo, "clave": clave})

    ctx: dict[str, Any] = {
        "client": client,
        "login": _login,
    }

    yield ctx

    client.close()
    database.Base.metadata.drop_all(bind=engine_sqlite)
    engine_sqlite.dispose()
    mp.undo()


def test_flujo_completo(recuperacion_ctx):
    client = recuperacion_ctx["client"]
    login = recuperacion_ctx["login"]

    # 1. Solicitar recuperación: devuelve token simulado (sin enviar correo)
    r = client.post("/auth/recuperar-clave", json={"correo": CORREO})
    assert r.status_code == 200, r.text
    data = r.json()["data"]
    assert data["simulado"] is True
    token = data.get("token_recuperacion")
    assert token, "Debe devolver el token simulado para un usuario activo"

    # 2. Restablecer con ese token
    r = client.post("/auth/restablecer-clave", json={"token": token, "clave_nueva": CLAVE_NUEVA})
    assert r.status_code == 200, r.text

    # 3. La clave nueva funciona y la vieja ya no
    assert login(CORREO, CLAVE_NUEVA).status_code == 200
    assert login(CORREO, CLAVE_ORIGINAL).status_code != 200

    # 4. El token es de un solo uso
    r = client.post("/auth/restablecer-clave", json={"token": token, "clave_nueva": "OtraClave3000!"})
    assert r.status_code != 200, "El token no debe poder reutilizarse"
    assert login(CORREO, CLAVE_NUEVA).status_code == 200


def test_correo_desconocido_o_inactivo_sin_token(recuperacion_ctx):
    client = recuperacion_ctx["client"]
    for correo in ("noexiste@ejemplo.com", "inactivo@ejemplo.com"):
        r = client.post("/auth/recuperar-clave", json={"correo": correo})
        assert r.status_code == 200, r.text
        assert "token_recuperacion" not in r.json()["data"]


def test_tokens_invalidos(recuperacion_ctx):
    client = recuperacion_ctx["client"]

    # Token basura
    r = client.post("/auth/restablecer-clave", json={"token": "basura", "clave_nueva": CLAVE_NUEVA})
    assert r.status_code != 200

    # Un token de SESIÓN no sirve para restablecer
    token_sesion = crear_token({"sub": "999", "correo": CORREO, "rol": "Comprador"})
    r = client.post("/auth/restablecer-clave", json={"token": token_sesion, "clave_nueva": CLAVE_NUEVA})
    assert r.status_code != 200

    # Token de recuperación de un usuario inactivo
    token_inactivo = crear_token({"sub": "998", "tipo": "recuperacion"}, minutos=15)
    r = client.post("/auth/restablecer-clave", json={"token": token_inactivo, "clave_nueva": CLAVE_NUEVA})
    assert r.status_code != 200

    # Un token de recuperación NO sirve para iniciar sesión en la API
    token_rec = crear_token({"sub": "999", "tipo": "recuperacion"}, minutos=15)
    r = client.get("/usuarios/compradores", headers={"Authorization": f"Bearer {token_rec}"})
    assert r.status_code in (401, 403)
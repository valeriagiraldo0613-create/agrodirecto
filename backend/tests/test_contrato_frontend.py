"""
Prueba de contrato frontend <-> backend (adaptada para pytest).

Envía al backend EXACTAMENTE los datos (nombres de campo y tipos) que arma
el frontend en TypeScript (src/services/api.ts y las páginas) y comprueba que
el backend los acepta. Si el frontend cambia un nombre de campo, esta prueba lo detecta.

Correr:
  pytest tests/test_contrato_frontend.py -v
"""
import importlib
import os
import pkgutil
import sys
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, func as _func
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCR_DIR = os.path.join(BACKEND_DIR, "scr")
if SCR_DIR not in sys.path:
    sys.path.insert(0, SCR_DIR)

import Conexion.database as database  # noqa: E402
import Controladores  # noqa: E402
import Modelos.models as models  # noqa: E402
import Utilidades.ids as ids_mod  # noqa: E402
from Utilidades.seguridad import hashear_clave  # noqa: E402
import main as app_module  # noqa: E402

CLAVE = "Clave1234!"


def _siguiente_id_sqlite(db, modelo):
    maximo_bd = db.query(_func.max(modelo.id)).scalar() or 0
    maximo_pendiente = max(
        (obj.id for obj in db.new if isinstance(obj, modelo) and obj.id is not None),
        default=0,
    )
    return max(maximo_bd, maximo_pendiente) + 1


def _poblar_datos_base(session_factory):
    db = session_factory()
    try:
        for rol_id, nombre in [(1, "Administrador"), (2, "Productor"), (3, "Comprador")]:
            db.add(models.Rol(id=rol_id, nombre=nombre, descripcion=nombre))
        db.add(models.TipoDocumento(codigo="CC", nombre="Cedula"))
        db.add(models.Categoria(nombre="Hortaliza"))
        db.commit()

        usuarios = [
            (1, "Admin", "admin@t.com", 1),
            (2, "Prod", "prod@t.com", 2),
            (3, "Comp", "comp@t.com", 3),
        ]
        for uid, nombre, correo, rol_id in usuarios:
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
                )
            )
        db.commit()
    finally:
        db.close()


@pytest.fixture(scope="module")
def api_context(request):
    """Configura SQLite en memoria, parches de ID y TestClient con limpieza al final."""
    mp = pytest.MonkeyPatch()

    engine_sqlite = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    @event.listens_for(engine_sqlite, "connect")
    def _fk_on(conn, _rec):
        conn.execute("PRAGMA foreign_keys=ON")

    testing_session_local = sessionmaker(autocommit=False, autoflush=False, bind=engine_sqlite)

    mp.setattr(database, "engine", engine_sqlite)
    mp.setattr(database, "SessionLocal", testing_session_local)
    mp.setattr(ids_mod, "siguiente_id", _siguiente_id_sqlite)

    for _, modname, _ in pkgutil.iter_modules(Controladores.__path__):
        mod = importlib.import_module(f"Controladores.{modname}")
        if hasattr(mod, "siguiente_id"):
            mp.setattr(mod, "siguiente_id", _siguiente_id_sqlite)

    database.Base.metadata.create_all(bind=engine_sqlite)
    _poblar_datos_base(testing_session_local)

    client = TestClient(app_module.app)

    def _headers_para(correo: str) -> dict[str, str]:
        resp = client.post("/auth/login", json={"correo": correo, "clave": CLAVE})
        assert resp.status_code in (200, 201), f"Login falló para {correo}: {resp.text}"
        token = resp.json()["data"]["token"]
        return {"Authorization": f"Bearer {token}"}

    ctx: dict[str, Any] = {
        "client": client,
        "admin": _headers_para("admin@t.com"),
        "prod": _headers_para("prod@t.com"),
        "comp": _headers_para("comp@t.com"),
    }

    yield ctx

    client.close()
    database.Base.metadata.drop_all(bind=engine_sqlite)
    engine_sqlite.dispose()
    mp.undo()


def _assert_ok(nombre: str, resp, esperados=(200, 201)):
    assert resp.status_code in esperados, f"{nombre} -> {resp.status_code}: {resp.text[:200]}"
    return resp


def test_contrato_panel_administrador(api_context):
    client = api_context["client"]
    admin = api_context["admin"]

    _assert_ok(
        "Crear proveedor",
        client.post(
            "/proveedores",
            headers=admin,
            json={
                "id": 1,
                "nombre": "Transportes Sur",
                "tipo": "Logistica",
                "ciudad": "Cali",
                "telefono": "3001112233",
                "correo": "t@sur.com",
                "estado": "Activo",
            },
        ),
    )
    _assert_ok(
        "Editar proveedor",
        client.put("/proveedores/1", headers=admin, json={"tipo": "Insumos", "ciudad": "Bogotá"}),
    )
    _assert_ok(
        "Crear rol",
        client.post(
            "/roles",
            headers=admin,
            json={"id": 10, "nombre": "Supervisor", "descripcion": "Revisa", "permisos": "leer"},
        ),
    )
    _assert_ok(
        "Crear usuario",
        client.post(
            "/usuarios",
            headers=admin,
            json={
                "id": 55555555,
                "tipo_documento": "CC",
                "numero_documento": "55555555",
                "nombre": "Nuevo",
                "correo": "n@t.com",
                "telefono": "3011111111",
                "clave": "Segura2026!",
                "rol_id": 3,
                "estado": "Activo",
            },
        ),
    )
    _assert_ok(
        "Editar usuario",
        client.put(
            "/usuarios/55555555",
            headers=admin,
            json={
                "nombre": "Nuevo B",
                "correo": "n@t.com",
                "telefono": "3011111111",
                "rol_id": 3,
                "tipo_documento": "CC",
                "estado": "Activo",
            },
        ),
    )
    _assert_ok("Crear categoría", client.post("/categorias", headers=admin, json={"nombre": "Fruta"}))
    _assert_ok(
        "Renombrar categoría",
        client.put("/categorias/Fruta", headers=admin, json={"nombre_nuevo": "Frutas"}),
    )
    _assert_ok(
        "Crear lote desde admin",
        client.post(
            "/lotes",
            headers=admin,
            json={
                "producto": "Tomate",
                "cantidad": 100,
                "categoria": "Hortaliza",
                "productor_id": 2,
                "fecha_cosecha": None,
                "estado": "Activo",
            },
        ),
    )


def test_contrato_productor(api_context):
    client = api_context["client"]
    prod = api_context["prod"]

    _assert_ok(
        "Crear lote productor",
        client.post(
            "/lotes",
            headers=prod,
            json={
                "producto": "Papa",
                "cantidad": 200,
                "categoria": "Hortaliza",
                "estado": "Activo",
                "fecha_cosecha": "2026-12-01",
                "precio_kg": 1500,
                "imagen_url": None,
                "anticipo_pct": 30,
                "horas_limite_pago": 48,
                "productor_id": 2,
            },
        ),
    )

    lotes = _assert_ok("Listar lotes", client.get("/lotes", headers=prod)).json()["data"]
    lote_id = next(l["id"] for l in lotes if l["producto"] == "Papa")
    api_context["lote_id"] = lote_id

    _assert_ok(
        "Editar lote",
        client.put(
            f"/lotes/{lote_id}",
            headers=prod,
            json={
                "producto": "Papa",
                "cantidad": 250,
                "categoria": "Hortaliza",
                "estado": "Activo",
                "fecha_cosecha": None,
                "precio_kg": 1600,
                "imagen_url": None,
                "anticipo_pct": 30,
                "horas_limite_pago": 48,
            },
        ),
    )
    _assert_ok(
        "Reportar incidencia",
        client.post(
            "/incidencias",
            headers=prod,
            json={"lote_id": lote_id, "tipo": "Plaga", "descripcion": "Se detectó plaga"},
        ),
    )


def test_contrato_comprador(api_context):
    client = api_context["client"]
    comp = api_context["comp"]
    lote_id = api_context["lote_id"]

    r = _assert_ok(
        "Reservar",
        client.post("/reservas", headers=comp, json={"comprador_id": 3, "lote_id": lote_id, "cantidad": 10}),
    )
    data_reserva = r.json()["data"]
    assert {"precio_kg", "producto", "cantidad"} <= set(data_reserva)
    api_context["reserva_id"] = data_reserva["id"]

    _assert_ok("Agregar favorito", client.post("/favoritos", headers=comp, json={"comprador_id": 3, "productor_id": 2}))
    _assert_ok("Listar favoritos", client.get("/favoritos?comprador_id=3", headers=comp))
    _assert_ok("Quitar favorito", client.delete("/favoritos/3/2?confirmar=true", headers=comp))


def test_contrato_reserva_pago_entrega_calificacion_disputa(api_context):
    client = api_context["client"]
    prod = api_context["prod"]
    comp = api_context["comp"]
    reserva_id = api_context["reserva_id"]

    _assert_ok(
        "Confirmar reserva",
        client.put(f"/reservas/{reserva_id}/estado", headers=prod, json={"estado": "Confirmada"}),
    )

    r_pago = _assert_ok(
        "Pagar reserva",
        client.post(
            "/pagos",
            headers=comp,
            json={"reserva_id": reserva_id, "metodo": "Simulado - Tarjeta", "resultado_simulado": "aprobado"},
        ),
    )
    d_pago = r_pago.json()["data"]
    assert {"monto", "monto_total_reserva", "monto_pendiente", "reserva_completamente_pagada"} <= set(d_pago)

    r_pagos = _assert_ok("Consultar pagos", client.get(f"/pagos?reserva_id={reserva_id}", headers=comp))
    assert isinstance(r_pagos.json()["data"].get("pagos"), list) and r_pagos.json()["data"]["pagos"]

    r_entrega = _assert_ok(
        "Despachar entrega",
        client.post(
            "/entregas",
            headers=prod,
            json={"reserva_id": reserva_id, "medio": "Camión XYZ-123", "fecha_estimada": "2026-12-02"},
        ),
    )
    codigo = r_entrega.json()["data"].get("codigo_confirmacion")
    assert codigo

    entregas = _assert_ok("Listar entregas", client.get(f"/entregas?reserva_id={reserva_id}", headers=comp)).json()["data"]
    entrega_id = entregas[0]["id"]

    _assert_ok(
        "Actualizar ubicación",
        client.put(f"/entregas/{entrega_id}/ubicacion", headers=prod, json={"latitud": 4.65, "longitud": -74.05}),
    )
    _assert_ok(
        "Confirmar recepción",
        client.put(f"/entregas/{entrega_id}", headers=comp, json={"codigo_confirmacion": codigo}),
    )

    _assert_ok(
        "Calificar",
        client.post("/calificaciones", headers=comp, json={"reserva_id": reserva_id, "estrellas": 5, "comentario": "Excelente"}),
    )
    r_cal = _assert_ok("Listar calificaciones", client.get("/calificaciones?productor_id=2", headers=comp))
    assert isinstance(r_cal.json()["data"].get("calificaciones"), list) and r_cal.json()["data"]["calificaciones"]

    _assert_ok(
        "Abrir disputa",
        client.post("/disputas", headers=comp, json={"reserva_id": reserva_id, "descripcion": "El producto llegó dañado"}),
    )


def test_contrato_soporte_y_contacto(api_context):
    client = api_context["client"]
    comp = api_context["comp"]

    _assert_ok(
        "Contacto público",
        client.post("/soporte", json={"nombre": "Ana", "correo": "ana@x.com", "mensaje": "[Duda] Hola (Tel: 300)"}),
    )
    _assert_ok(
        "Soporte desde panel",
        client.post(
            "/soporte",
            headers=comp,
            json={"usuario_id": 3, "nombre": "Comp", "correo": "comp@t.com", "mensaje": "[Ayuda] No puedo pagar"},
        ),
    )
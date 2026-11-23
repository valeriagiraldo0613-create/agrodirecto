"""
Pruebas de integración end-to-end para AgroDirecto (adaptada para pytest).

Corre la app FastAPI real contra SQLite en memoria (no hay Postgres en este
entorno). Diferencias conocidas entre motores se documentan al final.
"""
from datetime import datetime, timedelta
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
import main as app_module  # noqa: E402


def _siguiente_id_sqlite(db, modelo):
    maximo_bd = db.query(_func.max(modelo.id)).scalar() or 0
    maximo_pendiente = max(
        (obj.id for obj in db.new if isinstance(obj, modelo) and obj.id is not None),
        default=0,
    )
    return max(maximo_bd, maximo_pendiente) + 1


def _dato(resp):
    j = resp.json()
    return j.get("data", j)


@pytest.fixture(scope="module")
def integracion_ctx():
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
    mp.setattr(ids_mod, "siguiente_id", _siguiente_id_sqlite)

    for _, modname, _ in pkgutil.iter_modules(Controladores.__path__):
        mod = importlib.import_module(f"Controladores.{modname}")
        if hasattr(mod, "siguiente_id"):
            mp.setattr(mod, "siguiente_id", _siguiente_id_sqlite)

    database.Base.metadata.create_all(bind=engine_sqlite)

    db = session_factory()
    try:
        db.add_all(
            [
                models.Rol(id=1, nombre="Productor"),
                models.Rol(id=2, nombre="Comprador"),
                models.Rol(id=3, nombre="Administrador"),
            ]
        )
        db.add(models.TipoDocumento(codigo="CC", nombre="Cedula de Ciudadania"))
        db.add_all(
            [
                models.Categoria(nombre="Hortaliza"),
                models.Categoria(nombre="Fruta"),
            ]
        )
        db.commit()
    finally:
        db.close()

    client = TestClient(app_module.app)
    ctx: dict[str, Any] = {
        "client": client,
        "session_factory": session_factory,
    }

    yield ctx

    client.close()
    database.Base.metadata.drop_all(bind=engine_sqlite)
    engine_sqlite.dispose()
    mp.undo()


def _registrar(client: TestClient, uid: int, nombre: str, correo: str, clave: str, rol_id: int, tipo_documento: str = "CC"):
    return client.post(
        "/usuarios",
        json={
            "id": uid,
            "tipo_documento": tipo_documento,
            "numero_documento": f"{100000 + uid}",
            "nombre": nombre,
            "correo": correo,
            "clave": clave,
            "telefono": f"300000{uid:04d}",
            "rol_id": rol_id,
        },
    )


def _login(client: TestClient, correo: str, clave: str):
    return client.post("/auth/login", json={"correo": correo, "clave": clave})


def test_rf01_rf02_registro_y_login(integracion_ctx):
    client = integracion_ctx["client"]

    r = _registrar(client, 1, "Juan Productor", "juan@test.com", "Clave1234!", 1)
    assert r.status_code in (200, 201), r.text

    r = _registrar(client, 2, "Carla Compradora", "carla@test.com", "Clave1234!", 2)
    assert r.status_code in (200, 201), r.text

    r = _registrar(client, 3, "Admin Uno", "admin@test.com", "Clave1234!", 3)
    assert r.status_code in (200, 201), r.text

    r = _registrar(client, 4, "Duplicado", "juan@test.com", "Clave1234!", 2)
    assert r.status_code == 400, r.text

    r = _login(client, "juan@test.com", "Clave1234!")
    token_prod = _dato(r).get("token") if r.status_code == 200 else None
    assert r.status_code == 200 and token_prod, r.text

    r = _login(client, "carla@test.com", "Clave1234!")
    token_comp = _dato(r).get("token") if r.status_code == 200 else None
    assert r.status_code == 200 and token_comp, r.text

    r = _login(client, "admin@test.com", "Clave1234!")
    token_admin = _dato(r).get("token") if r.status_code == 200 else None
    assert r.status_code == 200 and token_admin, r.text

    r = _login(client, "juan@test.com", "clave-incorrecta")
    assert r.status_code == 401, r.text

    integracion_ctx["h_prod"] = {"Authorization": f"Bearer {token_prod}"}
    integracion_ctx["h_comp"] = {"Authorization": f"Bearer {token_comp}"}
    integracion_ctx["h_admin"] = {"Authorization": f"Bearer {token_admin}"}


def test_rnf02_rbac(integracion_ctx):
    client = integracion_ctx["client"]
    h_prod = integracion_ctx["h_prod"]
    h_comp = integracion_ctx["h_comp"]
    h_admin = integracion_ctx["h_admin"]

    r = client.get("/usuarios/1", headers=h_comp)
    assert r.status_code in (200, 403), r.text

    r = client.put("/usuarios/1", json={"nombre": "Hackeado"}, headers=h_comp)
    assert r.status_code == 403, r.text

    r = client.get("/lotes")
    assert r.status_code == 200, r.text

    r = client.post(
        "/lotes",
        json={"id": 99, "producto": "x", "cantidad": 1, "categoria": "Hortaliza", "productor_id": 2},
        headers=h_comp,
    )
    assert r.status_code == 403, r.text

    r = client.get("/reportes/admin", headers=h_prod)
    assert r.status_code == 403, r.text

    r = client.get("/reportes/admin", headers=h_admin)
    assert r.status_code == 200, r.text

    assert client.put("/usuarios/1", json={"nombre": "x"}).status_code == 401


def test_rf06_perfil_productor(integracion_ctx):
    client = integracion_ctx["client"]
    h_prod = integracion_ctx["h_prod"]
    h_comp = integracion_ctx["h_comp"]

    r = client.put(
        "/usuarios/1",
        json={
            "nombre_finca": "Finca La Esperanza",
            "cultivos_principales": "Tomate, lechuga",
            "latitud": 4.6097,
            "longitud": -74.0817,
        },
        headers=h_prod,
    )
    assert r.status_code == 200, r.text

    r = client.put("/usuarios/2", json={"nombre_finca": "Finca Falsa"}, headers=h_comp)
    assert r.status_code == 400, r.text


def test_rf07_rf08_rf11_lotes(integracion_ctx):
    client = integracion_ctx["client"]
    h_prod = integracion_ctx["h_prod"]

    r = client.post(
        "/lotes",
        json={
            "id": 1,
            "producto": "Tomate Chonto",
            "cantidad": 100,
            "categoria": "Hortaliza",
            "productor_id": 1,
            "precio_kg": 2800,
            "imagen_url": "https://ejemplo.com/tomate.jpg",
            "fecha_cosecha": "2026-09-01",
        },
        headers=h_prod,
    )
    assert r.status_code in (200, 201), r.text

    r = client.post(
        "/lotes",
        json={
            "id": 2,
            "producto": "Lote con plazo sin anticipo",
            "cantidad": 50,
            "categoria": "Hortaliza",
            "productor_id": 1,
            "precio_kg": 1000,
            "horas_limite_pago": 24,
        },
        headers=h_prod,
    )
    assert r.status_code in (400, 422), r.text

    r = client.post(
        "/lotes",
        json={
            "id": 2,
            "producto": "Papa Criolla",
            "cantidad": 200,
            "categoria": "Hortaliza",
            "productor_id": 1,
            "precio_kg": 1500,
            "anticipo_pct": 30,
            "horas_limite_pago": 24,
        },
        headers=h_prod,
    )
    assert r.status_code in (200, 201), r.text

    r = client.get("/lotes", params={"precio_min": 1400, "precio_max": 2000})
    lotes_filtrados = _dato(r)
    assert r.status_code == 200 and len(lotes_filtrados) == 1 and lotes_filtrados[0]["id"] == 2, r.text

    r = client.get("/lotes", params={"lat": 4.61, "lon": -74.08, "radio_km": 50})
    lotes_radio = _dato(r)
    assert r.status_code == 200 and len(lotes_radio) >= 1, r.text

    r = client.put("/lotes/1", json={"precio_kg": 9999}, headers=h_prod)
    assert r.status_code == 200, r.text


def test_reservas_stock_cancelacion_y_vencimiento(integracion_ctx):
    client = integracion_ctx["client"]
    h_comp = integracion_ctx["h_comp"]
    session_factory = integracion_ctx["session_factory"]

    r = client.post("/reservas", json={"comprador_id": 2, "lote_id": 1, "cantidad": 20}, headers=h_comp)
    reserva1 = _dato(r)
    assert r.status_code in (200, 201), r.text

    r = client.get("/lotes", params={"productor_id": 1})
    lote1 = next((l for l in _dato(r) if l["id"] == 1), None)
    assert lote1 and lote1["kg_reservados"] == 20, str(lote1)

    r = client.post("/reservas", json={"comprador_id": 2, "lote_id": 1, "cantidad": 999999}, headers=h_comp)
    assert r.status_code in (400, 409, 422), r.text

    r = client.post("/reservas", json={"comprador_id": 2, "lote_id": 2, "cantidad": 10}, headers=h_comp)
    reserva_con_plazo = _dato(r)
    assert r.status_code in (200, 201), r.text
    assert reserva_con_plazo.get("fecha_limite_pago") is not None, str(reserva_con_plazo)

    rid1 = reserva1["id"]
    r = client.put(f"/reservas/{rid1}/estado", json={"estado": "Cancelada"}, headers=h_comp)
    assert r.status_code == 400, r.text

    r = client.put(
        f"/reservas/{rid1}/estado",
        json={"estado": "Cancelada", "motivo_cancelacion": "Cambie de planes"},
        headers=h_comp,
    )
    assert r.status_code == 200, r.text
    assert _dato(r).get("motivo_cancelacion") == "Cambie de planes", r.text

    r = client.get("/lotes", params={"productor_id": 1})
    lote1 = next((l for l in _dato(r) if l["id"] == 1), None)
    assert lote1 and lote1["kg_reservados"] == 0, str(lote1)

    db = session_factory()
    try:
        res_db = db.query(models.Reserva).filter(models.Reserva.id == reserva_con_plazo["id"]).first()
        res_db.fecha_limite_pago = datetime.now() - timedelta(hours=1)
        db.commit()
    finally:
        db.close()

    r = client.get("/reservas", headers=h_comp)
    reservas_actuales = _dato(r)
    reserva_vencida = next((x for x in reservas_actuales if x["id"] == reserva_con_plazo["id"]), None)
    assert reserva_vencida and reserva_vencida["estado"] == "Cancelada", str(reserva_vencida)
    assert reserva_vencida and "plazo" in (reserva_vencida.get("motivo_cancelacion") or "").lower(), str(reserva_vencida)

    r = client.get("/lotes", params={"productor_id": 1})
    lote2 = next((l for l in _dato(r) if l["id"] == 2), None)
    assert lote2 and lote2["kg_reservados"] == 0, str(lote2)


def test_pagos_anticipo_saldo_comision_entregas_calificacion_disputas_y_notificaciones(integracion_ctx):
    client = integracion_ctx["client"]
    h_prod = integracion_ctx["h_prod"]
    h_comp = integracion_ctx["h_comp"]
    h_admin = integracion_ctx["h_admin"]

    r = client.post("/reservas", json={"comprador_id": 2, "lote_id": 1, "cantidad": 15}, headers=h_comp)
    reserva_pago = _dato(r)
    rid_pago = reserva_pago["id"]
    assert r.status_code in (200, 201), r.text

    r = client.put(f"/reservas/{rid_pago}/estado", json={"estado": "Confirmada"}, headers=h_prod)
    assert r.status_code == 200, r.text

    r = client.get("/configuracion/comision")
    comision_actual = _dato(r)["comision_pct"]
    assert comision_actual == 5, str(comision_actual)

    r = client.put("/configuracion/comision", json={"comision_pct": 10}, headers=h_admin)
    assert r.status_code == 200, r.text

    r = client.put("/configuracion/comision", json={"comision_pct": 10}, headers=h_comp)
    assert r.status_code == 403, r.text

    r = client.post("/pagos", json={"reserva_id": rid_pago, "metodo": "Simulado - Tarjeta"}, headers=h_comp)
    pago1 = _dato(r)
    assert r.status_code in (200, 201), r.text
    assert pago1.get("comision_pct") == 10, str(pago1)

    r = client.get("/reservas", params={"lote_id": 1}, headers=h_comp)
    reserva_pagada = next((x for x in _dato(r) if x["id"] == rid_pago), None)
    assert reserva_pagada and reserva_pagada["estado"] == "Pagada", str(reserva_pagada)

    # Anticipo + saldo
    r = client.post("/reservas", json={"comprador_id": 2, "lote_id": 2, "cantidad": 20}, headers=h_comp)
    reserva_anticipo = _dato(r)
    rid_ant = reserva_anticipo["id"]
    client.put(f"/reservas/{rid_ant}/estado", json={"estado": "Confirmada"}, headers=h_prod)

    r = client.get("/pagos", params={"reserva_id": rid_ant}, headers=h_comp)
    resumen = _dato(r)
    monto_anticipo_esperado = resumen.get("monto_anticipo")
    assert monto_anticipo_esperado is not None, str(resumen)

    r = client.post("/pagos", json={"reserva_id": rid_ant, "metodo": "Simulado - Tarjeta", "monto": 1}, headers=h_comp)
    assert r.status_code == 400, r.text

    r = client.post(
        "/pagos",
        json={"reserva_id": rid_ant, "metodo": "Simulado - Tarjeta", "monto": monto_anticipo_esperado},
        headers=h_comp,
    )
    assert r.status_code in (200, 201), r.text

    r = client.get("/reservas", params={"lote_id": 2}, headers=h_comp)
    reserva_tras_anticipo = next((x for x in _dato(r) if x["id"] == rid_ant), None)
    assert reserva_tras_anticipo and reserva_tras_anticipo["estado"] == "Confirmada", str(reserva_tras_anticipo)

    r = client.get("/pagos", params={"reserva_id": rid_ant}, headers=h_comp)
    saldo_pendiente = _dato(r).get("monto_pendiente")

    r = client.post(
        "/pagos",
        json={"reserva_id": rid_ant, "metodo": "Simulado - Tarjeta", "monto": saldo_pendiente},
        headers=h_comp,
    )
    assert r.status_code in (200, 201), r.text

    r = client.get("/reservas", params={"lote_id": 2}, headers=h_comp)
    reserva_final = next((x for x in _dato(r) if x["id"] == rid_ant), None)
    assert reserva_final and reserva_final["estado"] == "Pagada", str(reserva_final)

    # Entregas y calificación
    r = client.post("/entregas", json={"reserva_id": rid_pago, "medio": "Camion propio"}, headers=h_prod)
    entrega1 = _dato(r)
    assert r.status_code in (200, 201), r.text
    codigo = entrega1.get("codigo_confirmacion")
    assert bool(codigo), str(entrega1)

    r = client.put(f"/entregas/{entrega1['id']}", json={"codigo_confirmacion": "0000"}, headers=h_comp)
    assert r.status_code in (400, 404, 409), r.text

    r = client.put(f"/entregas/{entrega1['id']}", json={"codigo_confirmacion": codigo}, headers=h_comp)
    assert r.status_code == 200, r.text

    r = client.post(
        "/calificaciones",
        json={"reserva_id": rid_pago, "estrellas": 5, "comentario": "Excelente"},
        headers=h_comp,
    )
    assert r.status_code in (200, 201), r.text

    r = client.post(
        "/calificaciones",
        json={"reserva_id": rid_pago, "estrellas": 4, "comentario": "otra vez"},
        headers=h_comp,
    )
    assert r.status_code in (400, 409), r.text

    r = client.get("/reportes/productor", headers=h_prod)
    reporte_prod = _dato(r)
    assert reporte_prod.get("total_kg_vendidos", 0) >= 15, str(reporte_prod)
    assert "comision_total" in reporte_prod and "ingresos_netos" in reporte_prod, str(reporte_prod)

    # Disputas y reembolso
    r = client.post("/reservas", json={"comprador_id": 2, "lote_id": 1, "cantidad": 5}, headers=h_comp)
    reserva_disputa = _dato(r)
    rid_disp = reserva_disputa["id"]
    client.put(f"/reservas/{rid_disp}/estado", json={"estado": "Confirmada"}, headers=h_prod)
    client.post("/pagos", json={"reserva_id": rid_disp, "metodo": "Simulado - Tarjeta"}, headers=h_comp)

    r = client.post(
        "/disputas",
        json={"reserva_id": rid_disp, "descripcion": "El producto llego incompleto"},
        headers=h_comp,
    )
    disputa1 = _dato(r)
    assert r.status_code in (200, 201), r.text

    r = client.put(
        f"/disputas/{disputa1['id']}",
        json={"estado": "Resuelta", "resolucion": "Reembolso total", "reembolsar": True},
        headers=h_admin,
    )
    assert r.status_code == 200, r.text

    r = client.get("/pagos", params={"reserva_id": rid_disp}, headers=h_comp)
    pagos_tras_disputa = _dato(r).get("pagos", [])
    assert any(p["estado"] == "Reembolsado" for p in pagos_tras_disputa), str(pagos_tras_disputa)

    # Notificaciones
    r = client.get("/notificaciones", headers=h_prod)
    notifs_productor = _dato(r).get("notificaciones", [])
    assert len(notifs_productor) > 0, str(len(notifs_productor))

    r = client.get("/notificaciones", headers=h_comp)
    notifs_comprador = _dato(r).get("notificaciones", [])
    tipos_recibidos = {n["tipo"] for n in notifs_comprador}
    assert "ReembolsoProcesado" in tipos_recibidos, str(tipos_recibidos)
    assert "PlazoDePago" in tipos_recibidos, str(tipos_recibidos)
    assert "ReservaVencida" in tipos_recibidos, str(tipos_recibidos)

    #######################################################################


def test_categorias_crud_y_validaciones(integracion_ctx):
    client = integracion_ctx["client"]
    h_admin = integracion_ctx["h_admin"]

    nombre = "CategoriaPruebaCobertura"
    nombre_nuevo = "CategoriaPruebaActualizada"

    # 1. Consultar las categorías existentes
    r = client.get("/categorias")
    assert r.status_code == 200, r.text
    assert isinstance(_dato(r), list)

    # 2. Crear una categoría como administrador
    r = client.post(
        "/categorias",
        json={"nombre": nombre},
        headers=h_admin,
    )
    assert r.status_code == 201, r.text

    # La API normaliza el nombre antes de guardarlo
    nombre = _dato(r)["nombre"]
    assert nombre == "Categoriapruebacobertura"

    # 3. Intentar crear una categoría duplicada
    r = client.post(
        "/categorias",
        json={"nombre": nombre},
        headers=h_admin,
    )
    assert r.status_code in (400, 409), r.text

    # 4. Actualizar el nombre de la categoría
    r = client.put(
        f"/categorias/{nombre}",
        json={"nombre_nuevo": nombre_nuevo},
        headers=h_admin,
    )
    assert r.status_code == 200, r.text

    # Guardar el nombre normalizado que devuelve la API
    nombre_nuevo = _dato(r)["nombre"]
    assert nombre_nuevo == "Categoriapruebaactualizada"

    # 5. Intentar renombrarla con un nombre que ya existe
    r = client.put(
        f"/categorias/{nombre_nuevo}",
        json={"nombre_nuevo": "Fruta"},
        headers=h_admin,
    )
    assert r.status_code in (400, 409), r.text

    # 6. Intentar actualizar una categoría inexistente
    r = client.put(
        "/categorias/CategoriaInexistente",
        json={"nombre_nuevo": "OtroNombre"},
        headers=h_admin,
    )
    assert r.status_code in (400, 404), r.text

    # 7. Consultar lotes de una categoría inexistente
    r = client.get("/categorias/CategoriaInexistente/lotes")
    assert r.status_code in (400, 404), r.text

    # 8. Consultar lotes de una categoría existente
    r = client.get(
        "/categorias/Hortaliza/lotes",
        params={
            "cantidad_min": 0,
            "ordenar": True,
            "limite": 10,
            "solo_activos": True,
        },
    )
    assert r.status_code == 200, r.text

    # 9. Verificar el límite mínimo de cantidad
    r = client.get(
        "/categorias/Hortaliza/lotes",
        params={"cantidad_min": -1},
    )
    assert r.status_code == 422, r.text

    # 10. No permitir eliminar una categoría que tiene lotes
    r = client.delete(
        "/categorias/Hortaliza",
        headers=h_admin,
    )
    assert r.status_code in (400, 409), r.text

    # 11. Eliminar la categoría de prueba, que no tiene lotes
    r = client.delete(
        f"/categorias/{nombre_nuevo}",
        headers=h_admin,
    )
    assert r.status_code == 200, r.text
    assert _dato(r)["nombre"] == nombre_nuevo

    # 12. Intentar eliminar una categoría inexistente
    r = client.delete(
        "/categorias/CategoriaInexistente",
        headers=h_admin,
    )
    assert r.status_code in (400, 404), r.text

    # 13. Verificar que no se pueda crear sin autenticación
    r = client.post(
        "/categorias",
        json={"nombre": "CategoriaSinPermiso"},
    )
    assert r.status_code == 401, r.text

    # 14. Verificar que no se pueda eliminar sin autenticación
    r = client.delete("/categorias/Fruta")
    assert r.status_code == 401, r.text

################################################################################


def test_tipos_documento_crud_y_validaciones(integracion_ctx):
    client = integracion_ctx["client"]
    h_admin = integracion_ctx["h_admin"]

    codigo = "TDV"
    codigo_nuevo = "TD2"
    nombre = "Tipo Documento Cobertura"
    nombre_nuevo = "Tipo Documento Cobertura Actualizado"

    # 1. Consultar todos los tipos de documento
    r = client.get("/tipos_documento")
    assert r.status_code == 200, r.text
    assert isinstance(_dato(r), list)

    # 2. Consultar un tipo existente (CC)
    r = client.get("/tipos_documento/CC")
    assert r.status_code == 200, r.text
    assert _dato(r)["codigo"] == "CC"

    # 3. Consultar un tipo inexistente
    r = client.get("/tipos_documento/XYZ")
    assert r.status_code == 404, r.text

    # 4. Consultar con código vacío
    r = client.get("/tipos_documento/%20%20%20")
    assert r.status_code == 400, r.text

    # 5. Crear un tipo de documento
    r = client.post(
        "/tipos_documento",
        json={"codigo": codigo.lower(), "nombre": nombre},
        headers=h_admin,
    )
    assert r.status_code == 201, r.text
    assert _dato(r)["codigo"] == codigo

    # 6. Intentar crear un código duplicado
    r = client.post(
        "/tipos_documento",
        json={"codigo": codigo, "nombre": "Otro Nombre"},
        headers=h_admin,
    )
    assert r.status_code == 400, r.text

    # 7. Intentar crear un nombre duplicado
    r = client.post(
        "/tipos_documento",
        json={"codigo": codigo_nuevo, "nombre": _dato(
            client.get("/tipos_documento/CC")
        )["nombre"]},
        headers=h_admin,
    )
    assert r.status_code == 400, r.text

    # 8. Actualizar el tipo de documento
    r = client.put(
        f"/tipos_documento/{codigo}",
        json={"nombre": nombre_nuevo},
        headers=h_admin,
    )
    assert r.status_code == 200, r.text
    assert _dato(r)["nombre"] == nombre_nuevo

    # 9. Actualizar un código inexistente
    r = client.put(
        "/tipos_documento/INEXISTENTE",
        json={"nombre": "Otro Nombre"},
        headers=h_admin,
    )
    assert r.status_code == 404, r.text

    # 10. Intentar actualizar con un nombre duplicado
    nombre_cc = _dato(
        client.get("/tipos_documento/CC")
    )["nombre"]

    r = client.put(
        f"/tipos_documento/{codigo}",
        json={"nombre": nombre_cc},
        headers=h_admin,
    )
    assert r.status_code == 400, r.text

    # 11. Intentar eliminar sin confirmar
    r = client.delete(
        f"/tipos_documento/{codigo}",
        headers=h_admin,
    )
    assert r.status_code == 400, r.text

    # 12. Intentar eliminar un tipo inexistente
    r = client.delete(
        "/tipos_documento/INEXISTENTE?confirmar=true",
        headers=h_admin,
    )
    assert r.status_code == 404, r.text

    # 13. Eliminar el tipo creado correctamente
    r = client.delete(
        f"/tipos_documento/{codigo}?confirmar=true",
        headers=h_admin,
    )
    assert r.status_code == 200, r.text
    assert _dato(r)["codigo"] == codigo

    # 14. Comprobar que ya no existe
    r = client.get(f"/tipos_documento/{codigo}")
    assert r.status_code == 404, r.text

    # 15. Intentar eliminar CC, que tiene usuarios asociados
    r = client.delete(
        "/tipos_documento/CC?confirmar=true",
        headers=h_admin,
    )
    assert r.status_code == 409, r.text

    # 16. Intentar crear sin autenticación
    r = client.post(
        "/tipos_documento",
        json={"codigo": "SINAUTH", "nombre": "Sin Autenticación"},
    )
    assert r.status_code == 401, r.text

    # 17. Intentar actualizar sin autenticación
    r = client.put(
        "/tipos_documento/CC",
        json={"nombre": "Cambio No Autorizado"},
    )
    assert r.status_code == 401, r.text

    # 18. Intentar eliminar sin autenticación
    r = client.delete(
        "/tipos_documento/CC?confirmar=true",
    )
    assert r.status_code == 401, r.text

##########################################################################################


def test_roles_crud_y_validaciones(integracion_ctx):
    client = integracion_ctx["client"]
    h_admin = integracion_ctx["h_admin"]

    rol_id = 90
    rol_id_nuevo = 91

    nombre = "RolPruebaCobertura"
    nombre_nuevo = "RolPruebaActualizado"

    # 1. Consultar todos los roles
    r = client.get("/roles")
    assert r.status_code == 200, r.text
    assert isinstance(_dato(r), list)

    # 2. Consultar un rol existente
    r = client.get("/roles/1")
    assert r.status_code == 200, r.text

    # 3. Consultar un ID inexistente
    r = client.get("/roles/9999")
    assert r.status_code == 404, r.text

    # 4. Consultar un ID negativo
    r = client.get("/roles/-1")
    assert r.status_code == 400, r.text

    # 5. Crear un rol
    r = client.post(
        "/roles",
        json={
            "id": rol_id,
            "nombre": nombre,
            "descripcion": "Rol para pruebas de cobertura",
            "permisos": "consultar",
        },
        headers=h_admin,
    )
    assert r.status_code == 201, r.text
    assert _dato(r)["id"] == rol_id

    # 6. Crear un ID duplicado
    r = client.post(
        "/roles",
        json={
            "id": rol_id,
            "nombre": "Otro Rol",
        },
        headers=h_admin,
    )
    assert r.status_code == 400, r.text

    # 7. Crear un nombre duplicado
    r = client.post(
        "/roles",
        json={
            "id": rol_id_nuevo,
            "nombre": nombre,
        },
        headers=h_admin,
    )
    assert r.status_code == 400, r.text

    # 8. Validar ID no positivo al crear
    r = client.post(
        "/roles",
        json={
            "id": 0,
            "nombre": "Rol Invalido",
        },
        headers=h_admin,
    )
    assert r.status_code == 422, r.text

    # 9. Validar nombre vacío al crear
    r = client.post(
        "/roles",
        json={
            "id": rol_id_nuevo,
            "nombre": "   ",
        },
        headers=h_admin,
    )
    assert r.status_code == 422, r.text

    # 10. Actualizar nombre, descripción y permisos
    r = client.put(
        f"/roles/{rol_id}",
        json={
            "nombre": nombre_nuevo,
            "descripcion": "Descripción actualizada",
            "permisos": "consultar,editar",
        },
        headers=h_admin,
    )
    assert r.status_code == 200, r.text
    assert _dato(r)["nombre"] == nombre_nuevo
    assert _dato(r)["descripcion"] == "Descripción actualizada"
    assert _dato(r)["permisos"] == "consultar,editar"

    # 11. Actualizar únicamente la descripción
    r = client.put(
        f"/roles/{rol_id}",
        json={"descripcion": "Solo descripción"},
        headers=h_admin,
    )
    assert r.status_code == 200, r.text
    assert _dato(r)["descripcion"] == "Solo descripción"

    # 12. Actualizar únicamente los permisos
    r = client.put(
        f"/roles/{rol_id}",
        json={"permisos": "consultar"},
        headers=h_admin,
    )
    assert r.status_code == 200, r.text
    assert _dato(r)["permisos"] == "consultar"

    # 13. Actualizar un rol inexistente
    r = client.put(
        "/roles/9999",
        json={"nombre": "Otro Nombre"},
        headers=h_admin,
    )
    assert r.status_code == 404, r.text

    # 14. Actualizar con ID negativo
    r = client.put(
        "/roles/-1",
        json={"nombre": "Otro Nombre"},
        headers=h_admin,
    )
    assert r.status_code == 400, r.text

    # 15. Intentar actualizar con nombre duplicado
    r = client.put(
        f"/roles/{rol_id}",
        json={"nombre": "Administrador"},
        headers=h_admin,
    )
    assert r.status_code == 400, r.text

    # 16. Intentar actualizar con nombre vacío
    r = client.put(
        f"/roles/{rol_id}",
        json={"nombre": "   "},
        headers=h_admin,
    )
    assert r.status_code == 422, r.text

    # 17. Intentar eliminar sin confirmar
    r = client.delete(
        f"/roles/{rol_id}",
        headers=h_admin,
    )
    assert r.status_code == 400, r.text

    # 18. Intentar eliminar con ID negativo
    r = client.delete(
        "/roles/-1?confirmar=true",
        headers=h_admin,
    )
    assert r.status_code == 400, r.text

    # 19. Intentar eliminar un rol inexistente
    r = client.delete(
        "/roles/9999?confirmar=true",
        headers=h_admin,
    )
    assert r.status_code == 404, r.text

    # 20. Eliminar el rol de prueba
    r = client.delete(
        f"/roles/{rol_id}?confirmar=true",
        headers=h_admin,
    )
    assert r.status_code == 200, r.text
    assert _dato(r)["id"] == rol_id

    # 21. Comprobar que ya no existe
    r = client.get(f"/roles/{rol_id}")
    assert r.status_code == 404, r.text

    # 22. Intentar eliminar un rol utilizado por usuarios
    r = client.delete(
        "/roles/1?confirmar=true",
        headers=h_admin,
    )
    assert r.status_code == 409, r.text

    # 23. Intentar crear sin autenticación
    r = client.post(
        "/roles",
        json={"id": 92, "nombre": "RolSinPermiso"},
    )
    assert r.status_code == 401, r.text

    # 24. Intentar actualizar sin autenticación
    r = client.put(
        "/roles/1",
        json={"nombre": "CambioNoAutorizado"},
    )
    assert r.status_code == 401, r.text

    # 25. Intentar eliminar sin autenticación
    r = client.delete(
        "/roles/1?confirmar=true",
    )
    assert r.status_code == 401, r.text

#####################################################################


def test_soporte_crud_y_validaciones(integracion_ctx):
    client = integracion_ctx["client"]
    h_admin = integracion_ctx["h_admin"]

    # 1. Crear un ticket de soporte sin autenticación
    r = client.post(
        "/soporte",
        json={
            "nombre": "Usuario Prueba",
            "correo": "soporte.prueba@example.com",
            "mensaje": "Necesito ayuda con mi cuenta."
        }
    )
    assert r.status_code == 201, r.text

    ticket = _dato(r)
    soporte_id = ticket["id"]

    assert ticket["nombre"] == "Usuario Prueba"
    assert ticket["correo"] == "soporte.prueba@example.com"
    assert ticket["mensaje"] == "Necesito ayuda con mi cuenta."
    assert ticket["estado"] == "Pendiente"
    assert ticket["id"] is not None

    # 2. Crear otro ticket
    r = client.post(
        "/soporte",
        json={
            "nombre": "Segundo Usuario",
            "correo": "segundo@example.com",
            "mensaje": "Tengo una consulta sobre una reserva."
        }
    )
    assert r.status_code == 201, r.text

    segundo_id = _dato(r)["id"]

    # 3. Consultar todos los tickets como administrador
    r = client.get("/soporte", headers=h_admin)
    assert r.status_code == 200, r.text
    assert isinstance(_dato(r), list)

    ids = [ticket["id"] for ticket in _dato(r)]
    assert soporte_id in ids
    assert segundo_id in ids

    # 4. Filtrar tickets por estado Pendiente
    r = client.get(
        "/soporte?estado=Pendiente",
        headers=h_admin
    )
    assert r.status_code == 200, r.text
    assert all(t["estado"] == "Pendiente" for t in _dato(r))

    # 5. Filtrar por un estado sin tickets
    r = client.get(
        "/soporte?estado=EstadoInexistente",
        headers=h_admin
    )
    assert r.status_code == 200, r.text
    assert _dato(r) == []

    # 6. Actualizar estado a En proceso
    r = client.put(
        f"/soporte/{soporte_id}/estado",
        json={"estado": "En proceso"},
        headers=h_admin
    )
    assert r.status_code == 200, r.text
    assert _dato(r)["estado"] == "En proceso"

    # 7. Actualizar estado a Resuelto
    r = client.put(
        f"/soporte/{soporte_id}/estado",
        json={"estado": "Resuelto"},
        headers=h_admin
    )
    assert r.status_code == 200, r.text
    assert _dato(r)["estado"] == "Resuelto"

    # 8. Intentar actualizar con un estado inválido
    r = client.put(
        f"/soporte/{soporte_id}/estado",
        json={"estado": "Cancelado"},
        headers=h_admin
    )
    assert r.status_code == 422, r.text

    # 9. Intentar actualizar un ticket inexistente
    r = client.put(
        "/soporte/999999/estado",
        json={"estado": "Resuelto"},
        headers=h_admin
    )
    assert r.status_code == 404, r.text

    # 10. Validar nombre vacío
    r = client.post(
        "/soporte",
        json={
            "nombre": "   ",
            "correo": "invalido@example.com",
            "mensaje": "Mensaje de prueba"
        }
    )
    assert r.status_code == 422, r.text

    # 11. Validar mensaje vacío
    r = client.post(
        "/soporte",
        json={
            "nombre": "Usuario Prueba",
            "correo": "invalido@example.com",
            "mensaje": "   "
        }
    )
    assert r.status_code == 422, r.text

    # 12. Validar correo incorrecto
    r = client.post(
        "/soporte",
        json={
            "nombre": "Usuario Prueba",
            "correo": "correo_incorrecto",
            "mensaje": "Mensaje de prueba"
        }
    )
    assert r.status_code == 422, r.text

    # 13. Validar campos obligatorios
    r = client.post(
        "/soporte",
        json={"nombre": "Usuario Prueba"}
    )
    assert r.status_code == 422, r.text

    # 14. Intentar eliminar sin confirmar
    r = client.delete(
        f"/soporte/{soporte_id}",
        headers=h_admin
    )
    assert r.status_code == 400, r.text

    # 15. Intentar eliminar un ticket inexistente
    r = client.delete(
        "/soporte/999999?confirmar=true",
        headers=h_admin
    )
    assert r.status_code == 404, r.text

    # 16. Eliminar el primer ticket
    r = client.delete(
        f"/soporte/{soporte_id}?confirmar=true",
        headers=h_admin
    )
    assert r.status_code == 200, r.text
    assert _dato(r)["id"] == soporte_id

    # 17. Eliminar el segundo ticket
    r = client.delete(
        f"/soporte/{segundo_id}?confirmar=true",
        headers=h_admin
    )
    assert r.status_code == 200, r.text

    # 18. Comprobar que los tickets fueron eliminados
    r = client.get("/soporte", headers=h_admin)
    assert r.status_code == 200, r.text

    ids_finales = [ticket["id"] for ticket in _dato(r)]
    assert soporte_id not in ids_finales
    assert segundo_id not in ids_finales

    # 19. Comprobar que consultar tickets requiere administrador
    r = client.get("/soporte")
    assert r.status_code == 401, r.text

    # 20. Comprobar que actualizar requiere administrador
    r = client.put(
        "/soporte/1/estado",
        json={"estado": "Resuelto"}
    )
    assert r.status_code == 401, r.text

    # 21. Comprobar que eliminar requiere administrador
    r = client.delete("/soporte/1?confirmar=true")
    assert r.status_code == 401, r.text

#######################################################################


def test_proveedores_crud_y_validaciones(integracion_ctx):
    client = integracion_ctx["client"]
    h_admin = integracion_ctx["h_admin"]

    # 1. Consultar proveedores
    respuesta = client.get("/proveedores")
    assert respuesta.status_code == 200
    assert respuesta.json()["message"] == "Proveedores obtenidos"

    # Datos para crear un proveedor
    proveedor = {
        "id": 9801,
        "nombre": "Proveedor Prueba TDD",
        "tipo": "Agrícola",
        "ciudad": "Bogotá",
        "telefono": "3001234567",
        "correo": "proveedortdd@example.com",
        "estado": "Activo"
    }

    # 2. Crear proveedor
    respuesta = client.post(
        "/proveedores",
        json=proveedor,
        headers=h_admin
    )
    assert respuesta.status_code == 201

    datos = respuesta.json()["data"]
    assert datos["id"] == 9801
    assert datos["nombre"] == "Proveedor Prueba TDD"
    assert datos["tipo"] == "Agrícola"
    assert datos["ciudad"] == "Bogotá"
    assert datos["estado"] == "Activo"

    # 3. Consultar proveedor por ID
    respuesta = client.get("/proveedores/9801")
    assert respuesta.status_code == 200
    assert respuesta.json()["data"]["id"] == 9801

    # 4. Intentar crear un ID duplicado
    respuesta = client.post(
        "/proveedores",
        json={
            **proveedor,
            "nombre": "Otro proveedor"
        },
        headers=h_admin
    )
    assert respuesta.status_code == 400

    # 5. Intentar crear un nombre duplicado
    respuesta = client.post(
        "/proveedores",
        json={
            **proveedor,
            "id": 9802
        },
        headers=h_admin
    )
    assert respuesta.status_code == 400

    # 6. Consultar con ID negativo
    respuesta = client.get("/proveedores/-1")
    assert respuesta.status_code == 400

    # 7. Consultar proveedor inexistente
    respuesta = client.get("/proveedores/99999")
    assert respuesta.status_code == 404

    # 8. Actualizar proveedor
    respuesta = client.put(
        "/proveedores/9801",
        json={
            "nombre": "Proveedor Actualizado TDD",
            "ciudad": "Medellín",
            "telefono": "3119876543",
            "estado": "Inactivo"
        },
        headers=h_admin
    )
    assert respuesta.status_code == 200

    datos = respuesta.json()["data"]
    assert datos["nombre"] == "Proveedor Actualizado TDD"
    assert datos["ciudad"] == "Medellín"
    assert datos["telefono"] == "3119876543"
    assert datos["estado"] == "Inactivo"

    # 9. Intentar actualizar con ID negativo
    respuesta = client.put(
        "/proveedores/-1",
        json={"nombre": "Nombre inválido"},
        headers=h_admin
    )
    assert respuesta.status_code == 400

    # 10. Intentar actualizar proveedor inexistente
    respuesta = client.put(
        "/proveedores/99999",
        json={"nombre": "No existe"},
        headers=h_admin
    )
    assert respuesta.status_code == 404

    # 11. Intentar duplicar el nombre de otro proveedor
    respuesta = client.post(
        "/proveedores",
        json={
            "id": 9803,
            "nombre": "Proveedor Segundo TDD",
            "tipo": "Comercial",
            "estado": "Activo"
        },
        headers=h_admin
    )
    assert respuesta.status_code == 201

    respuesta = client.put(
        "/proveedores/9803",
        json={"nombre": "Proveedor Actualizado TDD"},
        headers=h_admin
    )
    assert respuesta.status_code == 400

    # 12. Intentar eliminar sin confirmación
    respuesta = client.delete(
        "/proveedores/9801",
        headers=h_admin
    )
    assert respuesta.status_code == 400

    # 13. Intentar eliminar con ID negativo
    respuesta = client.delete(
        "/proveedores/-1?confirmar=true",
        headers=h_admin
    )
    assert respuesta.status_code == 400

    # 14. Intentar eliminar proveedor inexistente
    respuesta = client.delete(
        "/proveedores/99999?confirmar=true",
        headers=h_admin
    )
    assert respuesta.status_code == 404

    # 15. Eliminar proveedor correctamente
    respuesta = client.delete(
        "/proveedores/9801?confirmar=true",
        headers=h_admin
    )
    assert respuesta.status_code == 200

    assert respuesta.json()["data"]["id"] == 9801

    # 16. Verificar que ya no existe
    respuesta = client.get("/proveedores/9801")
    assert respuesta.status_code == 404

    # 17. Eliminar el segundo proveedor de prueba
    respuesta = client.delete(
        "/proveedores/9803?confirmar=true",
        headers=h_admin
    )
    assert respuesta.status_code == 200

######################################################################################


def test_lotes_cobertura_adicional(integracion_ctx):
    client = integracion_ctx["client"]
    h_prod = integracion_ctx["h_prod"]
    h_admin = integracion_ctx["h_admin"]
    h_comp = integracion_ctx["h_comp"]
    session_factory = integracion_ctx["session_factory"]

    # ---------------------------------------------------------
    # 1. Crear lotes adicionales para probar diferentes casos
    # ---------------------------------------------------------

    def crear_lote(producto, cantidad=100, precio=2000):
        respuesta = client.post(
            "/lotes",
            json={
                "producto": producto,
                "cantidad": cantidad,
                "categoria": "Fruta",
                "productor_id": 1,
                "precio_kg": precio,
            },
            headers=h_prod,
        )
        assert respuesta.status_code in (200, 201), respuesta.text
        return _dato(respuesta)

    lote_eliminar = crear_lote("Lote Para Eliminar")
    lote_historial = crear_lote("Lote Con Historial")
    lote_reservado = crear_lote("Lote Con Reserva")
    lote_edicion = crear_lote("Lote Para Editar")

    id_eliminar = lote_eliminar["id"]
    id_historial = lote_historial["id"]
    id_reservado = lote_reservado["id"]
    id_edicion = lote_edicion["id"]

    # ---------------------------------------------------------
    # 2. Buscar lotes por nombre de producto
    # ---------------------------------------------------------

    r = client.get("/lotes/Tomate")
    assert r.status_code == 200, r.text
    assert isinstance(_dato(r), list)

    r = client.get("/lotes/ProductoQueNoExiste")
    assert r.status_code == 404, r.text

    r = client.get("/lotes/%20%20%20")
    assert r.status_code == 400, r.text

    # ---------------------------------------------------------
    # 3. Probar filtros adicionales
    # ---------------------------------------------------------

    r = client.get("/lotes", params={"categoria": "Fruta"})
    assert r.status_code == 200, r.text
    assert all(x["categoria"] == "Fruta" for x in _dato(r))

    r = client.get("/lotes", params={"estado": "Activo"})
    assert r.status_code == 200, r.text

    r = client.get("/lotes", params={"productor_id": 1})
    assert r.status_code == 200, r.text

    r = client.get("/lotes", params={"precio_min": 5000})
    assert r.status_code == 200, r.text

    r = client.get("/lotes", params={"precio_max": 1000})
    assert r.status_code == 200, r.text

    r = client.get(
        "/lotes",
        params={
            "cosecha_desde": "2026-01-01",
            "cosecha_hasta": "2026-12-31",
        },
    )
    assert r.status_code == 200, r.text

    # Radio pequeño: los lotes del productor pueden quedar fuera.
    r = client.get(
        "/lotes",
        params={
            "lat": 0,
            "lon": 0,
            "radio_km": 1,
        },
    )
    assert r.status_code == 200, r.text

    # ---------------------------------------------------------
    # 4. Validaciones de creación
    # ---------------------------------------------------------

    r = client.post(
        "/lotes",
        json={
            "producto": "Categoria Invalida",
            "cantidad": 10,
            "categoria": "CategoriaQueNoExiste",
            "productor_id": 1,
        },
        headers=h_prod,
    )
    assert r.status_code in (400, 422), r.text

    r = client.post(
        "/lotes",
        json={
            "producto": "Productor Inexistente",
            "cantidad": 10,
            "categoria": "Fruta",
            "productor_id": 99999,
        },
        headers=h_admin,
    )
    assert r.status_code == 404, r.text

    r = client.post(
        "/lotes",
        json={
            "producto": "Usuario Comprador",
            "cantidad": 10,
            "categoria": "Fruta",
            "productor_id": 2,
        },
        headers=h_admin,
    )
    assert r.status_code == 400, r.text

    # ---------------------------------------------------------
    # 5. Edición: validaciones y reglas comerciales
    # ---------------------------------------------------------

    r = client.put(
        "/lotes/0",
        json={"producto": "Producto"},
        headers=h_prod,
    )
    assert r.status_code == 400, r.text

    r = client.put(
        "/lotes/99999",
        json={"producto": "Producto"},
        headers=h_prod,
    )
    assert r.status_code in (404, 400), r.text

    r = client.put(
        f"/lotes/{id_edicion}",
        json={"producto": "   "},
        headers=h_prod,
    )
    assert r.status_code == 400, r.text

    r = client.put(
        f"/lotes/{id_edicion}",
        json={"categoria": "CategoriaInexistente"},
        headers=h_prod,
    )
    assert r.status_code in (400, 422), r.text

    r = client.put(
        f"/lotes/{id_edicion}",
        json={"horas_limite_pago": 24},
        headers=h_prod,
    )
    assert r.status_code == 400, r.text

    r = client.put(
        f"/lotes/{id_edicion}",
        json={
            "anticipo_pct": 30,
            "horas_limite_pago": 24,
        },
        headers=h_prod,
    )
    assert r.status_code == 200, r.text

    # ---------------------------------------------------------
    # 6. Reservas: bloquear cambios comerciales
    # ---------------------------------------------------------

    db = session_factory()
    try:
        db.add(
            models.Reserva(
                comprador_id=2,
                lote_id=id_reservado,
                cantidad=10,
                estado="Confirmada",
            )
        )
        db.add(
            models.Reserva(
                comprador_id=2,
                lote_id=id_historial,
                cantidad=5,
                estado="Cancelada",
            )
        )
        db.add(
            models.Reserva(
                comprador_id=2,
                lote_id=id_edicion,
                cantidad=5,
                estado="Confirmada",
            )
        )
        db.commit()
    finally:
        db.close()

    r = client.put(
        f"/lotes/{id_edicion}",
        json={"precio_kg": 3000},
        headers=h_prod,
    )
    assert r.status_code == 409, r.text

    # El administrador sí puede cambiar términos comerciales.
    r = client.put(
        f"/lotes/{id_edicion}",
        json={"precio_kg": 3500},
        headers=h_admin,
    )
    assert r.status_code == 200, r.text

    # ---------------------------------------------------------
    # 7. Eliminación: validaciones y reservas activas
    # ---------------------------------------------------------

    r = client.delete(
        f"/lotes/{id_eliminar}",
        headers=h_prod,
    )
    assert r.status_code == 400, r.text

    r = client.delete(
        "/lotes/0?confirmar=true",
        headers=h_prod,
    )
    assert r.status_code == 400, r.text

    r = client.delete(
        "/lotes/99999?confirmar=true",
        headers=h_prod,
    )
    assert r.status_code in (404, 400), r.text

    r = client.delete(
        f"/lotes/{id_reservado}?confirmar=true",
        headers=h_prod,
    )
    assert r.status_code == 409, r.text

    # Si existe historial, debe ocultarse y no borrarse.
    r = client.delete(
        f"/lotes/{id_historial}?confirmar=true",
        headers=h_prod,
    )
    assert r.status_code == 200, r.text
    assert _dato(r)["eliminado"] is False
    assert _dato(r)["estado"] == "Inactivo"

    # Si no tiene reservas ni historial, se elimina.
    r = client.delete(
        f"/lotes/{id_eliminar}?confirmar=true",
        headers=h_prod,
    )
    assert r.status_code == 200, r.text
    assert _dato(r)["eliminado"] is True

    # ---------------------------------------------------------
    # 8. Estado del cultivo y trazabilidad
    # ---------------------------------------------------------

    # Crear una reserva activa para comprobar las notificaciones.
    db = session_factory()
    try:
        db.add(
            models.Reserva(
                comprador_id=2,
                lote_id=id_reservado,
                cantidad=5,
                estado="Pendiente",
            )
        )
        db.commit()
    finally:
        db.close()

    r = client.put(
        f"/lotes/{id_reservado}/estado-cultivo",
        json={"estado_cultivo": "Crecimiento"},
        headers=h_prod,
    )
    assert r.status_code == 200, r.text
    assert _dato(r)["estado_cultivo"] == "Crecimiento"

    # No puede saltar etapas.
    r = client.put(
        f"/lotes/{id_reservado}/estado-cultivo",
        json={"estado_cultivo": "Cosechado"},
        headers=h_prod,
    )
    assert r.status_code == 409, r.text

    # El administrador puede avanzar directamente.
    r = client.put(
        f"/lotes/{id_reservado}/estado-cultivo",
        json={"estado_cultivo": "Cosechado"},
        headers=h_admin,
    )
    assert r.status_code == 200, r.text

    # Consultar el historial.
    r = client.get(f"/lotes/{id_reservado}/historial")
    assert r.status_code == 200, r.text
    assert len(_dato(r)) >= 2

    # Historial de lote inexistente.
    r = client.get("/lotes/99999/historial")
    assert r.status_code == 404, r.text

    # Lote inexistente al actualizar el estado.
    r = client.put(
        "/lotes/99999/estado-cultivo",
        json={"estado_cultivo": "Crecimiento"},
        headers=h_prod,
    )
    assert r.status_code == 404, r.text

    # ---------------------------------------------------------
    # 9. Verificar permisos y autenticación
    # ---------------------------------------------------------

    r = client.post(
        "/lotes",
        json={
            "producto": "Sin Autenticación",
            "cantidad": 10,
            "categoria": "Fruta",
            "productor_id": 1,
        },
    )
    assert r.status_code == 401, r.text

    r = client.put(
        f"/lotes/{id_reservado}",
        json={"producto": "Cambio Comprador"},
        headers=h_comp,
    )
    assert r.status_code == 403, r.text

    r = client.delete(
        f"/lotes/{id_reservado}?confirmar=true",
        headers=h_comp,
    )
    assert r.status_code == 403, r.text

###################################################################################


def test_notificaciones_cobertura_adicional(integracion_ctx):
    from Modelos.models import Notificacion

    client = integracion_ctx["client"]
    session_factory = integracion_ctx["session_factory"]

    # Obtener los encabezados de autenticación
    h_prod = integracion_ctx["h_prod"]
    h_comp = integracion_ctx["h_comp"]

    # Crear notificaciones para el productor y el comprador
    with session_factory() as db:
        notificacion_leida = Notificacion(
            usuario_id=1,
            tipo="NuevaReserva",
            mensaje="Un comprador realizó una reserva",
            leida=True,
        )

        notificacion_pendiente = Notificacion(
            usuario_id=1,
            tipo="PagoRecibido",
            mensaje="Se recibió un pago",
            leida=False,
        )

        notificacion_comprador = Notificacion(
            usuario_id=2,
            tipo="ReservaVencida",
            mensaje="Tu reserva ha vencido",
            leida=False,
        )

        db.add_all([
            notificacion_leida,
            notificacion_pendiente,
            notificacion_comprador,
        ])
        db.commit()

        id_pendiente = notificacion_pendiente.id

    # 1. Consultar notificaciones del productor
    r = client.get("/notificaciones", headers=h_prod)
    assert r.status_code == 200

    data = _dato(r)

    assert "notificaciones" in data
    assert "no_leidas" in data
    assert data["no_leidas"] >= 1

    # 2. Comprobar los datos serializados
    notificaciones = data["notificaciones"]

    pendiente = next(
        n for n in notificaciones
        if n["id"] == id_pendiente
    )

    assert pendiente["tipo"] == "PagoRecibido"
    assert pendiente["mensaje"] == "Se recibió un pago"
    assert pendiente["leida"] is False
    assert pendiente["comprador_id"] is None
    assert pendiente["comprador_nombre"] is None
    assert pendiente["fecha"] is not None

    # 3. Marcar una notificación individual como leída
    r = client.put(
        f"/notificaciones/{id_pendiente}/leer",
        headers=h_prod,
    )

    assert r.status_code == 200
    assert _dato(r)["leida"] is True

    # 4. Intentar marcar una notificación inexistente
    r = client.put(
        "/notificaciones/999999/leer",
        headers=h_prod,
    )

    assert r.status_code == 404

    # 5. El comprador no puede modificar la notificación del productor
    r = client.put(
        f"/notificaciones/{id_pendiente}/leer",
        headers=h_comp,
    )

    assert r.status_code == 403

    # 6. Marcar todas las notificaciones del productor como leídas
    r = client.put(
        "/notificaciones/leer-todas",
        headers=h_prod,
    )

    assert r.status_code == 200

    # 7. Verificar que no quedan notificaciones sin leer
    r = client.get(
        "/notificaciones",
        headers=h_prod,
    )

    assert r.status_code == 200
    data = _dato(r)
    assert data["no_leidas"] == 0

    # 8. Verificar que las notificaciones del comprador siguen independientes
    r = client.get(
        "/notificaciones",
        headers=h_comp,
    )

    assert r.status_code == 200

    data = _dato(r)
    assert data["no_leidas"] >= 1

    # 9. Ejecutar nuevamente la operación sin notificaciones pendientes
    r = client.put(
        "/notificaciones/leer-todas",
        headers=h_prod,
    )

    assert r.status_code == 200

#################################################################################################3



def test_entregas_cobertura_adicional(integracion_ctx):
    client = integracion_ctx["client"]
    session_factory = integracion_ctx["session_factory"]

    h_prod = integracion_ctx["h_prod"]
    h_comp = integracion_ctx["h_comp"]
    h_admin = integracion_ctx["h_admin"]

    # ---------------------------------------------------------
    # USUARIOS ADICIONALES
    # ---------------------------------------------------------

    r = _registrar(
        client, 50, "Otro Productor", "otroprod@test.com",
        "Clave1234!", 1
    )
    assert r.status_code in (200, 201), r.text

    r = _login(client, "otroprod@test.com", "Clave1234!")
    assert r.status_code == 200, r.text

    h_otro_prod = {
        "Authorization": f"Bearer {_dato(r)['token']}"
    }

    r = _registrar(
        client, 51, "Otra Compradora", "otracomp@test.com",
        "Clave1234!", 2
    )
    assert r.status_code in (200, 201), r.text

    r = _login(client, "otracomp@test.com", "Clave1234!")
    assert r.status_code == 200, r.text

    h_otra_comp = {
        "Authorization": f"Bearer {_dato(r)['token']}"
    }

    # ---------------------------------------------------------
    # FUNCIÓN AUXILIAR PARA CREAR LOTES Y RESERVAS
    # ---------------------------------------------------------

    def crear_reserva(numero_lote, producto, pagar=True):
        r = client.post(
            "/lotes",
            json={
                "id": numero_lote,
                "producto": producto,
                "cantidad": 100,
                "categoria": "Hortaliza",
                "productor_id": 1,
                "precio_kg": 2000
            },
            headers=h_prod
        )
        assert r.status_code in (200, 201), r.text

        # Obtener el ID real devuelto por la API.
        lote_creado = _dato(r)
        lote_id_real = lote_creado["id"]

        r = client.post(
            "/reservas",
            json={
                "comprador_id": 2,
                "lote_id": lote_id_real,
                "cantidad": 5
            },
            headers=h_comp
        )
        assert r.status_code in (200, 201), r.text

        reserva = _dato(r)

        if pagar:
            db = session_factory()
            try:
                reserva_db = (
                    db.query(models.Reserva)
                    .filter(models.Reserva.id == reserva["id"])
                    .first()
                )

                assert reserva_db is not None
                reserva_db.estado = "Pagada"
                db.commit()
            finally:
                db.close()

        return reserva["id"]

    reserva1 = crear_reserva(90, "Tomate Entregas 1")
    reserva2 = crear_reserva(91, "Tomate Entregas 2")
    reserva3 = crear_reserva(92, "Tomate Entregas 3")
    reserva_pendiente = crear_reserva(
        93, "Tomate Entregas Pendiente", pagar=False
    )

    # ---------------------------------------------------------
    # CREAR ENTREGA
    # ---------------------------------------------------------

    # Reserva inexistente.
    r = client.post(
        "/entregas",
        json={
            "reserva_id": 99999,
            "medio": "Transporte terrestre"
        },
        headers=h_prod
    )
    assert r.status_code == 404, r.text

    # Productor que no es propietario.
    r = client.post(
        "/entregas",
        json={
            "reserva_id": reserva1,
            "medio": "Transporte terrestre"
        },
        headers=h_otro_prod
    )
    assert r.status_code == 403, r.text

    # Reserva no pagada.
    r = client.post(
        "/entregas",
        json={
            "reserva_id": reserva_pendiente,
            "medio": "Camión"
        },
        headers=h_prod
    )
    assert r.status_code in (400, 409), r.text

    # Crear entrega correctamente.
    r = client.post(
        "/entregas",
        json={
            "reserva_id": reserva1,
            "medio": "Transporte terrestre",
            "fecha_estimada": "2026-12-01"
        },
        headers=h_prod
    )
    assert r.status_code in (200, 201), r.text

    entrega1 = _dato(r)
    id_entrega1 = entrega1["id"]
    codigo = entrega1["codigo_confirmacion"]

    assert codigo is not None

    # Intentar duplicar la entrega.
    r = client.post(
        "/entregas",
        json={
            "reserva_id": reserva1,
            "medio": "Motocicleta"
        },
        headers=h_prod
    )
    assert r.status_code in (400, 409), r.text

    # Validación: reserva_id positivo.
    r = client.post(
        "/entregas",
        json={
            "reserva_id": -1,
            "medio": "Camión"
        },
        headers=h_prod
    )
    assert r.status_code == 422, r.text

    # Validación: medio no vacío.
    r = client.post(
        "/entregas",
        json={
            "reserva_id": reserva1,
            "medio": "   "
        },
        headers=h_prod
    )
    assert r.status_code == 422, r.text

    # ---------------------------------------------------------
    # CONSULTAR ENTREGAS
    # ---------------------------------------------------------

    # Comprador propietario: puede ver el código.
    r = client.get(
        "/entregas",
        params={"reserva_id": reserva1},
        headers=h_comp
    )
    assert r.status_code == 200, r.text

    entregas = _dato(r)
    assert len(entregas) >= 1
    assert "codigo_confirmacion" in entregas[0]

    # Productor propietario: no puede ver el código.
    r = client.get(
        "/entregas",
        params={"reserva_id": reserva1},
        headers=h_prod
    )
    assert r.status_code == 200, r.text

    entregas_prod = _dato(r)
    assert len(entregas_prod) >= 1
    assert "codigo_confirmacion" not in entregas_prod[0]

    # Administrador: puede ver el código.
    r = client.get(
        "/entregas",
        params={"reserva_id": reserva1},
        headers=h_admin
    )
    assert r.status_code == 200, r.text
    assert "codigo_confirmacion" in _dato(r)[0]

    # Reserva inexistente.
    r = client.get(
        "/entregas",
        params={"reserva_id": 99999},
        headers=h_admin
    )
    assert r.status_code == 404, r.text

    # Comprador ajeno a la reserva.
    r = client.get(
        "/entregas",
        params={"reserva_id": reserva1},
        headers=h_otra_comp
    )
    assert r.status_code == 403, r.text

    # ---------------------------------------------------------
    # ACTUALIZAR ENTREGA
    # ---------------------------------------------------------

    # Entrega inexistente.
    r = client.put(
        "/entregas/99999",
        json={"estado": "Entregada"},
        headers=h_admin
    )
    assert r.status_code == 404, r.text

    # Comprador que no es propietario.
    r = client.put(
        f"/entregas/{id_entrega1}",
        json={"codigo_confirmacion": codigo},
        headers=h_otra_comp
    )
    assert r.status_code == 403, r.text

    # Código incorrecto.
    r = client.put(
        f"/entregas/{id_entrega1}",
        json={"codigo_confirmacion": "000000"},
        headers=h_comp
    )
    assert r.status_code in (400, 403), r.text

    # Código correcto.
    r = client.put(
        f"/entregas/{id_entrega1}",
        json={"codigo_confirmacion": codigo},
        headers=h_comp
    )
    assert r.status_code == 200, r.text
    assert _dato(r)["estado"] == "Entregada"

    # Estado inválido.
    r = client.put(
        f"/entregas/{id_entrega1}",
        json={"estado": "En camino"},
        headers=h_admin
    )
    assert r.status_code == 422, r.text

    # ---------------------------------------------------------
    # ACTUALIZAR UBICACIÓN
    # ---------------------------------------------------------

    r = client.post(
        "/entregas",
        json={
            "reserva_id": reserva2,
            "medio": "Camión"
        },
        headers=h_prod
    )
    assert r.status_code in (200, 201), r.text

    entrega2 = _dato(r)
    id_entrega2 = entrega2["id"]

    ubicacion = {
        "latitud": 4.6097,
        "longitud": -74.0817
    }

    # Productor ajeno.
    r = client.put(
        f"/entregas/{id_entrega2}/ubicacion",
        json=ubicacion,
        headers=h_otro_prod
    )
    assert r.status_code == 403, r.text

    # Productor propietario.
    r = client.put(
        f"/entregas/{id_entrega2}/ubicacion",
        json=ubicacion,
        headers=h_prod
    )
    assert r.status_code == 200, r.text

    # Entrega inexistente.
    r = client.put(
        "/entregas/99999/ubicacion",
        json=ubicacion,
        headers=h_admin
    )
    assert r.status_code == 404, r.text

    # Latitud fuera de rango.
    r = client.put(
        f"/entregas/{id_entrega2}/ubicacion",
        json={"latitud": 100, "longitud": -74},
        headers=h_prod
    )
    assert r.status_code == 422, r.text

    # Longitud fuera de rango.
    r = client.put(
        f"/entregas/{id_entrega2}/ubicacion",
        json={"latitud": 4, "longitud": 200},
        headers=h_prod
    )
    assert r.status_code == 422, r.text

    # ---------------------------------------------------------
    # ESTADOS Y PERMISOS
    # ---------------------------------------------------------

    # Productor actualiza el estado.
    r = client.put(
        f"/entregas/{id_entrega2}",
        json={"estado": "Pendiente"},
        headers=h_prod
    )
    assert r.status_code == 200, r.text

    # No se permite actualizar ubicación si no está en tránsito.
    r = client.put(
        f"/entregas/{id_entrega2}/ubicacion",
        json=ubicacion,
        headers=h_prod
    )
    assert r.status_code == 409, r.text

    # Administrador crea otra entrega.
    r = client.post(
        "/entregas",
        json={
            "reserva_id": reserva3,
            "medio": "Transporte administrado"
        },
        headers=h_admin
    )
    assert r.status_code in (200, 201), r.text

    entrega3 = _dato(r)
    id_entrega3 = entrega3["id"]
    codigo3 = entrega3["codigo_confirmacion"]

    # Administrador actualiza ubicación.
    r = client.put(
        f"/entregas/{id_entrega3}/ubicacion",
        json=ubicacion,
        headers=h_admin
    )
    assert r.status_code == 200, r.text

    # Administrador cambia estado y confirma recepción.
    r = client.put(
        f"/entregas/{id_entrega3}",
        json={
            "estado": "Entregada",
            "codigo_confirmacion": codigo3
        },
        headers=h_admin
    )
    assert r.status_code == 200, r.text
    assert _dato(r)["estado"] == "Entregada"

#########################################################################################3


def test_reportes_cobertura_adicional(integracion_ctx):
    client = integracion_ctx["client"]
    h_prod = integracion_ctx["h_prod"]
    h_comp = integracion_ctx["h_comp"]
    h_admin = integracion_ctx["h_admin"]

    # ---------------------------------------------------------
    # 1. REPORTE DEL PRODUCTOR CON FILTROS DE FECHAS
    # ---------------------------------------------------------
    r = client.get(
        "/reportes/productor",
        params={
            "fecha_desde": "2000-01-01",
            "fecha_hasta": "2100-12-31",
        },
        headers=h_prod,
    )

    assert r.status_code == 200, r.text
    data = _dato(r)

    assert data["productor_id"] == 1
    assert data["rango"]["desde"] == "2000-01-01"
    assert data["rango"]["hasta"] == "2100-12-31"
    assert "total_kg_vendidos" in data
    assert "ingresos_totales" in data
    assert "comision_total" in data
    assert "ingresos_netos" in data
    assert "lotes_activos" in data
    assert "reservas_entregadas" in data
    assert "calificacion" in data

    # ---------------------------------------------------------
    # 2. ADMINISTRADOR CONSULTA OTRO PRODUCTOR
    # ---------------------------------------------------------
    r = client.get(
        "/reportes/productor",
        params={"productor_id": 50},
        headers=h_admin,
    )

    assert r.status_code == 200, r.text
    assert _dato(r)["productor_id"] == 50

    # ---------------------------------------------------------
    # 3. REPORTE DEL COMPRADOR AUTENTICADO
    # ---------------------------------------------------------
    r = client.get(
        "/reportes/comprador",
        headers=h_comp,
    )

    assert r.status_code == 200, r.text
    data = _dato(r)

    assert data["comprador_id"] == 2
    assert "total_reservas" in data
    assert "total_gastado" in data
    assert "historial" in data
    assert isinstance(data["historial"], list)

    # ---------------------------------------------------------
    # 4. ADMINISTRADOR CONSULTA OTRO COMPRADOR
    # ---------------------------------------------------------
    r = client.get(
        "/reportes/comprador",
        params={"comprador_id": 51},
        headers=h_admin,
    )

    assert r.status_code == 200, r.text
    data = _dato(r)

    assert data["comprador_id"] == 51
    assert data["total_reservas"] == 0
    assert data["total_gastado"] == 0
    assert data["historial"] == []

    # ---------------------------------------------------------
    # 5. REPORTE FINANCIERO CON FILTROS DE FECHAS
    # ---------------------------------------------------------
    r = client.get(
        "/reportes/admin",
        params={
            "fecha_desde": "2000-01-01",
            "fecha_hasta": "2100-12-31",
        },
        headers=h_admin,
    )

    assert r.status_code == 200, r.text
    data = _dato(r)

    assert data["rango"]["desde"] == "2000-01-01"
    assert data["rango"]["hasta"] == "2100-12-31"
    assert "volumen_transacciones" in data
    assert "monto_total_transacciones" in data
    assert "comision_total_plataforma" in data
    assert "disputas_por_estado" in data
    assert "total_disputas" in data
    assert "usuarios_activos_por_rol" in data
    assert "total_usuarios_activos" in data

    # ---------------------------------------------------------
    # 6. VALIDAR PERMISOS DE LOS REPORTES
    # ---------------------------------------------------------

    # Comprador no puede consultar reporte de productor.
    r = client.get(
        "/reportes/productor",
        headers=h_comp,
    )
    assert r.status_code == 403, r.text

    # Productor no puede consultar reporte de comprador.
    r = client.get(
        "/reportes/comprador",
        headers=h_prod,
    )
    assert r.status_code == 403, r.text

    # Comprador no puede consultar reporte administrativo.
    r = client.get(
        "/reportes/admin",
        headers=h_comp,
    )
    assert r.status_code == 403, r.text

    # Productor tampoco puede consultar reporte administrativo.
    r = client.get(
        "/reportes/admin",
        headers=h_prod,
    )
    assert r.status_code == 403, r.text

    # Sin autenticación no se permite consultar reportes.
    assert client.get("/reportes/productor").status_code == 401
    assert client.get("/reportes/comprador").status_code == 401
    assert client.get("/reportes/admin").status_code == 401

###########################################################################################3


def test_reservas_validaciones_esquemas(integracion_ctx):
    from Esquemas.Esquemas import ReservaCrear, ReservaEditar
    from pydantic import ValidationError
    from datetime import date

    # ReservaCrear: IDs positivos
    with pytest.raises(ValidationError):
        ReservaCrear(comprador_id=0, lote_id=1, cantidad=5)

    with pytest.raises(ValidationError):
        ReservaCrear(comprador_id=2, lote_id=0, cantidad=5)

    with pytest.raises(ValidationError):
        ReservaCrear(comprador_id=-1, lote_id=1, cantidad=5)

    # ReservaCrear: cantidad mínima
    with pytest.raises(ValidationError):
        ReservaCrear(comprador_id=2, lote_id=1, cantidad=0)

    with pytest.raises(ValidationError):
        ReservaCrear(comprador_id=2, lote_id=1, cantidad=-5)

    # ReservaCrear: datos válidos
    reserva = ReservaCrear(
        comprador_id=2,
        lote_id=1,
        cantidad=10,
    )
    assert reserva.cantidad == 10

    # ReservaEditar: comprador positivo
    with pytest.raises(ValidationError):
        ReservaEditar(comprador_id=0)

    with pytest.raises(ValidationError):
        ReservaEditar(comprador_id=-2)

    # ReservaEditar: estado inválido
    with pytest.raises(ValidationError):
        ReservaEditar(estado="En preparación")

    # ReservaEditar: estados válidos
    for estado in [
        "Pendiente",
        "Confirmada",
        "Pagada",
        "En tránsito",
        "Entregada",
        "Calificada",
        "Cancelada",
    ]:
        datos = ReservaEditar(estado=estado)
        assert datos.estado == estado

    # ReservaEditar: campos opcionales
    datos = ReservaEditar()
    assert datos.comprador_id is None
    assert datos.fecha is None
    assert datos.estado is None
    assert datos.motivo_cancelacion is None

    # ReservaEditar: fecha válida
    datos = ReservaEditar(fecha=date(2026, 11, 22))
    assert datos.fecha == date(2026, 11, 22)

##########################################################################


def test_usuarios_consultas_y_perfiles_cobertura(integracion_ctx):
    client = integracion_ctx["client"]
    session_factory = integracion_ctx["session_factory"]

    # Obtener IDs disponibles para evitar duplicados
    db = session_factory()
    try:
        ultimo_id = (
            db.query(_func.max(models.Usuario.id)).scalar() or 0
        )
        id_prod = ultimo_id + 10
        id_comp = ultimo_id + 11
        id_admin = ultimo_id + 12
    finally:
        db.close()

    # Registrar productor
    r = _registrar(
        client, id_prod, "Productor Cobertura",
        f"productor{id_prod}@test.com", "Clave1234!", 1
    )
    assert r.status_code in (200, 201), r.text

    # Registrar comprador
    r = _registrar(
        client, id_comp, "Comprador Cobertura",
        f"comprador{id_comp}@test.com", "Clave1234!", 2
    )
    assert r.status_code in (200, 201), r.text

    # Registrar administrador
    r = _registrar(
        client, id_admin, "Administrador Cobertura",
        f"admin{id_admin}@test.com", "Clave1234!", 3
    )
    assert r.status_code in (200, 201), r.text

    # Obtener tokens
    r = _login(
        client, f"productor{id_prod}@test.com", "Clave1234!"
    )
    assert r.status_code == 200, r.text
    h_prod = {"Authorization": f"Bearer {_dato(r)['token']}"}

    r = _login(
        client, f"comprador{id_comp}@test.com", "Clave1234!"
    )
    assert r.status_code == 200, r.text
    h_comp = {"Authorization": f"Bearer {_dato(r)['token']}"}

    r = _login(
        client, f"admin{id_admin}@test.com", "Clave1234!"
    )
    assert r.status_code == 200, r.text
    h_admin = {"Authorization": f"Bearer {_dato(r)['token']}"}

    # 1. Consultar mi perfil como productor
    r = client.get("/usuarios/me", headers=h_prod)
    assert r.status_code == 200, r.text
    perfil = _dato(r)
    assert perfil["id"] == id_prod
    assert "correo" in perfil
    assert "rol" in perfil

    # 2. Consultar mi perfil como comprador
    r = client.get("/usuarios/me", headers=h_comp)
    assert r.status_code == 200, r.text
    assert _dato(r)["id"] == id_comp

    # 3. Consultar perfil sin autenticación
    r = client.get("/usuarios/me")
    assert r.status_code == 401, r.text

    # 4. Consultar resumen público
    r = client.get("/usuarios/resumen-publico")
    assert r.status_code == 200, r.text
    assert isinstance(_dato(r), dict)

    # 5. Listar usuarios como administrador
    r = client.get("/usuarios", headers=h_admin)
    assert r.status_code == 200, r.text
    usuarios = _dato(r)
    assert isinstance(usuarios, list)
    assert any(u["id"] == id_prod for u in usuarios)

    # 6. Filtrar usuarios por rol
    r = client.get(
        "/usuarios",
        params={"rol_id": 1},
        headers=h_admin
    )
    assert r.status_code == 200, r.text
    assert all(u["rol_id"] == 1 for u in _dato(r))

    # 7. Filtrar usuarios por estado
    r = client.get(
        "/usuarios",
        params={"estado": "Activo"},
        headers=h_admin
    )
    assert r.status_code == 200, r.text

    # 8. Listar compradores
    r = client.get("/usuarios/compradores", headers=h_admin)
    assert r.status_code == 200, r.text
    compradores = _dato(r)
    assert isinstance(compradores, list)
    assert all(u["rol_id"] == 2 for u in compradores)

    # 9. Filtrar compradores por estado
    r = client.get(
        "/usuarios/compradores",
        params={"estado": "Activo"},
        headers=h_admin
    )
    assert r.status_code == 200, r.text

    # 10. Consultar compradores sin permisos
    r = client.get("/usuarios/compradores", headers=h_comp)
    assert r.status_code == 403, r.text

    # 11. Listar productores públicamente
    r = client.get("/usuarios/productores")
    assert r.status_code == 200, r.text
    productores = _dato(r)
    assert isinstance(productores, list)

    productor = next(
        (u for u in productores if u["id"] == id_prod),
        None
    )
    assert productor is not None
    assert "correo" not in productor
    assert "telefono" not in productor

    # 12. Filtrar productores por estado
    r = client.get(
        "/usuarios/productores",
        params={"estado": "Activo"}
    )
    assert r.status_code == 200, r.text

    # 13. Buscar usuario por nombre
    r = client.get(
        "/usuarios/Productor",
        headers=h_admin
    )
    assert r.status_code == 200, r.text
    encontrados = _dato(r)
    assert isinstance(encontrados, list)
    assert any(u["id"] == id_prod for u in encontrados)

    # 14. Buscar usuario ignorando mayúsculas
    r = client.get(
        "/usuarios/productor",
        headers=h_admin
    )
    assert r.status_code == 200, r.text

    # 15. Buscar usuario con nombre vacío
    r = client.get(
        "/usuarios/%20%20%20",
        headers=h_admin
    )
    assert r.status_code == 400, r.text

    # 16. Buscar un usuario inexistente
    r = client.get(
        "/usuarios/NombreQueNoExisteXYZ",
        headers=h_admin
    )
    assert r.status_code == 404, r.text

    # 17. Buscar usuario sin autenticación
    r = client.get("/usuarios/Productor")
    assert r.status_code == 401, r.text

    # 18. Consultar perfil público del productor
    r = client.get(f"/usuarios/{id_prod}/perfil-publico")
    assert r.status_code == 200, r.text
    perfil_publico = _dato(r)
    assert perfil_publico["id"] == id_prod

    # 19. Consultar perfil público de un comprador
    r = client.get(f"/usuarios/{id_comp}/perfil-publico")
    assert r.status_code == 404, r.text

    # 20. Consultar perfil público de un usuario inexistente
    r = client.get("/usuarios/999999/perfil-publico")
    assert r.status_code == 404, r.text

    # 21. Intentar listar usuarios sin autenticación
    r = client.get("/usuarios")
    assert r.status_code == 401, r.text

    # 22. Intentar listar usuarios como comprador
    r = client.get("/usuarios", headers=h_comp)
    assert r.status_code == 403, r.text

#########################################################################################3


def test_disputas_cobertura_adicional(integracion_ctx):
    client = integracion_ctx["client"]

    # ---------------------------------------------------------
    # 1. REGISTRAR USUARIOS Y OBTENER TOKENS
    # ---------------------------------------------------------

    usuarios = [
        (53, "Productor Disputas", "prod_disputas@test.com", 1),
        (54, "Comprador Disputas", "comp_disputas@test.com", 2),
        (55, "Admin Disputas", "admin_disputas@test.com", 3),
        (56, "Segundo Comprador", "comp2_disputas@test.com", 2),
    ]

    encabezados = {}

    for uid, nombre, correo, rol_id in usuarios:
        r = _registrar(
            client,
            uid,
            nombre,
            correo,
            "Clave1234!",
            rol_id,
        )
        assert r.status_code in (200, 201), r.text

        r = _login(client, correo, "Clave1234!")
        assert r.status_code == 200, r.text

        token = _dato(r)["token"]
        encabezados[uid] = {
            "Authorization": f"Bearer {token}"
        }

    h_prod = encabezados[53]
    h_comp = encabezados[54]
    h_admin = encabezados[55]
    h_otro_comp = encabezados[56]

    # ---------------------------------------------------------
    # 2. CREAR LOTE
    # ---------------------------------------------------------

    r = client.post(
        "/lotes",
        json={
            "producto": "Tomate para disputas",
            "cantidad": 100,
            "categoria": "Hortaliza",
            "productor_id": 53,
            "precio_kg": 2000,
        },
        headers=h_prod,
    )
    assert r.status_code in (200, 201), r.text

    lote_id = _dato(r)["id"]

    # ---------------------------------------------------------
    # 3. CREAR RESERVA DEL PRIMER COMPRADOR
    # ---------------------------------------------------------

    r = client.post(
        "/reservas",
        json={
            "comprador_id": 54,
            "lote_id": lote_id,
            "cantidad": 10,
        },
        headers=h_comp,
    )
    assert r.status_code in (200, 201), r.text

    reserva_comp_id = _dato(r)["id"]

    # ---------------------------------------------------------
    # 4. CREAR RESERVA DEL SEGUNDO COMPRADOR
    # ---------------------------------------------------------

    r = client.post(
        "/reservas",
        json={
            "comprador_id": 56,
            "lote_id": lote_id,
            "cantidad": 10,
        },
        headers=h_otro_comp,
    )
    assert r.status_code in (200, 201), r.text

    reserva_otro_id = _dato(r)["id"]

    # ---------------------------------------------------------
    # 5. CREAR DISPUTA
    # ---------------------------------------------------------

    r = client.post(
        "/disputas",
        json={
            "reserva_id": reserva_comp_id,
            "descripcion": "El producto llegó incompleto",
        },
        headers=h_comp,
    )
    assert r.status_code in (200, 201), r.text

    disputa = _dato(r)
    disputa_id = disputa["id"]

    assert disputa["reserva_id"] == reserva_comp_id
    assert disputa["comprador_id"] == 54
    assert disputa["estado"] == "Abierta"

    # ---------------------------------------------------------
    # 6. INTENTAR CREAR DISPUTA DUPLICADA
    # ---------------------------------------------------------

    r = client.post(
        "/disputas",
        json={
            "reserva_id": reserva_comp_id,
            "descripcion": "Intento de disputa duplicada",
        },
        headers=h_comp,
    )
    assert r.status_code in (400, 409), r.text

    # ---------------------------------------------------------
    # 7. INTENTAR CREAR DISPUTA SOBRE RESERVA AJENA
    # ---------------------------------------------------------

    r = client.post(
        "/disputas",
        json={
            "reserva_id": reserva_otro_id,
            "descripcion": "Intento sobre reserva ajena",
        },
        headers=h_comp,
    )
    assert r.status_code == 403, r.text

    # ---------------------------------------------------------
    # 8. INTENTAR CREAR DISPUTA CON RESERVA INEXISTENTE
    # ---------------------------------------------------------

    r = client.post(
        "/disputas",
        json={
            "reserva_id": 99999,
            "descripcion": "Reserva inexistente",
        },
        headers=h_comp,
    )
    assert r.status_code == 404, r.text

    # ---------------------------------------------------------
    # 9. CONSULTAR DISPUTAS COMO COMPRADOR
    # ---------------------------------------------------------

    r = client.get(
        "/disputas",
        headers=h_comp,
    )
    assert r.status_code == 200, r.text

    disputas_comp = _dato(r)

    assert any(d["id"] == disputa_id for d in disputas_comp)
    assert all(d["comprador_id"] == 54 for d in disputas_comp)

    # ---------------------------------------------------------
    # 10. CONSULTAR DISPUTAS FILTRADAS POR ESTADO
    # ---------------------------------------------------------

    r = client.get(
        "/disputas",
        params={"estado": "Abierta"},
        headers=h_admin,
    )
    assert r.status_code == 200, r.text

    disputas_abiertas = _dato(r)

    assert all(
        d["estado"] == "Abierta"
        for d in disputas_abiertas
    )

    # ---------------------------------------------------------
    # 11. SEGUNDO COMPRADOR NO DEBE VER DISPUTAS AJENAS
    # ---------------------------------------------------------

    r = client.get(
        "/disputas",
        headers=h_otro_comp,
    )
    assert r.status_code == 200, r.text

    disputas_otro = _dato(r)

    assert all(d["comprador_id"] == 56 for d in disputas_otro)
    assert not any(d["id"] == disputa_id for d in disputas_otro)

    # ---------------------------------------------------------
    # 12. ROL NO AUTORIZADO
    # ---------------------------------------------------------

    r = client.get(
        "/disputas",
        headers=h_prod,
    )
    assert r.status_code == 403, r.text

    # ---------------------------------------------------------
    # 13. ACTUALIZAR DISPUTA INEXISTENTE
    # ---------------------------------------------------------

    r = client.put(
        "/disputas/99999",
        json={
            "estado": "Resuelta",
            "resolucion": "Prueba de disputa inexistente",
            "reembolsar": False,
        },
        headers=h_admin,
    )
    assert r.status_code == 404, r.text

    # ---------------------------------------------------------
    # 14. ACTUALIZAR DISPUTA
    # ---------------------------------------------------------

    r = client.put(
        f"/disputas/{disputa_id}",
        json={
            "estado": "Resuelta",
            "resolucion": "Se verificó el inconveniente",
            "reembolsar": False,
        },
        headers=h_admin,
    )
    assert r.status_code == 200, r.text

    disputa_actualizada = _dato(r)

    assert disputa_actualizada["estado"] == "Resuelta"
    assert disputa_actualizada["resolucion"] == "Se verificó el inconveniente"
    assert disputa_actualizada["fecha_resolucion"] is not None

    # ---------------------------------------------------------
    # 15. CONSULTAR DISPUTAS RESUELTAS
    # ---------------------------------------------------------

    r = client.get(
        "/disputas",
        params={"estado": "Resuelta"},
        headers=h_admin,
    )
    assert r.status_code == 200, r.text

    disputas_resueltas = _dato(r)

    assert any(
        d["id"] == disputa_id
        for d in disputas_resueltas
    )

########################################################################################


def test_favoritos_cobertura_adicional(integracion_ctx):
    client = integracion_ctx["client"]

    # Registrar un productor y dos compradores.
    r = _registrar(
        client, 57, "Productor Favoritos",
        "productor_fav@test.com", "Clave1234!", 1
    )
    assert r.status_code in (200, 201), r.text

    r = _registrar(
        client, 58, "Comprador Favoritos",
        "comprador_fav@test.com", "Clave1234!", 2
    )
    assert r.status_code in (200, 201), r.text

    r = _registrar(
        client, 59, "Segundo Comprador",
        "comprador2_fav@test.com", "Clave1234!", 2
    )
    assert r.status_code in (200, 201), r.text

    # Iniciar sesión con el primer comprador.
    r = _login(client, "comprador_fav@test.com", "Clave1234!")
    assert r.status_code == 200, r.text
    token = _dato(r)["token"]
    h_comp = {"Authorization": f"Bearer {token}"}

    # Iniciar sesión con el segundo comprador.
    r = _login(client, "comprador2_fav@test.com", "Clave1234!")
    assert r.status_code == 200, r.text
    token2 = _dato(r)["token"]
    h_comp2 = {"Authorization": f"Bearer {token2}"}

    # 1. Consultar favoritos cuando la lista está vacía.
    r = client.get(
        "/favoritos",
        params={"comprador_id": 58},
        headers=h_comp
    )
    assert r.status_code == 200, r.text
    assert _dato(r) == []

    # 2. Intentar consultar favoritos de otro comprador.
    r = client.get(
        "/favoritos",
        params={"comprador_id": 59},
        headers=h_comp
    )
    assert r.status_code == 403, r.text

    # 3. Intentar agregar un favorito con un ID negativo.
    r = client.post(
        "/favoritos",
        json={
            "comprador_id": 58,
            "productor_id": 0
        },
        headers=h_comp
    )
    assert r.status_code == 422, r.text

    # 4. Intentar agregar un productor inexistente.
    r = client.post(
        "/favoritos",
        json={
            "comprador_id": 58,
            "productor_id": 9999
        },
        headers=h_comp
    )
    assert r.status_code == 404, r.text

    # 5. Agregar un productor correctamente.
    r = client.post(
        "/favoritos",
        json={
            "comprador_id": 58,
            "productor_id": 57
        },
        headers=h_comp
    )
    assert r.status_code == 201, r.text

    favorito = _dato(r)
    assert favorito["comprador_id"] == 58
    assert favorito["productor_id"] == 57
    assert favorito["productor"] == "Productor Favoritos"

    # 6. Intentar agregar el mismo productor nuevamente.
    r = client.post(
        "/favoritos",
        json={
            "comprador_id": 58,
            "productor_id": 57
        },
        headers=h_comp
    )
    assert r.status_code in (400, 409), r.text

    # 7. Consultar favoritos después de agregar el productor.
    r = client.get(
        "/favoritos",
        params={"comprador_id": 58},
        headers=h_comp
    )
    assert r.status_code == 200, r.text

    favoritos = _dato(r)
    assert len(favoritos) == 1
    assert favoritos[0]["comprador_id"] == 58
    assert favoritos[0]["productor_id"] == 57
    assert favoritos[0]["productor"] == "Productor Favoritos"
    assert "ciudad" in favoritos[0]
    assert "fecha_agregado" in favoritos[0]

    # 8. Intentar eliminar sin confirmar.
    r = client.delete(
        "/favoritos/58/57",
        headers=h_comp
    )
    assert r.status_code == 400, r.text

    # 9. Intentar eliminar un favorito inexistente.
    r = client.delete(
        "/favoritos/58/9999",
        params={"confirmar": True},
        headers=h_comp
    )
    assert r.status_code == 404, r.text

    # 10. Intentar eliminar favoritos de otro comprador.
    r = client.delete(
        "/favoritos/59/57",
        params={"confirmar": True},
        headers=h_comp
    )
    assert r.status_code == 403, r.text

    # 11. Eliminar correctamente el favorito.
    r = client.delete(
        "/favoritos/58/57",
        params={"confirmar": True},
        headers=h_comp
    )
    assert r.status_code == 200, r.text

    resultado = _dato(r)
    assert resultado["comprador_id"] == 58
    assert resultado["productor_id"] == 57

    # 12. Comprobar que ya no existen favoritos.
    r = client.get(
        "/favoritos",
        params={"comprador_id": 58},
        headers=h_comp
    )
    assert r.status_code == 200, r.text
    assert _dato(r) == []

    # 13. El segundo comprador tampoco tiene favoritos.
    r = client.get(
        "/favoritos",
        params={"comprador_id": 59},
        headers=h_comp2
    )
    assert r.status_code == 200, r.text
    assert _dato(r) == []

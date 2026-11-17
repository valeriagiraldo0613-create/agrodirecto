
import sys

from pathlib import Path
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

# Agregar la carpeta scr para que Python encuentre los módulos
RUTA_SCR = Path(__file__).resolve().parent.parent / "scr"
sys.path.insert(0, str(RUTA_SCR))

# Importaciones del proyecto
from Rutas.rutas_auth import router
from Controladores import controladores_auth
from Controladores import controladores_pagos
from Excepciones.excepciones_auth import ErrorCredencialesInvalidas
from Utilidades.respuesta import respuesta_error


# Crear una aplicación independiente para las pruebas
app = FastAPI()
app.include_router(router)


# Manejar errores de credenciales durante las pruebas
@app.exception_handler(ErrorCredencialesInvalidas)
def manejar_error_credenciales(request, exc):
    return respuesta_error(
        message="Credenciales inválidas",
        status_code=401
    )


# Usuario simulado para las pruebas
usuario_prueba = SimpleNamespace(
    id=1,
    nombre="Usuario de prueba",
    correo="prueba@agrodirecto.com",
    clave="clave_simulada",
    estado="Activo",
    rol_rel=SimpleNamespace(nombre="Comprador")
)


# Simular la consulta a la base de datos
class ConsultaSimulada:

    def query(self, modelo):
        return self

    def filter(self, condicion):
        return self

    def first(self):
        return usuario_prueba


# Proporcionar una sesión simulada
def obtener_db_simulada():
    yield ConsultaSimulada()


# Reemplazar la conexión real por la simulada
app.dependency_overrides[controladores_auth.get_db] = obtener_db_simulada

cliente = TestClient(app)


# TEST-01: Inicio de sesión exitoso
def test_login_exitoso(monkeypatch):

    monkeypatch.setattr(
        controladores_auth,
        "verificar_clave",
        lambda clave, hash_guardado: True
    )

    monkeypatch.setattr(
        controladores_auth,
        "crear_token",
        lambda datos: "token_de_prueba"
    )

    respuesta = cliente.post(
        "/auth/login",
        json={
            "correo": "prueba@agrodirecto.com",
            "clave": "clave123"
        }
    )

    assert respuesta.status_code == 200

    datos = respuesta.json()

    assert datos["success"] is True
    assert datos["data"]["token"] == "token_de_prueba"
    assert datos["data"]["usuario"]["correo"] == "prueba@agrodirecto.com"


# TEST-02: Inicio de sesión con credenciales incorrectas
def test_login_credenciales_incorrectas(monkeypatch):

    # Simular que la contraseña no coincide
    monkeypatch.setattr(
        controladores_auth,
        "verificar_clave",
        lambda clave, hash_guardado: False
    )

    # Comprobar que no se intente generar un token
    def token_no_debe_generarse(datos):
        raise AssertionError(
            "No debe generarse un token con credenciales incorrectas"
        )

    monkeypatch.setattr(
        controladores_auth,
        "crear_token",
        token_no_debe_generarse
    )

    respuesta = cliente.post(
        "/auth/login",
        json={
            "correo": "prueba@agrodirecto.com",
            "clave": "incorrecta"
        }
    )

    assert respuesta.status_code == 401

    datos = respuesta.json()

    assert datos["success"] is False
    assert datos["data"] is None

def test_calcular_totales_reserva():
    # Caso 1: el envío corresponde al 5% del subtotal.
    reserva = SimpleNamespace(
        lote=SimpleNamespace(precio_kg=10),
        cantidad=10
    )

    resultado = controladores_pagos._calcular_totales_reserva(reserva)

    assert resultado["subtotal"] == 100.0
    assert resultado["costo_envio"] == 5.0
    assert resultado["total"] == 105.0

    # Caso 2: se aplica el costo mínimo de envío ($3).
    reserva_minima = SimpleNamespace(
        lote=SimpleNamespace(precio_kg=2),
        cantidad=10
    )

    resultado_minimo = controladores_pagos._calcular_totales_reserva(
        reserva_minima
    )

    assert resultado_minimo["subtotal"] == 20.0
    assert resultado_minimo["costo_envio"] == 3.0
    assert resultado_minimo["total"] == 23.0
import pytest

from Utilidades.validacion_clave import (
    clave_es_segura,
    validar_clave_segura,
    MENSAJE_REGLAS_CLAVE,
)


@pytest.mark.parametrize(
    "clave",
    [
        "Prueba123!",
        "AgroDirecto2026!",
        "Clave#2026",
        "Segura123$",
    ],
)
def test_acepta_claves_seguras(clave):
    assert clave_es_segura(clave) is True


@pytest.mark.parametrize(
    "clave",
    [
        "",
        "abc",
        "prueba123!",
        "PRUEBA123",
        "PruebaClave!",
        "Prueba12",
        "12345678!",
    ],
)
def test_rechaza_claves_inseguras(clave):
    assert clave_es_segura(clave) is False


def test_rechaza_clave_menor_a_ocho_caracteres():
    assert clave_es_segura("Ab1!") is False


def test_rechaza_clave_sin_mayuscula():
    assert clave_es_segura("prueba123!") is False


def test_rechaza_clave_sin_numero():
    assert clave_es_segura("PruebaSegura!") is False


def test_rechaza_clave_sin_caracter_especial():
    assert clave_es_segura("Prueba123") is False


def test_validar_clave_segura_devuelve_la_misma_clave():
    clave = "AgroDirecto2026!"

    resultado = validar_clave_segura(clave)

    assert resultado == clave


def test_validar_clave_segura_lanza_error_si_es_invalida():
    with pytest.raises(ValueError) as error:
        validar_clave_segura("clave123")

    assert str(error.value) == MENSAJE_REGLAS_CLAVE
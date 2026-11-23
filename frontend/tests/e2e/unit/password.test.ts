import { describe, it, expect } from "vitest";

import {
  evaluarClave,
  claveEsValida,
  LONGITUD_MINIMA_CLAVE,
} from "../../../src/utils/password";

describe("Validación de contraseñas", () => {

  it("debe tener una longitud mínima de 8 caracteres", () => {
    expect(LONGITUD_MINIMA_CLAVE).toBe(8);
  });

  it("acepta una contraseña segura", () => {
    expect(claveEsValida("AgroDirecto2026!")).toBe(true);
  });

  it("rechaza una contraseña vacía", () => {
    expect(claveEsValida("")).toBe(false);
  });

  it("rechaza una contraseña corta", () => {
    expect(claveEsValida("Ab1!")).toBe(false);
  });

  it("rechaza una contraseña sin mayúscula", () => {
    expect(claveEsValida("prueba123!")).toBe(false);
  });

  it("rechaza una contraseña sin número", () => {
    expect(claveEsValida("PruebaSegura!")).toBe(false);
  });

  it("rechaza una contraseña sin carácter especial", () => {
    expect(claveEsValida("Prueba123")).toBe(false);
  });

  it("evalúa cada regla individualmente", () => {
    const resultado = evaluarClave("AgroDirecto2026!");

    expect(resultado.longitud).toBe(true);
    expect(resultado.mayus).toBe(true);
    expect(resultado.numero).toBe(true);
    expect(resultado.especial).toBe(true);
  });

});
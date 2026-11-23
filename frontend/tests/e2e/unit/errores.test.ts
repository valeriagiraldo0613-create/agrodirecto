import { describe, it, expect } from "vitest";

import { mensajeError } from "../../../src/utils/errores";

describe("Utilidad de mensajes de error", () => {

  it("devuelve el mensaje de un Error", () => {
    expect(
      mensajeError(new Error("Error de conexión"))
    ).toBe("Error de conexión");
  });

  it("devuelve el texto cuando recibe una cadena", () => {
    expect(
      mensajeError("Error de autenticación")
    ).toBe("Error de autenticación");
  });

  it("devuelve el mensaje predeterminado cuando recibe null", () => {
    expect(
      mensajeError(null)
    ).toBe("Ocurrió un error inesperado.");
  });

  it("permite definir un mensaje predeterminado personalizado", () => {
    expect(
      mensajeError(null, "Error personalizado")
    ).toBe("Error personalizado");
  });

});
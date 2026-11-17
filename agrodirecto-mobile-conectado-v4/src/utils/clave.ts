// Misma regla de contraseña segura que valida el backend
// (scr/Utilidades/validacion_clave.py): mínimo 8 caracteres,
// una mayúscula, un número y un carácter especial.

export const MENSAJE_REGLAS_CLAVE =
  'La contraseña debe tener al menos 8 caracteres, una mayúscula, un número y un carácter especial.';

export function claveEsSegura(clave: string): boolean {
  return (
    clave.length >= 8 &&
    /[A-Z]/.test(clave) &&
    /[0-9]/.test(clave) &&
    /[!@#$%^&*(),.?":{}|<>_\-+=/\\[\]~`;']/.test(clave)
  );
}

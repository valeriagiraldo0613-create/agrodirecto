// ============================================================
// api.ts — Conector React Native / TypeScript con FastAPI
//
// Este archivo es la ÚNICA frontera entre la app y el backend
// "AgroMercado API" (FastAPI). Las pantallas llaman a estas
// funciones y reciben objetos con los nombres de campo que ellas
// esperan; aquí se traducen:
//
//   · respuestas del backend  → forma que usan las pantallas (adaptar*)
//   · payloads de las pantallas → esquemas Pydantic del backend
//   · parámetros de filtro    → nombres reales de Query del backend
//
// Contrato de respuesta del backend (Utilidades/respuesta.py):
//   { success: boolean, message: string, data: any, error: string|null }
// ============================================================

import AsyncStorage from '@react-native-async-storage/async-storage';
import { getApiUrl } from './config';

export const TOKEN_KEY = '@agrodirecto_token';
export const USER_KEY = '@agrodirecto_user';

/** Tiempo máximo de espera por petición antes de abortar. */
const TIMEOUT_MS = 20000;

export interface Usuario {
  id: number;
  nombre: string;
  correo: string;
  rol: 'Administrador' | 'Productor' | 'Comprador' | string;
  telefono?: string;
  ciudad?: string;
  estado?: string;
  direccion?: string;
  empresa?: string;
  nombre_finca?: string;
  cultivos_principales?: string;
  descripcion?: string;
  latitud?: number;
  longitud?: number;
  tipo_documento?: string;
  numero_documento?: string;
}

export interface PeticionOpciones extends RequestInit {
  headers?: Record<string, string>;
}

// ============================================================
// SESIÓN EXPIRADA (HTTP 401)
// ============================================================
// El token JWT del backend dura 120 minutos y además se revoca en
// /auth/logout. Cuando el backend responde 401 con una sesión
// guardada, limpiamos el almacenamiento y avisamos a AuthContext
// para que devuelva al usuario a la pantalla de login.

let manejadorSesionExpirada: (() => void) | null = null;

export function registrarManejadorSesionExpirada(fn: (() => void) | null): void {
  manejadorSesionExpirada = fn;
}

// ============================================================
// UTILIDADES
// ============================================================

/** Arma "?a=1&b=2" ignorando valores null/undefined/'' (evita mandar "undefined"). */
function qs(filtros: Record<string, any> = {}): string {
  const p = new URLSearchParams();
  Object.entries(filtros).forEach(([k, v]) => {
    if (v !== undefined && v !== null && v !== '') p.append(k, String(v));
  });
  const s = p.toString();
  return s ? `?${s}` : '';
}

const num = (v: any): number => {
  const n = Number(v);
  return Number.isFinite(n) ? n : 0;
};

const entero = (v: any): number => Math.round(num(v));

/** Quita claves undefined/null para no pisar datos con vacíos. */
function limpiar<T extends Record<string, any>>(obj: T): Partial<T> {
  const out: Record<string, any> = {};
  Object.entries(obj).forEach(([k, v]) => {
    if (v !== undefined && v !== null) out[k] = v;
  });
  return out as Partial<T>;
}

/** Convierte el detalle de un 422 de FastAPI en un mensaje legible en español. */
function mensajeValidacion(detail: any): string | null {
  if (!Array.isArray(detail)) return typeof detail === 'string' ? detail : null;
  return detail
    .map((d: any) => {
      const campo = Array.isArray(d.loc) ? d.loc.filter((x: any) => x !== 'body').join('.') : '';
      const msg = String(d.msg || '').replace(/^Value error,\s*/i, '');
      return campo ? `${campo}: ${msg}` : msg;
    })
    .join(' · ');
}

// ============================================================
// FUNCIÓN BASE
// ============================================================

export async function peticion<T = any>(ruta: string, opciones: PeticionOpciones = {}): Promise<T> {
  const encabezados: Record<string, string> = {
    'Content-Type': 'application/json',
    ...(opciones.headers || {}),
  };

  let token: string | null = null;
  if (!encabezados['Authorization']) {
    try {
      token = await AsyncStorage.getItem(TOKEN_KEY);
    } catch {
      // Ignorar
    }
    if (token) {
      encabezados['Authorization'] = `Bearer ${token}`;
    }
  }

  const baseUrl = getApiUrl();
  let respuesta: Response;

  const controlador = new AbortController();
  const temporizador = setTimeout(() => controlador.abort(), TIMEOUT_MS);

  try {
    respuesta = await fetch(`${baseUrl}${ruta}`, {
      ...opciones,
      headers: encabezados,
      signal: controlador.signal,
    });
  } catch (error: any) {
    if (error?.name === 'AbortError') {
      throw new Error(`El servidor en ${baseUrl} tardó demasiado en responder. Intenta de nuevo.`);
    }
    throw new Error(
      `No se pudo conectar con el servidor en ${baseUrl}. ` +
      `Verifica que FastAPI esté ejecutándose (uvicorn main:app --host 0.0.0.0) y que tu dispositivo y PC compartan la misma red WiFi.`
    );
  } finally {
    clearTimeout(temporizador);
  }

  let cuerpo: any;
  try {
    cuerpo = await respuesta.json();
  } catch {
    throw new Error(
      `El backend respondió con un formato inválido (HTTP ${respuesta.status}).`
    );
  }

  // SESIÓN EXPIRADA / TOKEN REVOCADO
  if (respuesta.status === 401 && token && ruta !== '/auth/login') {
    try {
      await AsyncStorage.multiRemove([TOKEN_KEY, USER_KEY]);
    } catch {
      // Ignorar
    }
    if (manejadorSesionExpirada) manejadorSesionExpirada();
    const e: any = new Error('Tu sesión expiró. Inicia sesión nuevamente.');
    e.status = 401;
    throw e;
  }

  // PAGO RECHAZADO (HTTP 402)
  if (respuesta.status === 402 && cuerpo && cuerpo.error === 'PagoRechazado') {
    const errorPago: any = new Error(cuerpo.message || 'El pago fue rechazado.');
    errorPago.status = 402;
    errorPago.codigo = 'PagoRechazado';
    errorPago.data = cuerpo.data || null;
    throw errorPago;
  }

  // ERRORES GENERALES (incluye 422 de validación Pydantic: { detail: [...] })
  if (!respuesta.ok || !cuerpo.success) {
    const error: any = new Error(
      cuerpo.message ||
      mensajeValidacion(cuerpo.detail) ||
      cuerpo.error ||
      `Error HTTP ${respuesta.status}`
    );
    error.status = respuesta.status;
    error.codigo = cuerpo.error || null;
    error.data = cuerpo.data || null;
    throw error;
  }

  return cuerpo.data;
}

// ============================================================
// ADAPTADORES: backend → pantallas
// ============================================================

/** Lote del backend + alias que usan las pantallas. */
export function adaptarLote(l: any): any {
  if (!l) return l;
  const cantidad = num(l.cantidad);
  const reservados = num(l.kg_reservados);
  return {
    ...l,
    cultivo: l.producto,
    cantidad_total: cantidad,
    cantidad_disponible: Math.max(0, cantidad - reservados),
    precio_por_kilo: l.precio_kg,
    fecha_cosecha_estimada: l.fecha_cosecha,
    categoria_nombre: l.categoria,
    productor_nombre: l.productor,
    usuario_id: l.productor_id,
    ciudad: l.ciudad ?? l.productor_ciudad,
  };
}

/** Reserva del backend + alias (total calculado = precio_kg × cantidad). */
export function adaptarReserva(r: any): any {
  if (!r) return r;
  const total = num(r.precio_kg) * num(r.cantidad);
  return {
    ...r,
    cultivo: r.producto,
    cantidad_kg: r.cantidad,
    precio_por_kilo: r.precio_kg,
    precio_total: total,
    total,
    comprador_nombre: r.comprador,
    productor_nombre: r.productor,
    fecha_creacion: r.fecha,
    lote: {
      id: r.lote_id,
      cultivo: r.producto,
      producto: r.producto,
      productor_id: r.productor_id,
      usuario_id: r.productor_id,
      estado_cultivo: r.estado_cultivo,
      fecha_cosecha: r.fecha_cosecha,
    },
  };
}

function adaptarDisputa(d: any): any {
  if (!d) return d;
  return { ...d, fecha_creacion: d.fecha_apertura, motivo: d.motivo ?? null };
}

function adaptarTicket(t: any): any {
  if (!t) return t;
  return { ...t, email: t.correo, descripcion: t.mensaje, asunto: t.asunto ?? null };
}

function adaptarProveedor(p: any): any {
  if (!p) return p;
  return { ...p, servicio: p.tipo };
}

function adaptarFavorito(f: any): any {
  if (!f) return f;
  return { ...f, id: f.productor_id, nombre: f.productor, productor_nombre: f.productor };
}

function adaptarCalificacion(c: any): any {
  if (!c) return c;
  return { ...c, puntuacion: c.estrellas, comprador_nombre: c.comprador };
}

function adaptarEvento(e: any): any {
  if (!e) return e;
  return { ...e, titulo: e.accion, estado: e.estado ?? e.accion };
}

// ============================================================
// RESOLUCIÓN DE IDs (el backend exige `id` en usuarios/roles/proveedores)
// ============================================================

async function siguienteId(ruta: string): Promise<number> {
  const lista = await peticion<any[]>(ruta);
  const maximo = (Array.isArray(lista) ? lista : []).reduce(
    (m, x) => Math.max(m, num(x?.id)),
    0
  );
  return maximo + 1;
}

async function resolverRolId(rol?: string | number): Promise<number | undefined> {
  if (rol === undefined || rol === null || rol === '') return undefined;
  if (typeof rol === 'number') return rol;
  const roles = await peticion<any[]>('/roles');
  const encontrado = roles.find(
    (r) => String(r.nombre).toLowerCase() === String(rol).toLowerCase()
  );
  if (!encontrado) throw new Error(`El rol "${rol}" no existe en el sistema.`);
  return encontrado.id;
}

// ============================================================
// AUTENTICACIÓN
// ============================================================

export async function iniciarSesion(correo: string, clave: string): Promise<Usuario> {
  const datos = await peticion<{ token: string; usuario: Usuario }>('/auth/login', {
    method: 'POST',
    body: JSON.stringify({ correo, clave }),
  });

  await AsyncStorage.setItem(TOKEN_KEY, datos.token);
  await AsyncStorage.setItem(USER_KEY, JSON.stringify(datos.usuario));

  // /auth/login solo devuelve id, nombre, correo y rol; completamos el perfil
  // (teléfono, ciudad, finca, GPS...) con GET /usuarios/me (datos del usuario con sesión).
  try {
    const completo = await peticion<any>('/usuarios/me');
    if (completo) {
      const usuario: Usuario = { ...datos.usuario, ...completo, rol: datos.usuario.rol };
      await AsyncStorage.setItem(USER_KEY, JSON.stringify(usuario));
      return usuario;
    }
  } catch {
    // Si falla, nos quedamos con los datos básicos del login
  }

  return datos.usuario;
}

export async function solicitarRecuperacionClave(correo: string): Promise<any> {
  return peticion('/auth/recuperar-clave', {
    method: 'POST',
    body: JSON.stringify({ correo }),
  });
}

/** Cambio de clave propio: el backend exige la clave actual. */
export async function cambiarClave(claveActual: string, claveNueva: string): Promise<any> {
  return peticion('/auth/cambiar-clave', {
    method: 'POST',
    body: JSON.stringify({ clave_actual: claveActual, clave_nueva: claveNueva }),
  });
}

export async function restablecerClave(token: string, claveNueva: string): Promise<any> {
  return peticion('/auth/restablecer-clave', {
    method: 'POST',
    body: JSON.stringify({
      token,
      clave_nueva: claveNueva,
    }),
  });
}

export async function cerrarSesion(): Promise<void> {
  try {
    await peticion('/auth/logout', { method: 'POST' });
  } catch {
    // Ignorar si el backend ya cerró
  }
  await AsyncStorage.removeItem(TOKEN_KEY);
  await AsyncStorage.removeItem(USER_KEY);
}

// ============================================================
// USUARIOS
// ============================================================

/** Listado completo: solo Administrador. */
export async function obtenerUsuarios(filtros: Record<string, any> = {}): Promise<any[]> {
  return peticion(`/usuarios${qs(filtros)}`);
}

/** Conteos públicos (sin sesión) para el Home: { compradores, productores }. */
export async function obtenerResumenPublico(): Promise<{ compradores: number; productores: number }> {
  return peticion('/usuarios/resumen-publico');
}

/** Productores con datos públicos (sin correo/teléfono/documento). Sin sesión. */
export async function obtenerProductoresPublicos(filtros: Record<string, any> = {}): Promise<any[]> {
  return peticion(`/usuarios/productores${qs(filtros)}`);
}

/**
 * Registro de usuario. El backend (UsuarioCrear) exige: id, tipo_documento,
 * numero_documento, nombre, correo, telefono, clave y rol_id. La app trabaja
 * con `rol` (nombre) y el id se calcula aquí (MAX(id)+1).
 */
export async function registrarUsuario(usuario: any): Promise<any> {
  if (!usuario.numero_documento || !String(usuario.numero_documento).trim()) {
    throw new Error('El número de documento es obligatorio.');
  }
  if (!usuario.telefono || !String(usuario.telefono).trim()) {
    throw new Error('El teléfono es obligatorio.');
  }

  const rolId = usuario.rol_id ?? (await resolverRolId(usuario.rol));
  if (!rolId) throw new Error('Debes seleccionar un rol.');

  const crear = async (id: number) =>
    peticion('/usuarios', {
    method: 'POST',
    body: JSON.stringify(
      limpiar({
        id,
        tipo_documento: usuario.tipo_documento || 'CC',
        numero_documento: String(usuario.numero_documento).trim(),
        nombre: usuario.nombre,
        correo: usuario.correo,
        telefono: String(usuario.telefono).trim(),
        clave: usuario.clave,
        direccion: usuario.direccion,
        ciudad: usuario.ciudad,
        empresa: usuario.empresa,
        rol_id: rolId,
        estado: usuario.estado || 'Activo',
      })
    ),
  });

  // El backend exige `id` y ya no permite listar usuarios sin ser Administrador.
  // Admin: MAX(id)+1. Sin permiso (registro público): id aleatorio, reintentando si colisiona.
  let creado: any;
  let idBase: number | null = null;
  try {
    idBase = await siguienteId('/usuarios');
  } catch {
    idBase = null;
  }
  for (let intento = 0; ; intento++) {
    const id = idBase !== null ? idBase + intento : 100000000 + Math.floor(Math.random() * 1800000000);
    try {
      creado = await crear(id);
      break;
    } catch (e: any) {
      const colision = /id/i.test(String(e.message)) && /existe/i.test(String(e.message)) && !/correo|tel[eé]fono|documento/i.test(String(e.message));
      if (!colision || intento >= 4) throw e;
    }
  }

  // Datos de finca: el backend solo los acepta en PUT /usuarios/{id} y ese
  // endpoint exige sesión. Iniciamos una sesión efímera SOLO con encabezados
  // explícitos (sin tocar la sesión guardada).
  const finca = limpiar({
    nombre_finca: usuario.nombre_finca,
    cultivos_principales: usuario.cultivos_principales,
  });
  if (Object.keys(finca).length > 0 && usuario.clave) {
    try {
      const sesion = await peticion<{ token: string }>('/auth/login', {
        method: 'POST',
        body: JSON.stringify({ correo: usuario.correo, clave: usuario.clave }),
      });
      const auth = { Authorization: `Bearer ${sesion.token}` };
      await peticion(`/usuarios/${creado.id}`, {
        method: 'PUT',
        headers: auth,
        body: JSON.stringify(finca),
      });
      // No se llama a /auth/logout: el JWT del backend es determinista por segundo y revocarlo
      // podría invalidar un login inmediato del mismo usuario. Expira solo.
    } catch {
      // El usuario ya quedó creado; los datos de finca se pueden completar en el perfil.
    }
  }

  return creado;
}

export async function editarUsuarioApi(id: number, cambios: any): Promise<any> {
  const payload: Record<string, any> = { ...cambios };

  // La app habla en nombres de rol; el backend en rol_id.
  if (payload.rol !== undefined) {
    payload.rol_id = await resolverRolId(payload.rol);
    delete payload.rol;
  }
  // El backend no verifica la clave actual (no existe ese campo en UsuarioEditar).
  delete payload.clave_actual;

  // Estos campos no pueden ir vacíos según los validadores del backend.
  ['nombre', 'telefono', 'correo', 'clave'].forEach((k) => {
    if (payload[k] === '') delete payload[k];
  });

  return peticion(`/usuarios/${id}`, {
    method: 'PUT',
    body: JSON.stringify(limpiar(payload)),
  });
}

export async function eliminarUsuarioApi(id: number): Promise<any> {
  return peticion(`/usuarios/${id}?confirmar=true`, {
    method: 'DELETE',
  });
}

// ============================================================
// LOTES
// ============================================================

/** Traduce nombres de la app a los de LoteCrear / LoteEditar del backend. */
function payloadLote(l: any): Record<string, any> {
  const producto =
    l.producto ??
    (l.cultivo ? (l.variedad ? `${String(l.cultivo).trim()} ${String(l.variedad).trim()}` : String(l.cultivo).trim()) : undefined);
  const cantidad = l.cantidad ?? l.cantidad_total;
  const precio = l.precio_kg ?? l.precio_por_kilo;

  return limpiar({
    producto,
    cantidad: cantidad !== undefined ? entero(cantidad) : undefined,
    categoria: l.categoria ?? l.categoria_nombre,
    productor_id: l.productor_id ?? l.usuario_id,
    estado: l.estado,
    fecha_siembra: l.fecha_siembra || undefined,
    fecha_cosecha: l.fecha_cosecha ?? (l.fecha_cosecha_estimada || undefined),
    precio_kg: precio !== undefined && precio !== '' ? num(precio) : undefined,
    imagen_url: l.imagen_url,
    anticipo_pct: l.anticipo_pct,
    horas_limite_pago: l.horas_limite_pago,
  });
}

export async function obtenerLotes(filtros: Record<string, any> = {}): Promise<any[]> {
  const f = { ...filtros };
  // El filtro del backend se llama productor_id (usuario_id se ignoraba y devolvía TODOS los lotes).
  if (f.usuario_id !== undefined) {
    if (f.productor_id === undefined) f.productor_id = f.usuario_id;
    delete f.usuario_id;
  }
  const lotes = await peticion<any[]>(`/lotes${qs(f)}`);
  return lotes.map(adaptarLote);
}

export async function registrarLote(lote: any): Promise<any> {
  const payload = payloadLote(lote);
  const creado = await peticion('/lotes', {
    method: 'POST',
    body: JSON.stringify(payload),
  });
  return adaptarLote(creado);
}

export async function editarLoteApi(id: number, cambios: any): Promise<any> {
  const payload = payloadLote(cambios);
  // productor_id no se edita en LoteEditar
  delete payload.productor_id;
  const editado = await peticion(`/lotes/${id}`, {
    method: 'PUT',
    body: JSON.stringify(payload),
  });
  return adaptarLote(editado);
}

export async function actualizarEstadoCultivo(id: number, estadoCultivo: string): Promise<any> {
  return peticion(`/lotes/${id}/estado-cultivo`, {
    method: 'PUT',
    body: JSON.stringify({ estado_cultivo: estadoCultivo }),
  });
}

export async function obtenerHistorialLote(id: number): Promise<any[]> {
  const eventos = await peticion<any[]>(`/lotes/${id}/historial`);
  return eventos.map(adaptarEvento);
}

export async function eliminarLoteApi(id: number): Promise<any> {
  return peticion(`/lotes/${id}?confirmar=true`, {
    method: 'DELETE',
  });
}

// ============================================================
// ROLES
// ============================================================

export async function obtenerRoles(): Promise<any[]> {
  return peticion('/roles');
}

export async function registrarRol(rol: any): Promise<any> {
  const id = rol.id ?? (await siguienteId('/roles'));
  return peticion('/roles', {
    method: 'POST',
    body: JSON.stringify(
      limpiar({
        id,
        nombre: rol.nombre,
        descripcion: rol.descripcion,
        permisos: rol.permisos,
      })
    ),
  });
}

export async function editarRolApi(id: number, cambios: any): Promise<any> {
  return peticion(`/roles/${id}`, {
    method: 'PUT',
    body: JSON.stringify(
      limpiar({
        nombre: cambios.nombre,
        descripcion: cambios.descripcion,
        permisos: cambios.permisos,
      })
    ),
  });
}

export async function eliminarRolApi(id: number): Promise<any> {
  return peticion(`/roles/${id}?confirmar=true`, {
    method: 'DELETE',
  });
}

// ============================================================
// RESERVAS
// ============================================================

export async function obtenerReservas(filtros: Record<string, any> = {}): Promise<any[]> {
  const reservas = await peticion<any[]>(`/reservas${qs(filtros)}`);
  return reservas.map(adaptarReserva);
}

export async function crearReserva(reserva: any): Promise<any> {
  const creada = await peticion('/reservas', {
    method: 'POST',
    body: JSON.stringify({
      comprador_id: reserva.comprador_id,
      lote_id: reserva.lote_id,
      cantidad: entero(reserva.cantidad),
    }),
  });
  return adaptarReserva(creada);
}

export async function editarEstadoReserva(id: number, cambios: any): Promise<any> {
  return peticion(`/reservas/${id}/estado`, {
    method: 'PUT',
    body: JSON.stringify(
      limpiar({
        estado: cambios.estado,
        motivo_cancelacion: cambios.motivo_cancelacion,
      })
    ),
  });
}

export async function eliminarReservaApi(id: number): Promise<any> {
  return peticion(`/reservas/${id}?confirmar=true`, {
    method: 'DELETE',
  });
}

// ============================================================
// CATEGORÍAS
// ============================================================

export async function obtenerCategorias(): Promise<any[]> {
  return peticion('/categorias');
}

export async function obtenerLotesPorCategoria(nombre: string, filtros: Record<string, any> = {}): Promise<any[]> {
  const lotes = await peticion<any[]>(`/categorias/${encodeURIComponent(nombre)}/lotes${qs(filtros)}`);
  return lotes.map(adaptarLote);
}

export async function registrarCategoria(categoria: any): Promise<any> {
  return peticion('/categorias', {
    method: 'POST',
    body: JSON.stringify({ nombre: categoria.nombre }),
  });
}

export async function editarCategoriaApi(nombre: string, cambios: any): Promise<any> {
  return peticion(`/categorias/${encodeURIComponent(nombre)}`, {
    method: 'PUT',
    body: JSON.stringify({ nombre_nuevo: cambios.nombre_nuevo ?? cambios.nombre }),
  });
}

export async function eliminarCategoriaApi(nombre: string): Promise<any> {
  return peticion(`/categorias/${encodeURIComponent(nombre)}`, {
    method: 'DELETE',
  });
}

// ============================================================
// TIPOS DE DOCUMENTO
// ============================================================

export async function obtenerTiposDocumento(): Promise<any[]> {
  return peticion('/tipos_documento');
}

// ============================================================
// HISTORIALES
// ============================================================

export async function obtenerHistorialSeguimiento(filtros: Record<string, any> = {}): Promise<any[]> {
  return peticion(`/historial_seguimiento${qs(filtros)}`);
}

export async function obtenerHistorialReservas(filtros: Record<string, any> = {}): Promise<any[]> {
  return peticion(`/historial_reservas${qs(filtros)}`);
}

// ============================================================
// COMPRAS Y VENTAS
// ============================================================

export async function obtenerCompras(filtros: Record<string, any> = {}): Promise<any[]> {
  return peticion(`/compras${qs(filtros)}`);
}

export async function obtenerVentas(filtros: Record<string, any> = {}): Promise<any[]> {
  return peticion(`/ventas${qs(filtros)}`);
}

// ============================================================
// PROVEEDORES
// ============================================================

export async function obtenerProveedores(filtros: Record<string, any> = {}): Promise<any[]> {
  const lista = await peticion<any[]>(`/proveedores${qs(filtros)}`);
  return lista.map(adaptarProveedor);
}

export async function obtenerProveedorPorId(id: number): Promise<any> {
  return adaptarProveedor(await peticion(`/proveedores/${id}`));
}

export async function registrarProveedor(proveedor: any): Promise<any> {
  const id = proveedor.id ?? (await siguienteId('/proveedores'));
  return peticion('/proveedores', {
    method: 'POST',
    body: JSON.stringify(
      limpiar({
        id,
        nombre: proveedor.nombre,
        tipo: proveedor.tipo ?? proveedor.servicio ?? 'General',
        ciudad: proveedor.ciudad,
        telefono: proveedor.telefono,
        correo: proveedor.correo,
        estado: proveedor.estado || 'Activo',
      })
    ),
  });
}

export async function editarProveedorApi(id: number, cambios: any): Promise<any> {
  return peticion(`/proveedores/${id}`, {
    method: 'PUT',
    body: JSON.stringify(
      limpiar({
        nombre: cambios.nombre,
        tipo: cambios.tipo ?? cambios.servicio,
        ciudad: cambios.ciudad,
        telefono: cambios.telefono,
        correo: cambios.correo,
        estado: cambios.estado,
      })
    ),
  });
}

export async function eliminarProveedorApi(id: number): Promise<any> {
  return peticion(`/proveedores/${id}?confirmar=true`, {
    method: 'DELETE',
  });
}

// ============================================================
// FAVORITOS
// ============================================================

export async function obtenerFavoritos(compradorId: number): Promise<any[]> {
  const lista = await peticion<any[]>(`/favoritos?comprador_id=${encodeURIComponent(compradorId)}`);
  return lista.map(adaptarFavorito);
}

export async function agregarFavorito(compradorId: number, productorId: number): Promise<any> {
  return peticion('/favoritos', {
    method: 'POST',
    body: JSON.stringify({
      comprador_id: compradorId,
      productor_id: productorId,
    }),
  });
}

export async function eliminarFavoritoApi(compradorId: number, productorId: number): Promise<any> {
  return peticion(`/favoritos/${compradorId}/${productorId}?confirmar=true`, {
    method: 'DELETE',
  });
}

// ============================================================
// SOPORTE
// ============================================================

/**
 * SoporteCrear exige nombre, correo (válido) y mensaje. Si hay sesión se
 * completan con los datos del usuario; el asunto se antepone al mensaje.
 */
export async function enviarSoporte(datos: any): Promise<any> {
  let usuario: any = null;
  try {
    const guardado = await AsyncStorage.getItem(USER_KEY);
    if (guardado) usuario = JSON.parse(guardado);
  } catch {
    // sin sesión
  }

  const nombre = datos.nombre || usuario?.nombre;
  const correo = datos.correo || datos.email || usuario?.correo;
  if (!nombre || !correo) {
    throw new Error('Indica tu nombre y un correo electrónico para que podamos responderte.');
  }

  const cuerpo = datos.asunto ? `[${String(datos.asunto).trim()}] ${datos.mensaje}` : datos.mensaje;

  return peticion('/soporte', {
    method: 'POST',
    body: JSON.stringify(
      limpiar({
        usuario_id: datos.usuario_id ?? usuario?.id,
        nombre,
        correo,
        mensaje: cuerpo,
      })
    ),
  });
}

export async function obtenerTicketsSoporte(filtros: Record<string, any> = {}): Promise<any[]> {
  const lista = await peticion<any[]>(`/soporte${qs(filtros)}`);
  return lista.map(adaptarTicket);
}

export async function actualizarEstadoSoporte(id: number, estado: string): Promise<any> {
  return peticion(`/soporte/${id}/estado`, {
    method: 'PUT',
    body: JSON.stringify({ estado }),
  });
}

export async function eliminarTicketSoporte(id: number): Promise<any> {
  return peticion(`/soporte/${id}?confirmar=true`, {
    method: 'DELETE',
  });
}

// ============================================================
// PAGOS
// ============================================================

export async function crearPago(datos: {
  reserva_id: number;
  metodo?: string;
  monto?: number;
  resultado_simulado?: string;
}): Promise<any> {
  if (!datos || !datos.reserva_id) {
    throw new Error('El reserva_id es obligatorio para crear el pago.');
  }

  const payload: any = {
    reserva_id: Number(datos.reserva_id),
    metodo: datos.metodo || 'Simulado - Tarjeta',
  };

  if (datos.monto !== undefined && datos.monto !== null) {
    payload.monto = Number(datos.monto);
  }

  if (datos.resultado_simulado !== undefined && datos.resultado_simulado !== null) {
    payload.resultado_simulado = datos.resultado_simulado;
  }

  return peticion('/pagos', {
    method: 'POST',
    body: JSON.stringify(payload),
  });
}

/**
 * Devuelve el resumen de pagos de una reserva:
 * { monto_total_reserva, monto_pagado, monto_pendiente, anticipo_pct, monto_anticipo, pagos: [...] }
 */
export async function obtenerPagos(reservaId: number): Promise<any> {
  if (!reservaId) {
    throw new Error('El reserva_id es obligatorio.');
  }
  return peticion(`/pagos?reserva_id=${encodeURIComponent(reservaId)}`);
}

export async function simularPagoAprobado(reservaId: number, monto: number | null = null, metodo = 'Simulado - Tarjeta') {
  const datos: any = {
    reserva_id: Number(reservaId),
    metodo,
    resultado_simulado: 'aprobado',
  };
  if (monto !== null && monto !== undefined) {
    datos.monto = Number(monto);
  }
  return crearPago(datos);
}

export async function simularPagoFallido(reservaId: number, monto: number | null = null, metodo = 'Simulado - Tarjeta') {
  const datos: any = {
    reserva_id: Number(reservaId),
    metodo,
    resultado_simulado: 'fallido',
  };
  if (monto !== null && monto !== undefined) {
    datos.monto = Number(monto);
  }
  return crearPago(datos);
}

// ============================================================
// ENTREGAS
// ============================================================

/** El Productor despacha una reserva "Pagada": { reserva_id, medio, fecha_estimada? }. */
export async function crearEntrega(datos: any): Promise<any> {
  return peticion('/entregas', {
    method: 'POST',
    body: JSON.stringify(
      limpiar({
        reserva_id: Number(datos.reserva_id),
        medio: datos.medio,
        fecha_estimada: datos.fecha_estimada || undefined,
      })
    ),
  });
}

export async function actualizarUbicacionEntrega(entregaId: number, latitud: number, longitud: number): Promise<any> {
  return peticion(`/entregas/${entregaId}/ubicacion`, {
    method: 'PUT',
    body: JSON.stringify({ latitud, longitud }),
  });
}

/**
 * Productor/Admin: { estado }.
 * Comprador: { codigo_confirmacion } para confirmar la recepción.
 */
export async function actualizarEntrega(id: number, cambios: any): Promise<any> {
  return peticion(`/entregas/${id}`, {
    method: 'PUT',
    body: JSON.stringify(
      limpiar({
        estado: cambios.estado,
        codigo_confirmacion: cambios.codigo_confirmacion,
      })
    ),
  });
}

export async function obtenerEntregas(reservaId: number): Promise<any[]> {
  return peticion(`/entregas?reserva_id=${encodeURIComponent(reservaId)}`);
}

// ============================================================
// CALIFICACIONES
// ============================================================

/** CalificacionCrear: { reserva_id, estrellas (1-5), comentario? }. */
export async function crearCalificacion(datos: any): Promise<any> {
  return peticion('/calificaciones', {
    method: 'POST',
    body: JSON.stringify(
      limpiar({
        reserva_id: Number(datos.reserva_id),
        estrellas: entero(datos.estrellas ?? datos.puntuacion),
        comentario: datos.comentario,
      })
    ),
  });
}

export async function obtenerCalificaciones(productorId: number): Promise<any> {
  const res = await peticion<any>(`/calificaciones?productor_id=${encodeURIComponent(productorId)}`);
  if (res && Array.isArray(res.calificaciones)) {
    return { ...res, calificaciones: res.calificaciones.map(adaptarCalificacion) };
  }
  return res;
}

// ============================================================
// DISPUTAS
// ============================================================

/** DisputaCrear: { reserva_id, descripcion }. El motivo se antepone a la descripción. */
export async function crearDisputa(datos: any): Promise<any> {
  const descripcion = datos.motivo
    ? `${String(datos.motivo).trim()}: ${String(datos.descripcion).trim()}`
    : datos.descripcion;
  return peticion('/disputas', {
    method: 'POST',
    body: JSON.stringify({
      reserva_id: Number(datos.reserva_id),
      descripcion,
    }),
  });
}

export async function obtenerDisputas(filtros: Record<string, any> = {}): Promise<any[]> {
  const lista = await peticion<any[]>(`/disputas${qs(filtros)}`);
  return lista.map(adaptarDisputa);
}

export async function actualizarDisputa(id: number, cambios: any): Promise<any> {
  return peticion(`/disputas/${id}`, {
    method: 'PUT',
    body: JSON.stringify(
      limpiar({
        estado: cambios.estado,
        resolucion: cambios.resolucion,
        reembolsar: cambios.reembolsar,
      })
    ),
  });
}

// ============================================================
// REPORTES
// ============================================================

export async function obtenerReporteProductor(productorId: number | null = null): Promise<any> {
  const r = await peticion<any>(`/reportes/productor${qs({ productor_id: productorId })}`);
  return {
    ...r,
    ingresos_brutos: r.ingresos_totales,
    total_ventas: r.ingresos_totales,
    comision_retenida: r.comision_total,
    kg_totales_vendidos: r.total_kg_vendidos,
    kg_vendidos: r.total_kg_vendidos,
  };
}

export async function obtenerReporteComprador(compradorId: number | null = null): Promise<any> {
  return peticion(`/reportes/comprador${qs({ comprador_id: compradorId })}`);
}

export async function obtenerReporteAdmin(filtros: Record<string, any> = {}): Promise<any> {
  const r = await peticion<any>(`/reportes/admin${qs(filtros)}`);
  const monto = num(r.monto_total_transacciones);
  const comision = num(r.comision_total_plataforma);
  return {
    ...r,
    volumen_total: monto,
    gmv: monto,
    comisiones_totales: comision,
    comision_plataforma: comision,
    transferido_productores: monto - comision,
    total_transacciones: r.volumen_transacciones,
    transacciones: r.volumen_transacciones,
  };
}

// ============================================================
// PERFIL PÚBLICO PRODUCTOR
// ============================================================

/** Perfil + lotes activos del productor, con la forma { ...perfil, usuario, lotes }. */
export async function obtenerPerfilPublico(usuarioId: number): Promise<any> {
  const [perfil, lotes] = await Promise.all([
    peticion<any>(`/usuarios/${usuarioId}/perfil-publico`),
    peticion<any[]>(`/lotes${qs({ productor_id: usuarioId, estado: 'Activo' })}`).catch(() => []),
  ]);
  return { ...perfil, usuario: perfil, lotes: lotes.map(adaptarLote) };
}

// ============================================================
// CONFIGURACIÓN
// ============================================================

export async function obtenerComision(): Promise<{ comision_pct: number }> {
  return peticion('/configuracion/comision');
}

export async function actualizarComision(comisionPct: number): Promise<any> {
  return peticion('/configuracion/comision', {
    method: 'PUT',
    body: JSON.stringify({ comision_pct: entero(comisionPct) }),
  });
}

// ============================================================
// NOTIFICACIONES
// ============================================================

/** Devuelve { no_leidas, notificaciones: [...] }. */
export async function obtenerNotificaciones(): Promise<any> {
  return peticion('/notificaciones');
}

export async function marcarNotificacionLeida(id: number): Promise<any> {
  return peticion(`/notificaciones/${id}/leer`, {
    method: 'PUT',
  });
}

export async function marcarTodasNotificacionesLeidas(): Promise<any> {
  return peticion('/notificaciones/leer-todas', {
    method: 'PUT',
  });
}

// ============================================================
// INCIDENCIAS
// ============================================================

export async function crearIncidencia(datos: any): Promise<any> {
  return peticion('/incidencias', {
    method: 'POST',
    body: JSON.stringify({
      lote_id: Number(datos.lote_id),
      tipo: datos.tipo,
      descripcion: datos.descripcion,
    }),
  });
}

export async function obtenerIncidencias(loteId: number): Promise<any[]> {
  return peticion(`/incidencias?lote_id=${encodeURIComponent(loteId)}`);
}

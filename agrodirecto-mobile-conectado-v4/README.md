# AgroDirecto Móvil (React Native + TypeScript + Expo Go)

Aplicación móvil oficial de **AgroDirecto**, desarrollada con **React Native**, **TypeScript** y configurada para ser ejecutada directamente con **Expo Go** en dispositivos móviles (Android / iOS).

---

## 🚀 Requisitos Previos

1. **Node.js** v18 o superior instalado.
2. Aplicación **Expo Go** instalada en tu teléfono móvil (disponible gratis en Google Play Store y Apple App Store).
3. El backend FastAPI de AgroDirecto ejecutándose en tu PC (`python -m uvicorn ...` en el puerto 8000).
4. El dispositivo móvil y la PC deben estar conectados a la **misma red Wi-Fi**.

---

## 📲 Cómo Iniciar la Aplicación Móvil

1. Abre una terminal en la carpeta `agrodirecto-mobile`:
   ```bash
   cd agrodirecto-mobile
   ```

2. Inicia el servidor de desarrollo de Expo:
   ```bash
   npx expo start
   ```

3. Escanea el código QR que aparece en la terminal con:
   - **Android:** La aplicación **Expo Go**.
   - **iOS:** La aplicación de **Cámara** nativa (abrirá en Expo Go).

---

## 🌐 Conexión con el Backend FastAPI

1. Levanta el backend **escuchando en toda la red** (necesario para el celular físico):
   ```bash
   cd backend/scr
   uvicorn main:app --host 0.0.0.0 --port 8000
   ```
   Si tu base ya existía, sincroniza el esquema una vez: `python ../migracion_esquema.py`.
2. URL por defecto: emulador Android `http://10.0.2.2:8000`, iOS/Web `http://127.0.0.1:8000`.
   Puedes fijarla con la variable `EXPO_PUBLIC_API_URL` (ej. `EXPO_PUBLIC_API_URL=http://192.168.1.50:8000 npx expo start`).
3. En **Expo Go con celular físico**: en el Login pulsa **⚙️ Servidor** e ingresa la IP de tu PC
   (`ipconfig` → IPv4), p. ej. `http://192.168.1.50:8000`. Se guarda en `AsyncStorage`.

Toda la comunicación pasa por `src/services/api.ts`, que traduce entre el modelo del backend
(`producto`, `cantidad`, `precio_kg`, `productor_id`, `estrellas`…) y el que usan las pantallas
(`cultivo`, `cantidad_total`, `precio_por_kilo`, `usuario_id`, `puntuacion`…). Si el backend cambia un
campo, el ajuste va en los adaptadores de ese archivo.

---

## 👥 Cuentas de Prueba (datos del `.sql` del backend)

- **Administrador:** `admin@agrodirecto.com` / `admin123`
- **Productor:** `finca.paraiso@campo.com` / `prod123`
- **Comprador:** `compras@laplaza.com` / `comp123`

(Requiere haber ejecutado `rehash_claves.py` en el backend.) El Login tiene botones de acceso rápido.

---

## 🔄 Ciclo de una reserva (así lo exige el backend)

`Pendiente` → el **productor confirma** → `Confirmada` → el **comprador paga** (anticipo del lote o total)
→ `Pagada` → el **productor despacha** (medio de envío, genera código) → `En tránsito` → el **comprador
confirma la recepción** → `Entregada` → el comprador **califica** → `Calificada`.

## 📁 Estructura del Proyecto

```
agrodirecto-mobile/
├── App.tsx                      # Componente raíz con AuthProvider y NavigationContainer
├── index.ts                     # Entrada principal de Expo
├── app.json                     # Metadatos de la app para Expo Go
├── tsconfig.json                # Configuración TypeScript
├── package.json                 # Dependencias (Expo 52, React 18, React Navigation 7)
└── src/
    ├── components/common/       # Componentes UI reutilizables (Badge, Button, Card, Header, InputField, StatCard, etc.)
    ├── context/
    │   └── AuthContext.tsx      # Manejo global de autenticación, JWT y rol
    ├── navigation/
    │   ├── AppNavigator.tsx     # Enrutador dinámico por rol (Público, Comprador, Productor, Admin)
    │   ├── PublicNavigator.tsx  # Rutas públicas (Home, Nosotros, Contacto, Login, Registro, Recuperación)
    │   ├── BuyerNavigator.tsx   # Tabs y Stack del Comprador
    │   ├── ProducerNavigator.tsx# Tabs y Stack del Productor Campesino
    │   └── AdminNavigator.tsx   # Tabs y Stack del Administrador
    ├── screens/
    │   ├── public/              # Pantallas públicas informativas y de acceso
    │   ├── buyer/               # Panel, Catálogo, Reservas, Entregas, Pagos, Favoritos, Perfil Finca
    │   ├── producer/            # Panel, Mis Cultivos, Ventas/Despacho, Trazabilidad, Reportes
    │   ├── admin/               # Panel, Usuarios, Roles, Lotes, Categorías, Proveedores, Auditoría, Soporte, Reportes
    │   └── shared/              # Perfil, Notificaciones, Disputas y Reclamos
    ├── services/
    │   ├── api.ts               # Cliente REST + adaptadores backend↔pantallas, JWT, timeout y sesión expirada
    │   └── config.ts            # Gestor de URL base del backend y persistencia
    └── theme/
        └── colors.ts            # Paleta de colores institucional AgroDirecto
```

---

## 🛠️ Comprobación de Tipos TypeScript

Para verificar que el código no tenga ningún error de tipos:
```bash
npx tsc --noEmit
```
Resultado: **0 errores**.

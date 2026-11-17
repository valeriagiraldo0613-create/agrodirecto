AGRODIRECTO - GUIA DE DESPLIEGUE EN RENDER
=========================================

IMPORTANTE: este repositorio NO es un proyecto Django. La carpeta backend contiene una API FastAPI con SQLAlchemy, PostgreSQL y Alembic. La carpeta frontend contiene una aplicación React/Vite. También existe una aplicación móvil Expo en agrodirecto-mobile-conectado-v4; Expo no se publica como un servicio web tradicional de Render.

Esta guía cubre la publicación de la API FastAPI y, opcionalmente, del frontend React como dos servicios separados.

1. REQUISITOS PREVIOS
---------------------
- Cuenta de GitHub con el repositorio AgroDirecto.
- Cuenta de Render: https://render.com/
- Repositorio subido a GitHub.
- Acceso para crear una base PostgreSQL en Render.
- Antes de producción, corregir las variables de entorno y la configuración indicadas en la sección 8.

2. ESTRUCTURA RELEVANTE DEL REPOSITORIO
---------------------------------------
Feria-main/
  backend/
    requirements.txt
    alembic.ini
    alembic/
    scr/
      main.py
      Conexion/database.py
      Utilidades/seguridad.py
  frontend/
    package.json
    vite.config.ts
    src/ (código de React)
  agrodirecto-mobile-conectado-v4/
    package.json
    App.tsx

La API inicia desde backend/scr/main.py y crea el objeto FastAPI llamado app.

3. BASE DE DATOS POSTGRESQL EN RENDER
-------------------------------------
1. En Render, abrir Dashboard.
2. Seleccionar New + > PostgreSQL.
3. Asignar un nombre, por ejemplo agrodirecto-db.
4. Elegir la región más cercana a la API.
5. Crear la base de datos con el plan disponible.
6. Abrir la página de la base de datos y copiar Internal Database URL para usarla desde otro servicio Render de la misma región. Si se conecta desde fuera de Render, usar External Database URL.
7. Guardar la URL como variable DATABASE_URL en el servicio API. No publicar esta URL ni subirla a GitHub.

NOTA SOBRE EL PLAN GRATUITO: las condiciones, límites, vencimiento y disponibilidad de PostgreSQL gratuito pueden cambiar. Revisar el plan que muestra Render al crear la base. No usar el plan gratuito como única copia de datos importantes. Configurar respaldos externos y considerar un plan con persistencia adecuada antes de uso real.

4. PUBLICAR LA API FASTAPI
--------------------------
1. En Render, seleccionar New + > Web Service.
2. Conectar GitHub y elegir el repositorio AgroDirecto.
3. Configurar:
   - Name: agrodirecto-api
   - Runtime: Python
   - Root Directory: backend
   - Build Command: pip install -r requirements.txt
   - Start Command: uvicorn main:app --app-dir scr --host 0.0.0.0 --port $PORT
4. Crear el servicio.
5. En Environment agregar las variables descritas en la sección 5.
6. Guardar cambios y esperar el deploy.

El comando de inicio usa --app-dir scr porque main.py importa módulos como Conexion, Modelos y Rutas desde esa carpeta.

5. VARIABLES DE ENTORNO DE LA API
---------------------------------
Configurar en Render > servicio agrodirecto-api > Environment:

DATABASE_URL
  URL de PostgreSQL creada por Render. Usar Internal Database URL cuando API y DB estén en Render y en la misma región.

CLAVE_SECRETA
  Cadena aleatoria larga y privada para firmar JWT. Generar una clave nueva; no reutilizar la que aparece actualmente escrita en el código.

CORS_ORIGINS
  Lista de orígenes del frontend separados por comas. Ejemplo:
  https://agrodirecto-web.onrender.com
  Agregar localhost solo para desarrollo, no como sustituto del dominio de producción.

ENVIRONMENT
  production

PORT
  Render define PORT automáticamente. No fijar un puerto constante en el código; Uvicorn debe usar $PORT.

IMPORTANTE: en el estado actual del ZIP, database.py todavía contiene una URL local con usuario/contraseña y seguridad.py contiene una clave JWT fija. Definir variables en Render por sí solo NO cambia esos valores: el código debe modificarse para leer DATABASE_URL y CLAVE_SECRETA desde os.environ antes del despliegue.

6. PUBLICAR EL FRONTEND REACT/VITE (OPCIONAL)
---------------------------------------------
El frontend está en frontend/ y tiene package.json con Vite.

1. En Render seleccionar New + > Static Site.
2. Conectar el mismo repositorio.
3. Configurar:
   - Name: agrodirecto-web
   - Root Directory: frontend
   - Build Command: npm ci && npm run build
   - Publish Directory: dist
4. Crear el sitio.
5. Configurar la variable que use el código del frontend para la URL de API. En Vite, las variables expuestas al navegador normalmente deben comenzar por VITE_. Por ejemplo VITE_API_URL=https://agrodirecto-api.onrender.com, pero confirmar el nombre exacto que consume el código antes de configurarla.
6. Agregar el dominio final del frontend a CORS_ORIGINS en la API y volver a desplegar la API.

Si React Router se usa para rutas del lado del cliente, configurar una regla de rewrite en Render para que las rutas de la aplicación devuelvan /index.html.

7. COMPROBACIONES DESPUÉS DEL DESPLIEGUE
---------------------------------------
- Abrir https://NOMBRE-DEL-SERVICIO.onrender.com/docs. FastAPI debería mostrar Swagger UI.
- Probar un endpoint de lectura y uno de autenticación que no modifique datos importantes.
- Revisar Render > servicio > Logs si aparece un error.
- Confirmar que la API conecta a PostgreSQL y que las tablas existen.
- Abrir el frontend y verificar inicio de sesión, consultas y operaciones principales.
- Probar CORS desde el dominio real del frontend.
- Confirmar que los datos siguen presentes después de un redeploy.

8. PROBLEMAS CRÍTICOS DETECTADOS EN EL ZIP Y ACCIONES ANTES DE PRODUCCIÓN
---------------------------------------------------------------------------
A. Conexión de base de datos local
Archivo: backend/scr/Conexion/database.py
Actualmente SQLALCHEMY_DATABASE_URL está escrita como una URL postgresql+psycopg2 hacia localhost con credenciales de desarrollo. En Render localhost apunta al propio contenedor, no a la base PostgreSQL administrada. Modificar el archivo para leer DATABASE_URL del entorno y convertir el esquema postgres:// o postgresql:// a postgresql+psycopg2:// si hace falta.

B. Clave JWT fija
Archivo: backend/scr/Utilidades/seguridad.py
CLAVE_SECRETA está escrita directamente en el código. Cambiarla para leer CLAVE_SECRETA desde el entorno y detener el arranque si no está definida en producción. Invalidar tokens antiguos al cambiar la clave y no compartirla.

C. CORS limitado a localhost
Archivo: backend/scr/main.py
Actualmente allow_origin_regex permite únicamente localhost y 127.0.0.1. Añadir el dominio real del frontend mediante una lista de orígenes de entorno. No habilitar cualquier origen indiscriminadamente cuando se usan credenciales.

D. Migración Alembic inicial vacía
Existe alembic/versions/be0f5201fe69_baseline_esquema_ya_existente_en_la_bd.py y su upgrade() está vacío intencionalmente. El comentario indica que se creó para marcar una base de datos que YA tenía el esquema, mediante alembic stamp head. No crea tablas en una base nueva. Antes de ejecutar alembic upgrade head en una base vacía, crear una migración inicial real que cree todas las tablas, o preparar y validar un proceso seguro de inicialización del esquema. No asumir que esta migración vacía crea las tablas.

E. Creación automática de tablas al importar la API
Archivo: backend/scr/main.py
Actualmente se ejecuta Base.metadata.create_all(bind=engine) al importar el módulo. Esto puede ocultar la falta de migraciones y producir cambios de esquema fuera de Alembic. Para producción, preferir migraciones controladas y retirar create_all del arranque una vez que exista una migración inicial válida.

F. Usuario administrador
El proyecto usa roles y usuarios propios, no el sistema Django. No ejecutar createsuperuser de Django. Si se necesita un administrador inicial, crear un comando idempotente propio que use el modelo y el mecanismo de hash de contraseñas existentes. Las credenciales deben recibirse como variables privadas y no imprimirse en logs. No inventar nombres de campos o relaciones sin revisar los modelos.

G. Archivos locales y logs
Los archivos escritos dentro del contenedor pueden perderse al reiniciar o desplegar. No guardar allí datos de usuarios, documentos ni archivos que deban persistir. Enviar logs a stdout/stderr para consultarlos en Render. Para archivos subidos por usuarios usar almacenamiento externo persistente.

H. WebSockets
En la revisión de main.py no se identificó una ruta WebSocket registrada en el punto de entrada revisado. Revisar también todas las rutas y dependencias antes de afirmar que el proyecto completo no usa WebSockets. El servicio web de Render admite HTTP; cualquier funcionalidad en tiempo real debe validarse según el tipo de servicio y plan.

I. Repositorio ZIP
El ZIP recibido contiene carpetas de entorno virtual, node_modules, .git y .expo. No subir esas carpetas al repositorio. Subir solo código fuente y archivos de configuración necesarios. Mantener secretos fuera de Git.

9. SOLUCIÓN DE PROBLEMAS
------------------------
Error: ModuleNotFoundError (por ejemplo, No module named 'Conexion')
- Confirmar Root Directory = backend.
- Confirmar Start Command = uvicorn main:app --app-dir scr --host 0.0.0.0 --port $PORT.

Error: conexión rechazada a localhost / OperationalError
- DATABASE_URL no está configurada o el código sigue usando la URL local.
- Confirmar que la base está activa y usar Internal Database URL desde Render.

Error: contraseña/autenticación JWT inválida después del despliegue
- Confirmar que CLAVE_SECRETA está configurada y que todos los procesos usan el mismo valor.
- No cambiarla en cada arranque.

Error: CORS policy
- Añadir el origen exacto del frontend (incluyendo https://) a CORS_ORIGINS.
- Revisar que el frontend consuma la URL pública de la API.

Error: tablas no existen
- La migración baseline actual no crea tablas. Preparar y ejecutar una migración inicial real o inicializar el esquema de forma controlada antes de recibir tráfico.

Error: servicio tarda en responder tras inactividad
- Los servicios gratuitos pueden entrar en suspensión por inactividad y tardar en arrancar al recibir una nueva solicitud. Esto es una limitación del plan.

Error: frontend muestra página no encontrada al refrescar una ruta
- Configurar rewrite de rutas SPA hacia /index.html en el Static Site.

10. RECOMENDACIONES FINALES
---------------------------
- Hacer un respaldo antes de migrar datos.
- Probar primero en una base de datos de pruebas.
- No subir .env, claves, tokens, contraseñas ni archivos de base de datos.
- Fijar versiones de dependencias en requirements.txt para builds reproducibles.
- No considerar listo el despliegue hasta corregir los puntos A, B, C y D.
- Render puede cambiar los límites de sus planes gratuitos; revisar la documentación y el panel al momento del despliegue.

FIN DEL DOCUMENTO
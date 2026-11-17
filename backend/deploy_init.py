"""Inicialización idempotente del esquema y datos de referencia de AgroDirecto."""
import os
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BACKEND_DIR / "scr"))

from Conexion.database import Base, engine, SessionLocal
import Modelos.models as models  # registra todas las tablas en metadata
from Utilidades.seguridad import hashear_clave

def inicializar():
    # Crea las tablas que falten usando los modelos actuales.
    Base.metadata.create_all(bind=engine)

    db = SessionLocal()
    try:
        # Datos de catálogo indispensables para las relaciones de la aplicación.
        for codigo, nombre in [
            ("CC", "Cédula de Ciudadanía"),
            ("NIT", "Número de Identificación Tributaria"),
            ("CE", "Cédula de Extranjería"),
            ("PP", "Pasaporte"),
        ]:
            if not db.query(models.TipoDocumento).filter_by(codigo=codigo).first():
                db.add(models.TipoDocumento(codigo=codigo, nombre=nombre))

        for nombre, descripcion, permisos in [
            ("Administrador", "Acceso total al sistema", "Ver, Crear, Editar, Eliminar"),
            ("Productor", "Gestiona lotes y actualiza cosechas", "Ver, Crear, Editar"),
            ("Comprador", "Explora lotes y crea reservas", "Ver, Crear"),
        ]:
            if not db.query(models.Rol).filter_by(nombre=nombre).first():
                db.add(models.Rol(nombre=nombre, descripcion=descripcion, permisos=permisos))

        for nombre in ["Hortaliza", "Fruta", "Tuberculo", "Cereal", "Leguminosa"]:
            if not db.query(models.Categoria).filter_by(nombre=nombre).first():
                db.add(models.Categoria(nombre=nombre))

        db.commit()

        # Crear administrador personalizado solo si se proporcionan TODAS las
        # variables. No se inventan credenciales ni se reutilizan usuarios demo.
        admin_vars = {
            "ADMIN_NAME": os.getenv("ADMIN_NAME"),
            "ADMIN_EMAIL": os.getenv("ADMIN_EMAIL"),
            "ADMIN_PASSWORD": os.getenv("ADMIN_PASSWORD"),
            "ADMIN_DOCUMENT_TYPE": os.getenv("ADMIN_DOCUMENT_TYPE", "CC"),
            "ADMIN_DOCUMENT_NUMBER": os.getenv("ADMIN_DOCUMENT_NUMBER"),
            "ADMIN_PHONE": os.getenv("ADMIN_PHONE"),
        }
        required_admin_values = [
            admin_vars["ADMIN_NAME"],
            admin_vars["ADMIN_EMAIL"],
            admin_vars["ADMIN_PASSWORD"],
            admin_vars["ADMIN_DOCUMENT_NUMBER"],
            admin_vars["ADMIN_PHONE"],
        ]
        if any(required_admin_values) and not all(required_admin_values):
            raise RuntimeError(
                "Para crear el administrador configura ADMIN_NAME, ADMIN_EMAIL, "
                "ADMIN_PASSWORD, ADMIN_DOCUMENT_NUMBER y ADMIN_PHONE."
            )
        if all(required_admin_values):
            if len(admin_vars["ADMIN_PASSWORD"]) < 12:
                raise RuntimeError("ADMIN_PASSWORD debe tener al menos 12 caracteres.")
            existing = db.query(models.Usuario).filter(
                models.Usuario.correo == admin_vars["ADMIN_EMAIL"].strip().lower()
            ).first()
            if not existing:
                rol = db.query(models.Rol).filter_by(nombre="Administrador").one()
                tipo = db.query(models.TipoDocumento).filter_by(
                    codigo=admin_vars["ADMIN_DOCUMENT_TYPE"]
                ).first()
                if not tipo:
                    raise RuntimeError("ADMIN_DOCUMENT_TYPE no existe en tipos_documento.")
                usuario = models.Usuario(
                    tipo_documento=tipo.codigo,
                    numero_documento=admin_vars["ADMIN_DOCUMENT_NUMBER"],
                    nombre=admin_vars["ADMIN_NAME"],
                    correo=admin_vars["ADMIN_EMAIL"].strip().lower(),
                    telefono=admin_vars["ADMIN_PHONE"],
                    clave=hashear_clave(admin_vars["ADMIN_PASSWORD"]),
                    rol_id=rol.id,
                    estado="Activo",
                )
                db.add(usuario)
                db.commit()
                print("Administrador inicial creado.")
            else:
                print("El correo administrador ya existe; no se modificó.")
        else:
            print("Variables ADMIN_* no configuradas: se omite la creación del administrador.")
    finally:
        db.close()

if __name__ == "__main__":
    inicializar()

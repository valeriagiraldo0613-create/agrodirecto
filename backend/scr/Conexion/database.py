import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base

def _database_url() -> str:
    url = os.getenv("DATABASE_URL")
    if not url:
        # Solo para desarrollo local. En Render DATABASE_URL es obligatoria.
        if os.getenv("RENDER") or os.getenv("ENVIRONMENT") == "production":
            raise RuntimeError("Falta configurar la variable DATABASE_URL.")
        url = "postgresql+psycopg2://postgres:1234@localhost/agro_mercado"

    # Render puede entregar URLs con esquemas postgres:// o postgresql://.
    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql+psycopg2://", 1)
    elif url.startswith("postgresql://"):
        url = url.replace("postgresql://", "postgresql+psycopg2://", 1)
    return url

SQLALCHEMY_DATABASE_URL = _database_url()

engine = create_engine(
    SQLALCHEMY_DATABASE_URL,
    pool_pre_ping=True,
    pool_recycle=300,
    connect_args={"connect_timeout": 10},
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

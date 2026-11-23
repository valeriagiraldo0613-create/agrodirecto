import importlib
import os
import pkgutil
import sys

import pytest
from sqlalchemy import create_engine, event, func as _func
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCR_DIR = os.path.join(BACKEND_DIR, "scr")
if SCR_DIR not in sys.path:
    sys.path.insert(0, SCR_DIR)

# Must be set before Conexion.database or main is imported
os.environ["DATABASE_URL"] = "sqlite:///:memory:"

import Conexion.database as database  # noqa: E402
import Controladores  # noqa: E402
import Utilidades.ids as ids_mod  # noqa: E402

_TEST_ENGINE = create_engine(
    "sqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)


@event.listens_for(_TEST_ENGINE, "connect")
def _enable_sqlite_fk(dbapi_conn, _conn_record):
    cursor = dbapi_conn.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


_TestSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=_TEST_ENGINE)

database.engine = _TEST_ENGINE
database.SessionLocal = _TestSessionLocal


def _siguiente_id_sqlite(db, modelo):
    maximo_bd = db.query(_func.max(modelo.id)).scalar() or 0
    maximo_pendiente = max(
        (obj.id for obj in db.new if isinstance(obj, modelo) and obj.id is not None),
        default=0,
    )
    return max(maximo_bd, maximo_pendiente) + 1


ids_mod.siguiente_id = _siguiente_id_sqlite
for _, modname, _ in pkgutil.iter_modules(Controladores.__path__):
    mod = importlib.import_module(f"Controladores.{modname}")
    if hasattr(mod, "siguiente_id"):
        mod.siguiente_id = _siguiente_id_sqlite


@pytest.fixture(autouse=True)
def _reset_sqlite_schema():
    database.Base.metadata.drop_all(bind=_TEST_ENGINE)
    database.Base.metadata.create_all(bind=_TEST_ENGINE)
    yield
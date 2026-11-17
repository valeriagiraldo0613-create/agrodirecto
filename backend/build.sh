#!/usr/bin/env bash
set -euo pipefail

echo "==> Instalando dependencias"
python -m pip install --upgrade pip
pip install -r requirements.txt

echo "==> Creando tablas, catálogos y administrador inicial (si fue configurado)"
python deploy_init.py

echo "==> Aplicando migraciones Alembic"
alembic upgrade head

echo "==> Build de AgroDirecto finalizado"

import logging
import os

logger = logging.getLogger("agrodirecto")
logger.setLevel(os.getenv("LOG_LEVEL", "INFO").upper())

if not logger.handlers:
    formatter = logging.Formatter(
        fmt="%(asctime)s | %(levelname)-8s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    console = logging.StreamHandler()
    console.setFormatter(formatter)
    logger.addHandler(console)

    # El sistema de archivos gratuito de Render es efímero.
    if os.getenv("ENVIRONMENT", "development").lower() != "production":
        logs_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "logs")
        os.makedirs(logs_dir, exist_ok=True)
        file_handler = logging.FileHandler(
            os.path.join(logs_dir, "backend.log"), encoding="utf-8"
        )
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)

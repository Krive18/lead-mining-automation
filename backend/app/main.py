import logging
from logging.handlers import RotatingFileHandler

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import router
from app.core.config import get_config
from app.core.database import init_database


def configure_logging() -> None:
    config = get_config()
    log_file_path = config.log_dir / "lead_mining_monitor_app.log"
    formatter = logging.Formatter(
        "%(asctime)s %(levelname)s [%(name)s] %(message)s"
    )
    file_handler = RotatingFileHandler(
        log_file_path,
        maxBytes=5 * 1024 * 1024,
        backupCount=5,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)
    logging.basicConfig(level=logging.INFO, handlers=[file_handler, logging.StreamHandler()])


configure_logging()
init_database()

config = get_config()
app = FastAPI(title="精准客户数据挖掘本地系统")
app.add_middleware(
    CORSMiddleware,
    allow_origins=list(config.allowed_origins),
    allow_origin_regex=r"https://([a-zA-Z0-9-]+\.)?(1688|alibaba)\.com",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(router)

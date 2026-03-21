import logging
import os
import sys
from logging.handlers import RotatingFileHandler

import dotenv


def setup_logging():
    dotenv.load_dotenv()

    log_format = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    formatter = logging.Formatter(log_format)

    # Root logger captures everything; handlers filter by level independently.
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.DEBUG)

    # Console handler: always active. In Docker, stdout is captured by the
    # container runtime and shipped to Cloud Logging by the Ops Agent.
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(formatter)
    root_logger.addHandler(console_handler)

    # File handlers: only in local development (no LOG_LEVEL env var).
    # In Docker, LOG_LEVEL is injected via /etc/orc-bot.env, so file handlers
    # are skipped — the container filesystem is ephemeral and stdout suffices.
    if not os.environ.get("LOG_LEVEL"):
        log_dir = "logs"
        if not os.path.exists(log_dir):
            os.makedirs(log_dir)

        info_file_handler = RotatingFileHandler(
            os.path.join(log_dir, "bot.log"),
            maxBytes=5 * 1024 * 1024,  # 5MB
            backupCount=5,
        )
        info_file_handler.setLevel(logging.INFO)
        info_file_handler.setFormatter(formatter)
        root_logger.addHandler(info_file_handler)

        debug_file_handler = RotatingFileHandler(
            os.path.join(log_dir, "bot_debug.log"),
            maxBytes=10 * 1024 * 1024,  # 10MB
            backupCount=3,
        )
        debug_file_handler.setLevel(logging.DEBUG)
        debug_file_handler.setFormatter(formatter)
        root_logger.addHandler(debug_file_handler)

    # Silence noisy third-party libraries.
    logging.getLogger("discord").setLevel(logging.WARNING)
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)

    logging.info("Logging initialized")


def get_logger(name):
    return logging.getLogger(name)

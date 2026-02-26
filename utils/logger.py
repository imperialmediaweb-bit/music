import logging
import sys
from config import OUTPUT_DIR


def setup_logger(name: str = "music_pipeline") -> logging.Logger:
    logger = logging.getLogger(name)
    if logger.handlers:
        return logger

    logger.setLevel(logging.DEBUG)
    formatter = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # Console handler — force UTF-8 to avoid cp1252 errors on Windows.
    # When running under pythonw (no console), sys.stdout is None — skip console handler.
    if sys.stdout is not None:
        try:
            utf8_stdout = open(sys.stdout.fileno(), mode="w", encoding="utf-8", closefd=False)
        except Exception:
            utf8_stdout = sys.stdout
        console = logging.StreamHandler(utf8_stdout)
        console.setLevel(logging.INFO)
        console.setFormatter(formatter)
        logger.addHandler(console)

    # File handler — force UTF-8 encoding
    log_file = OUTPUT_DIR / "pipeline.log"
    file_handler = logging.FileHandler(log_file, encoding="utf-8")
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    return logger


log = setup_logger()

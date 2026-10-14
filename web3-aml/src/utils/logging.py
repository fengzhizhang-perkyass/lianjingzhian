from pathlib import Path
import logging
from .io import ROOT


def get_logger(name: str, root: Path = ROOT):
    logger = logging.getLogger(f"web3_aml.{name}.{root}")
    if not logger.handlers:
        (root / "logs").mkdir(parents=True, exist_ok=True)
        logger.setLevel(logging.INFO)
        logger.propagate = False
        fmt = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
        for handler in (logging.FileHandler(root / "logs" / f"{name}.log", encoding="utf-8"),
                        logging.StreamHandler()):
            handler.setFormatter(fmt)
            logger.addHandler(handler)
    return logger

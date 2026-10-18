import logging

from .odoo import Odoo, OdooConfig
from .server import build_server


def main():
    # httpx logs every request at INFO; keep the server's stderr for real problems
    logging.getLogger("httpx").setLevel(logging.WARNING)
    build_server(Odoo(OdooConfig.from_env())).run()


if __name__ == "__main__":
    main()

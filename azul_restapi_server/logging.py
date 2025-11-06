"""Provide logging."""

import logging
import sys

from loguru import logger

from azul_restapi_server.settings import logging as config


class InterceptHandler(logging.Handler):
    """Default handler from examples in loguru documentation.

    See https://loguru.readthedocs.io/en/stable/overview.html#entirely-compatible-with-standard-logging

    Use to redirect standard logging messages towards loguru sink
    """

    def emit(self, record):
        """Emit a record."""
        if record.name == "uvicorn.access":
            # we already log access using middleware
            # don't log anything from uvicorn.access since its difficult to stop it logging any other way
            # i.e. guvicorn seems to add a handler, which breaks the config option 'access_log'
            return
        # Get corresponding Loguru level if it exists
        try:
            level = logger.level(record.levelname).name
        except ValueError:
            level = record.levelno

        # Find caller from where originated the logged message.
        frame, depth = logging.currentframe(), 0
        while frame and (depth == 0 or frame.f_code.co_filename == logging.__file__):
            frame = frame.f_back
            depth += 1

        logger.opt(depth=depth, exception=record.exc_info).log(level, record.getMessage())


class RestAPILogger:
    """Provide logger for use in REST API."""

    def __init__(self):
        """Init."""
        logger.remove()

        self.logger = logger.bind(feed="log")
        self.audit_logger = logger.bind(feed="audit")

        # log all to stdout
        logger.add(
            sys.stdout,
            enqueue=True,
            backtrace=config.log_backtrace,
            level=config.log_level.upper(),
            format=config.log_format,
            diagnose=False,
        )

        # log file
        if config.log_file:
            logger.add(
                config.log_file,
                rotation=config.log_rotation,
                retention=config.log_retention,
                enqueue=True,
                backtrace=config.log_backtrace,
                level=config.log_level.upper(),
                format=config.log_format,
                filter=lambda record: record["extra"].get("feed") == "log",
                diagnose=False,
            )

        # audit file
        if config.audit_file:
            logger.add(
                config.audit_file,
                rotation=config.audit_rotation,
                retention=config.audit_retention,
                enqueue=True,
                level="INFO",
                format="{message}",
                filter=lambda record: record["extra"].get("feed") == "audit",
                diagnose=False,
            )

        # redirect logging to loguru sink
        # eg: 'uvicorn', 'uvicorn.error', 'uvicorn.access', 'fastapi',
        handler = InterceptHandler()
        logging.basicConfig(handlers=[handler], level=0)
        for name in logging.root.manager.loggerDict:
            logging.getLogger(name).handlers = [handler]

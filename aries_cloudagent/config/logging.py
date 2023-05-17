"""Utilities related to logging."""

import sys
import logging
from io import TextIOWrapper
from logging.config import fileConfig
from typing import TextIO

import pkg_resources

from ..core.profile import Profile
from ..version import __version__

from .banner import Banner
from .base import BaseSettings


DEFAULT_LOGGING_CONFIG_PATH = "aries_cloudagent.config:default_logging_config.ini"
LOG_FORMAT_FILE_ALIAS = logging.Formatter(
    "%(asctime)s [%(logger_alias)s] %(levelname)s %(filename)s %(lineno)d %(message)s"
)
LOG_FORMAT_FILE_NO_ALIAS = logging.Formatter(
    "%(asctime)s %(levelname)s %(filename)s %(lineno)d %(message)s"
)
LOG_FORMAT_STREAM = logging.Formatter(
    "%(asctime)s %(levelname)s %(filename)s %(lineno)d %(message)s"
)


def clear_prev_handlers(logger: logging.Logger) -> logging.Logger:
    """Remove all handler classes associated with logger instance."""
    iter_count = 0
    num_handlers = len(logger.handlers)
    while iter_count < num_handlers:
        logger.removeHandler(logger.handlers[0])
        iter_count = iter_count + 1
    return logger


def get_logger_inst(profile: Profile, logger_name) -> logging.Logger:
    """Return a logger instance with provided name and handlers."""
    logger = None
    if profile.settings.get("log.alias"):
        logger = get_logger_with_handlers(
            settings=profile.settings,
            logger=logging.getLogger(f"{logger_name}_{profile.settings['log.alias']}"),
        )
    else:
        logger = get_logger_with_handlers(
            settings=profile.settings, logger=logging.getLogger(logger_name)
        )
    return logger


def get_logger_with_handlers(
    settings: BaseSettings, logger: logging.Logger
) -> logging.Logger:
    """Return logger instance with necessary handlers if required."""
    if settings.get("log.file"):
        # Clear handlers set previously for this logger instance
        logger = clear_prev_handlers(logger)
        # log file handler
        file_path = settings.get("log.file")
        logger_alias = settings.get("log.alias")
        file_handler = logging.FileHandler(file_path)
        if logger_alias:
            file_handler.setFormatter(LOG_FORMAT_FILE_ALIAS)
        else:
            file_handler.setFormatter(LOG_FORMAT_FILE_NO_ALIAS)
        logger.addHandler(file_handler)
        # stream console handler
        std_out_handler = logging.StreamHandler(sys.stdout)
        std_out_handler.setFormatter(LOG_FORMAT_STREAM)
        logger.addHandler(std_out_handler)
        if logger_alias:
            logger = logging.LoggerAdapter(logger, {"logger_alias": logger_alias})
        # set log level
        logger_level = (
            (settings.get("log.level")).upper()
            if settings.get("log.level")
            else logging.INFO
        )
        logger.setLevel(logger_level)
    return logger


def load_resource(path: str, encoding: str = None) -> TextIO:
    """
    Open a resource file located in a python package or the local filesystem.

    Args:
        path: The resource path in the form of `dir/file` or `package:dir/file`
    Returns:
        A file-like object representing the resource
    """
    components = path.rsplit(":", 1)
    try:
        if len(components) == 1:
            return open(components[0], encoding=encoding)
        else:
            bstream = pkg_resources.resource_stream(components[0], components[1])
            if encoding:
                return TextIOWrapper(bstream, encoding=encoding)
            return bstream
    except IOError:
        pass


class LoggingConfigurator:
    """Utility class used to configure logging and print an informative start banner."""

    @classmethod
    def configure(
        cls,
        logging_config_path: str = None,
        log_level: str = None,
        log_file: str = None,
    ):
        """
        Configure logger.

        :param logging_config_path: str: (Default value = None) Optional path to
            custom logging config

        :param log_level: str: (Default value = None)
        """
        if logging_config_path is not None:
            config_path = logging_config_path
        else:
            config_path = DEFAULT_LOGGING_CONFIG_PATH

        log_config = load_resource(config_path, "utf-8")
        if log_config:
            with log_config:
                fileConfig(log_config, disable_existing_loggers=False)
        else:
            logging.basicConfig(level=logging.WARNING)
            logging.root.warning(f"Logging config file not found: {config_path}")

        if log_file:
            logging.root.handlers.clear()
            logging.root.handlers.append(
                logging.FileHandler(log_file, encoding="utf-8")
            )

        if log_level:
            log_level = log_level.upper()
            logging.root.setLevel(log_level)

    @classmethod
    def print_banner(
        cls,
        agent_label,
        inbound_transports,
        outbound_transports,
        public_did,
        admin_server=None,
        banner_length=40,
        border_character=":",
    ):
        """
        Print a startup banner describing the configuration.

        Args:
            agent_label: Agent Label
            inbound_transports: Configured inbound transports
            outbound_transports: Configured outbound transports
            admin_server: Admin server info
            public_did: Public DID
            banner_length: (Default value = 40) Length of the banner
            border_character: (Default value = ":") Character to use in banner
            border
        """
        print()
        banner = Banner(border=border_character, length=banner_length)
        banner.print_border()

        # Title
        banner.print_title(agent_label or "ACA")

        banner.print_spacer()
        banner.print_spacer()

        # Inbound transports
        banner.print_subtitle("Inbound Transports")
        internal_in_transports = [
            f"{transport.scheme}://{transport.host}:{transport.port}"
            for transport in inbound_transports.values()
            if not transport.is_external
        ]
        if internal_in_transports:
            banner.print_spacer()
            banner.print_list(internal_in_transports)
            banner.print_spacer()
        external_in_transports = [
            f"{transport.scheme}://{transport.host}:{transport.port}"
            for transport in inbound_transports.values()
            if transport.is_external
        ]
        if external_in_transports:
            banner.print_spacer()
            banner.print_subtitle("  External Plugin")
            banner.print_spacer()
            banner.print_list(external_in_transports)
            banner.print_spacer()

        # Outbound transports
        banner.print_subtitle("Outbound Transports")
        internal_schemes = set().union(
            *(
                transport.schemes
                for transport in outbound_transports.values()
                if not transport.is_external
            )
        )
        if internal_schemes:
            banner.print_spacer()
            banner.print_list([f"{scheme}" for scheme in sorted(internal_schemes)])
            banner.print_spacer()

        external_schemes = set().union(
            *(
                transport.schemes
                for transport in outbound_transports.values()
                if transport.is_external
            )
        )
        if external_schemes:
            banner.print_spacer()
            banner.print_subtitle("  External Plugin")
            banner.print_spacer()
            banner.print_list([f"{scheme}" for scheme in sorted(external_schemes)])
            banner.print_spacer()

        # DID info
        if public_did:
            banner.print_subtitle("Public DID Information")
            banner.print_spacer()
            banner.print_list([f"DID: {public_did}"])
            banner.print_spacer()

        # Admin server info
        banner.print_subtitle("Administration API")
        banner.print_spacer()
        banner.print_list(
            [f"http://{admin_server.host}:{admin_server.port}"]
            if admin_server
            else ["not enabled"]
        )
        banner.print_spacer()

        banner.print_version(__version__)

        banner.print_border()
        print()
        print("Listening...")
        print()

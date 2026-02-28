"""Central logging utilities for the rhizome namespace."""

import logging

NAMESPACE = "rhizome"


def get_logger(name: str) -> logging.Logger:
    """Return a logger under the 'rhizome.' namespace."""
    return logging.getLogger(f"{NAMESPACE}.{name}")


def initialize_global_logger(handler: logging.Handler) -> None:
    """Attach a handler to the root 'rhizome' logger."""
    root = logging.getLogger(NAMESPACE)
    root.setLevel(logging.DEBUG)
    root.addHandler(handler)

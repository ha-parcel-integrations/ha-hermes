"""Compatibility imports for the tracking-code source.

New code imports from :mod:`hermes.tracking.api`; this module preserves the
pre-split public import path for custom automations and older tests.
"""
from .tracking.api import HermesApiClient, HermesApiError

__all__ = ["HermesApiClient", "HermesApiError"]

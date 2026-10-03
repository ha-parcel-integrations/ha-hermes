"""Compatibility module for the tracking-code normaliser."""
from .tracking import parcels as _tracking

globals().update(vars(_tracking))

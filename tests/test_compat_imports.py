"""The pre-split import paths must keep resolving.

`api.py`, `coordinator.py` and `parcels.py` at package root became re-export
shims when the tracking source moved into `tracking/`. Nothing else in the
tests imports them, so only a test notices if a rename quietly breaks an
external import.
"""
from custom_components.hermes import api, coordinator, parcels
from custom_components.hermes.tracking import api as tracking_api
from custom_components.hermes.tracking import coordinator as tracking_coordinator
from custom_components.hermes.tracking import parcels as tracking_parcels


def test_root_coordinator_module_re_exports_the_tracking_coordinator():
    assert coordinator.HermesCoordinator is tracking_coordinator.HermesCoordinator


def test_root_api_module_re_exports_the_tracking_client():
    assert api.HermesApiClient is tracking_api.HermesApiClient
    assert api.HermesApiError is tracking_api.HermesApiError


def test_root_parcels_module_re_exports_the_tracking_normaliser():
    assert parcels.normalize_parcel is tracking_parcels.normalize_parcel
    assert parcels._STATUS_MAP is tracking_parcels._STATUS_MAP

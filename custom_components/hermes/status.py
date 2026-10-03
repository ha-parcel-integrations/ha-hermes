"""Hermes' two status vocabularies, kept apart on purpose.

The keyless tracking route reports a stable English enum and the account route
a German one — both under the field name ``parcelStatus``. They are different
vocabularies, so each source has its own map and neither may reach for the
other's. Do not merge them.
"""
from __future__ import annotations

from .const import ParcelStatus

# Where users report a status we do not map yet. Rewritten by the bootstrap
# script; it must point at the carrier's own repo so the log line is
# copy-pasteable straight into a new issue.
#
# The ``?template=`` parameter matters: without it the link opens a blank form,
# and the report comes back missing the version and the log line we need.
NEW_ISSUE_URL = (
    "https://github.com/ha-parcel-integrations/ha-hermes/issues/new"
    "?template=unrecognised_status.yml"
)

# Keyless route: Hermes ``parcelStatus`` (the stable English enum on each ``parcelProgress``
# event) → canonical ParcelStatus. Seeded from the values mapped in
# ``itsvic-dev/deliveries`` (HermesDeliveryService.kt) plus the pickup family
# from the app decompile; extend it as real parcels surface more. An unmapped
# value surfaces as ``unknown`` plus a one-shot warning that asks the user to
# report it — do not map the localised ``status`` / ``historyText`` here, only
# the stable ``parcelStatus`` code.
TRACKING_STATUS_MAP: dict[str, ParcelStatus] = {
    "ANNOUNCED": ParcelStatus.REGISTERED,
    "ORDER_INFO_RECEIVED": ParcelStatus.REGISTERED,
    "PREANNOUNCED": ParcelStatus.REGISTERED,
    "PARCELSHOP_DROP_OFF": ParcelStatus.REGISTERED,
    "SHIPMENT_PICKED_UP": ParcelStatus.IN_TRANSIT,
    "TAKEN_OVER_BY_HERMES": ParcelStatus.IN_TRANSIT,
    "HANDED_OVER_TO_HERMES": ParcelStatus.IN_TRANSIT,
    "PARCELSHOP_COLLECTED_BY_DRIVER": ParcelStatus.IN_TRANSIT,
    "IN_TRANSIT": ParcelStatus.IN_TRANSIT,
    "SORTED": ParcelStatus.IN_TRANSIT,
    "ARRIVED_AT_DEPOT": ParcelStatus.IN_TRANSIT,
    "ARRIVED_AT_DELIVERY_DEPOT": ParcelStatus.IN_TRANSIT,
    "ARRIVED_IN_DESTINATION_REGION": ParcelStatus.IN_TRANSIT,
    "DELIVERY_TOUR_STARTED": ParcelStatus.OUT_FOR_DELIVERY,
    "OUT_FOR_DELIVERY": ParcelStatus.OUT_FOR_DELIVERY,
    "NEXT_STOP": ParcelStatus.OUT_FOR_DELIVERY,
    "DELIVERED_HOMEDELIVERY": ParcelStatus.DELIVERED,
    "DELIVERED_NEIGHBOUR": ParcelStatus.DELIVERED,
    "DELIVERED_PARCELSHOP": ParcelStatus.DELIVERED,
    "DELIVERED_PARCELBOX": ParcelStatus.DELIVERED,
    "DELIVERED_MAILBOX": ParcelStatus.DELIVERED,
    "DELIVERED_DROPOFF": ParcelStatus.DELIVERED,
    "DELIVERED": ParcelStatus.DELIVERED,
    "PICKED_UP_BY_RECIPIENT": ParcelStatus.DELIVERED,
    "COLLECTED": ParcelStatus.DELIVERED,
    "PARCELSHOP_ITEMS_FOR_COLLECTION": ParcelStatus.AT_PICKUP_POINT,
    "READY_FOR_COLLECTION": ParcelStatus.AT_PICKUP_POINT,
    "RETURN_DELIVERED_TO_SENDER": ParcelStatus.RETURNING,
    "RETURN_TO_SENDER": ParcelStatus.RETURNING,
    "RETURN": ParcelStatus.RETURNING,
    "NOT_DELIVERABLE": ParcelStatus.PROBLEM,
    "UNKNOWN_WHEREABOUTS": ParcelStatus.PROBLEM,
}

# ``EDL_BOOKED_DROPOFF`` ("Wunschablageort gebucht") is deliberately left
# unmapped: it is a delivery-preference booking, not a location movement, and
# real evidence (ha-hermes#1) shows it firing *before* Hermes even collects
# the parcel — mapping it to any single ParcelStatus risks regressing the
# status backwards on a parcel where the same event fires later in transit.
# It falls through to the unmapped-code warning like any other new code.

# Account route: the German ``status.parcelStatus`` / ``parcelHistory[].status``
# vocabulary → canonical ParcelStatus. The ``EDL_*``, ``HBX_*``, ``TAN_*`` and
# ``INVALID_*`` families are deliberately absent: they are app-feature state
# (booked delivery preferences, parcel-box hops, pickup-PIN failures, form
# validation), not parcel progress. They fall through to ``unknown`` with the
# one-shot unmapped-status warning.
ACCOUNT_STATUS_MAP: dict[str, ParcelStatus] = {
    "ANNOUNCED": ParcelStatus.REGISTERED,
    "AVISE": ParcelStatus.REGISTERED,
    "SENDUNG_VON_HERMES_UEBERNOMMEN": ParcelStatus.IN_TRANSIT,
    "UNTERWEGS": ParcelStatus.IN_TRANSIT,
    "UNTERWEGS_ZU_HERMES": ParcelStatus.IN_TRANSIT,
    "UMSCHLAG_INLAND": ParcelStatus.IN_TRANSIT,
    "UMSCHLAG_AUSLAND": ParcelStatus.IN_TRANSIT,
    "SENDUNG_IN_ZIELREGION_ANGEKOMMEN": ParcelStatus.IN_TRANSIT,
    "AN_INSELSPEDITEUR_UEBERGEBEN": ParcelStatus.IN_TRANSIT,
    "AM_PKS_ABGEGEBEN": ParcelStatus.IN_TRANSIT,
    "ABGEHOLT_AN_FAHRER_UEBERGEBEN": ParcelStatus.IN_TRANSIT,
    "PAKETSHOP_AN_FAHRER_UEBERGEBEN": ParcelStatus.IN_TRANSIT,
    "ZUSTELLTOUR": ParcelStatus.OUT_FOR_DELIVERY,
    "ZUSTELLTOUR_VERSPAETET": ParcelStatus.OUT_FOR_DELIVERY,
    "ZUSTELLTOUR_STARK_VERSPAETET": ParcelStatus.OUT_FOR_DELIVERY,
    "PAKETSHOP": ParcelStatus.AT_PICKUP_POINT,
    "WUNSCHPAKETSHOP": ParcelStatus.AT_PICKUP_POINT,
    "READY_FOR_COLLECTION_SINCE": ParcelStatus.AT_PICKUP_POINT,
    "LAGERND": ParcelStatus.AT_PICKUP_POINT,
    "LAGERND_TERMIN": ParcelStatus.AT_PICKUP_POINT,
    "LAGERND_MEHRCOLLIG": ParcelStatus.AT_PICKUP_POINT,
    "ZUGESTELLT": ParcelStatus.DELIVERED,
    "ZUGESTELLT_BRIEFKASTEN": ParcelStatus.DELIVERED,
    # "Zugestellt" here means handed to the shop, not to you: a real parcel
    # carried it with the text "Die Sendung ist abholbereit" and only reached
    # VOM_PAKETSHOP_ABGEHOLT two hours later. Reporting it as delivered would
    # tell someone a parcel is home while it waits on a shop counter.
    "ZUGESTELLT_PAKETSHOP": ParcelStatus.AT_PICKUP_POINT,
    # Seen live 2026-10-03, and absent from every list the app itself carries:
    # the account backend returns values the app does not enumerate, so this map
    # can only ever grow from real parcels. Map each one explicitly — a
    # substring rule on "ZUGESTELLT" would also swallow a future negated form
    # and report an undelivered parcel as delivered.
    "INT_ZUGESTELLT_ABLAGEORT": ParcelStatus.DELIVERED,
    "VOM_PAKETSHOP_ABGEHOLT": ParcelStatus.DELIVERED,
    "RETOURE_AUSLIEFERUNG_ZUM_ATG": ParcelStatus.RETURNING,
    "RETOURE_AUSLIEFERUNG_ZUM_ATG_NACH_SCHADEN": ParcelStatus.RETURNING,
    "RETOURE_AUSGELIEFERT_BEIM_ATG": ParcelStatus.RETURNING,
    "RETOURE_AUSGELIEFERT_BEIM_ATG_NACH_SCHADEN": ParcelStatus.RETURNING,
    "RUECKVERSAND_RETOURE": ParcelStatus.RETURNING,
    "RUECKVERSAND_DURCH_ATG": ParcelStatus.RETURNING,
    "RUECKVERSAND_SCHADENFALL": ParcelStatus.RETURNING,
    "RUECKVERSAND_NICHT_AM_PKS_ABGEHOLT": ParcelStatus.RETURNING,
    "NICHT_ZUSTELLBAR_RUECKVERSAND": ParcelStatus.RETURNING,
    "NICHT_ZUSTELLBAR_ADRESSFEHLER": ParcelStatus.PROBLEM,
    "NICHT_ZUSTELLBAR_ERNEUTER_VERSUCH": ParcelStatus.PROBLEM,
    "NICHT_ANGETROFFEN_1": ParcelStatus.PROBLEM,
    "NICHT_ANGETROFFEN_2": ParcelStatus.PROBLEM,
    "NICHT_ANGETROFFEN_3": ParcelStatus.PROBLEM,
    "NICHT_ANGETROFFEN_4": ParcelStatus.PROBLEM,
    "UNKLARER_SENDUNGSVERBLEIB": ParcelStatus.PROBLEM,
    "PRUEFUNG_AUF_BESCHAEDIGUNG": ParcelStatus.PROBLEM,
    "ABHOLUNG_STORNIERT": ParcelStatus.PROBLEM,
    "STORNIERTE_ONLINEBEZAHLUNG": ParcelStatus.PROBLEM,
    "HBX_STORAGETIME_EXPIRED": ParcelStatus.PROBLEM,
    "NICHT_ANGEZEIGT": ParcelStatus.UNKNOWN,
}

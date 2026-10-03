"""Sample Hermes account ``GET /shipments`` payloads shared by the account tests.

Built from a scrubbed real response (two elements: one full, one thin). The
receiver, delivery-partner and destination fields are blank and the barcodes are
placeholders; keep it that way — no personal data in fixtures, ever.
"""
from __future__ import annotations

import copy

BARCODE = "00000000000000"
THIN_BARCODE = "00000000000000000000"
IN_FLIGHT_BARCODE = "00000000000001"

_DELIVERED = {'address': {'addressType': 'HOMEDELIVERY',
             'closed': False,
             'country': 'DEU',
             'ersatzAdresse': False,
             'firstName': '',
             'hasParcelboxInformation': False},
 'atg': {'companyName': ''},
 'barcode': '00000000000000',
 'relatedShipments': [{'barcode': '00000000000000',
                       'timestamp': '2026-09-14T01:34:39.261Z'}],
 'bookedEdl': {'bookedPermanently': False,
               'bookingTimestamp': '2026-09-15T14:07:13.372Z',
               'deliveryDate': '2026-09-19',
               'deliveryType': 'WUNSCHTAG'},
 'content': [],
 'forecast': {'deliveryDateBooked': False, 'showForecast': False},
 'metaInformation': {'addressValid': True,
                     'collection': False,
                     'collectionCanceled': False,
                     'csChatFrom': 0,
                     'csChatTo': 0,
                     'delivered': True,
                     'destination': '',
                     'directionKey': '62',
                     'parcelCategory': 'PARCEL',
                     'parcelShopBookable': False,
                     'pk': False,
                     'retoure': False,
                     'showEmailNotification': False,
                     'showZipCodeValidation': True,
                     'warrantForbidden': False,
                     'onlinePaymentCanceled': False,
                     'showHBXPickupPin': False,
                     'tanRequired': False,
                     'zipCodeFormat': 'FIVE_DIGITS'},
 'parcelHistory': [{'nextStatus': False,
                    'status': 'AVISE',
                    'statusHistoryShortText': 'Sendung angekündigt',
                    'statusHistoryText': 'Die Sendung wurde angekündigt',
                    'statusIndex': 0,
                    'timestamp': '2026-09-14T01:34:39.176Z'},
                   {'nextStatus': False,
                    'status': 'SENDUNG_VON_HERMES_UEBERNOMMEN',
                    'statusHistoryShortText': 'Sendung übernommen',
                    'statusHistoryText': 'Die Sendung wurde von Hermes in <ORT> '
                                         'übernommen',
                    'statusIndex': 1,
                    'timestamp': '2026-09-15T13:37:04.000Z'},
                   {'nextStatus': False,
                    'status': 'SENDUNG_IN_ZIELREGION_ANGEKOMMEN',
                    'statusHistoryShortText': 'In Zielregion <ORT>',
                    'statusHistoryText': 'In Zielregion <ORT>',
                    'statusIndex': 2,
                    'timestamp': '2026-09-16T05:40:38.130Z'},
                   {'nextStatus': False,
                    'status': 'UMSCHLAG_INLAND',
                    'statusHistoryShortText': 'Sortiert',
                    'statusHistoryText': 'Die Sendung wurde in <ORT> sortiert und '
                                         'weiterversandt',
                    'statusIndex': 3,
                    'timestamp': '2026-09-16T05:40:38.131Z'},
                   {'nextStatus': False,
                    'status': 'UMSCHLAG_INLAND',
                    'statusHistoryShortText': 'Sortiert',
                    'statusHistoryText': 'Die Sendung wurde in <ORT> sortiert und '
                                         'weiterversandt',
                    'statusIndex': 4,
                    'timestamp': '2026-09-19T04:53:41.366Z'},
                   {'nextStatus': False,
                    'status': 'ZUSTELLTOUR',
                    'statusHistoryShortText': 'In Zustellung',
                    'statusHistoryText': 'Die Sendung befindet sich in Zustellung',
                    'statusIndex': 5,
                    'timestamp': '2026-09-21T07:04:40.550Z'},
                   {'nextStatus': False,
                    'status': 'ZUGESTELLT',
                    'statusHistoryShortText': 'Zugestellt',
                    'statusHistoryText': 'Die Sendung wurde zugestellt',
                    'statusIndex': 6,
                    'timestamp': '2026-09-21T08:11:18.895Z'}],
 'status': {'deliveryTime': '2026-09-21T08:11:18.895Z',
            'failedDeliveryTries': 0,
            'parcelStatus': 'ZUGESTELLT',
            'statusImage': '24_zugestellt_allgemein_d',
            'text': {'language': 'de',
                     'longText': 'Deine Sendung wurde an deiner Haustür zugestellt. '
                                 'Viel Spaß damit!',
                     'shortText': 'Zugestellt'},
            'timestamp': '2026-09-21T08:11:18.895Z'},
 'infoTexts': [],
 'shipmentType': 'IN_MANUALLY',
 'externalId': 'EXTERNAL-ID-REDACTED'}

_THIN = {'barcode': '00000000000000000000',
 'shipmentType': 'IN_UNKNOWN',
 'externalId': 'EXTERNAL-ID-REDACTED',
 'lastModified': '2025-12-28T01:00:00.000+01:00'}


def delivered_shipment() -> dict:
    """A full ``IN_MANUALLY`` element, delivered; history is oldest-first."""
    return copy.deepcopy(_DELIVERED)


def thin_shipment() -> dict:
    """A thin ``IN_UNKNOWN`` element: no ``status`` block, no history, no meta."""
    return copy.deepcopy(_THIN)


def in_flight_shipment(
    parcel_status: str = "ZUSTELLTOUR", barcode: str = IN_FLIGHT_BARCODE
) -> dict:
    """The full element cut back to a parcel that is still on its way.

    The history is trimmed to the events up to ``parcel_status`` so that the
    current status is deliberately *not* the first history entry.
    """
    shipment = copy.deepcopy(_DELIVERED)
    shipment["barcode"] = barcode
    shipment["metaInformation"]["delivered"] = False
    shipment["parcelHistory"] = shipment["parcelHistory"][:6]
    shipment["status"] = {
        "failedDeliveryTries": 0,
        "parcelStatus": parcel_status,
        "statusImage": "09_auf_zustelltour",
        "text": {
            "language": "de",
            "longText": "Deine Sendung ist auf Zustelltour.",
            "shortText": "In Zustellung",
        },
        "timestamp": "2026-09-21T07:04:40.550Z",
    }
    return shipment

import json
import logging

from tollroute import logging as logging_mod


def test_json_formatter_renders_one_json_object_with_merged_fields():
    formatter = logging_mod.JSONFormatter()
    record = logging.LogRecord(
        name="tollroute.route", level=logging.INFO, pathname=__file__, lineno=1,
        msg="route computed", args=(), exc_info=None,
    )
    record.fields = {"gates": [1, 2, 3], "toll_eur": 4.5}

    line = formatter.format(record)
    payload = json.loads(line)

    assert payload["level"] == "INFO"
    assert payload["logger"] == "tollroute.route"
    assert payload["message"] == "route computed"
    assert payload["gates"] == [1, 2, 3]
    assert payload["toll_eur"] == 4.5


def test_json_formatter_handles_records_with_no_fields():
    formatter = logging_mod.JSONFormatter()
    record = logging.LogRecord(
        name="tollroute.route", level=logging.WARNING, pathname=__file__, lineno=1,
        msg="plain message", args=(), exc_info=None,
    )

    payload = json.loads(formatter.format(record))

    assert payload == {"level": "WARNING", "logger": "tollroute.route", "message": "plain message"}


def test_configure_logging_is_idempotent():
    root = logging.getLogger()

    logging_mod.configure_logging()
    logging_mod.configure_logging()
    logging_mod.configure_logging()

    json_handlers = [h for h in root.handlers if isinstance(h.formatter, logging_mod.JSONFormatter)]
    assert len(json_handlers) == 1


def test_log_route_response_includes_full_gate_chain_for_every_option(caplog):
    result = {
        "vot_eur_per_hour": 20.0,
        "options": [
            {"route_id": "abc123", "labels": ["fastest"], "gates": [111, 222],
             "toll_eur": 8.4, "duration_s": 5000.0, "distance_m": 190000.0},
            {"route_id": "def456", "labels": ["cheapest"], "gates": [333],
             "toll_eur": 0.0, "duration_s": 6000.0, "distance_m": 205000.0},
        ],
    }

    with caplog.at_level(logging.INFO, logger=logging_mod.ROUTE_LOGGER_NAME):
        logging_mod.log_route_response((47.0, 5.0), (45.7, 4.8), 1, result)

    [record] = caplog.records
    assert record.fields["vehicle_class"] == 1
    assert record.fields["vot_eur_per_hour"] == 20.0
    assert record.fields["origin"] == {"lat": 47.0, "lon": 5.0}
    assert [o["gates"] for o in record.fields["options"]] == [[111, 222], [333]]
    assert [o["route_id"] for o in record.fields["options"]] == ["abc123", "def456"]

"""Structured logging (Phase 6a).

A JSON-lines formatter plus one helper that logs a `/route` response's full
gate chain per option. The exit criterion ("a single request log contains
the full gate chain") needs every option's gate chain, toll and labels
queryable from one log line for "why this route" debugging, not scattered
across separate unstructured messages a human has to stitch back together.
"""

from __future__ import annotations

import json
import logging

ROUTE_LOGGER_NAME = "tollroute.route"

route_logger = logging.getLogger(ROUTE_LOGGER_NAME)


class JSONFormatter(logging.Formatter):
    """Renders each record as one JSON object per line, merging in structured
    fields passed via ``logger.info(msg, extra={"fields": {...}})`` rather
    than interpolating them into the message string, so the gate chain stays
    machine-parseable instead of embedded in free text."""

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        fields = getattr(record, "fields", None)
        if fields:
            payload.update(fields)
        return json.dumps(payload, default=str)


def configure_logging(level: int = logging.INFO) -> None:
    """Attach a JSON-formatted stream handler to the root logger, idempotently
    - safe to call more than once (app startup, tests importing this module)
    without stacking duplicate handlers."""
    root = logging.getLogger()
    if any(isinstance(h.formatter, JSONFormatter) for h in root.handlers):
        return
    handler = logging.StreamHandler()
    handler.setFormatter(JSONFormatter())
    root.addHandler(handler)
    root.setLevel(level)


def log_route_response(
    origin: tuple[float, float],
    destination: tuple[float, float],
    vehicle_class: int,
    result: dict,
) -> None:
    """Log the full gate chain for every option in a `/route` response as one
    structured record - the exit criterion ("a single request log contains
    the full gate chain") needs the whole option set, not just the winning
    one, since "why this route" debugging usually means "why not that one"."""
    route_logger.info(
        "route computed",
        extra={
            "fields": {
                "origin": {"lat": origin[0], "lon": origin[1]},
                "destination": {"lat": destination[0], "lon": destination[1]},
                "vehicle_class": vehicle_class,
                "vot_eur_per_hour": result.get("vot_eur_per_hour"),
                "options": [
                    {
                        "route_id": option.get("route_id"),
                        "labels": option["labels"],
                        "gates": option["gates"],
                        "toll_eur": option["toll_eur"],
                        "duration_s": option["duration_s"],
                        "distance_m": option["distance_m"],
                    }
                    for option in result.get("options", [])
                ],
            }
        },
    )

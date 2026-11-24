"""One published schema for runtime and offline contract checks, never data approval."""

import json
from pathlib import Path
from jsonschema import Draft202012Validator, FormatChecker, ValidationError

# Static, checked-in contract only. No market-data cache or runtime schema override.
SCHEMA = json.loads(
    (
        Path(__file__).resolve().parents[2]
        / "config/market-intelligence-v3.schema.json"
    ).read_text()
)
Draft202012Validator.check_schema(SCHEMA)
VALIDATOR = Draft202012Validator(SCHEMA, format_checker=FormatChecker())
SESSION_VALIDATOR = Draft202012Validator(
    {"$defs": SCHEMA["$defs"], "$ref": "#/$defs/Session"},
    format_checker=FormatChecker(),
)


def validate_shape(value, *, session=False):
    try:
        (SESSION_VALIDATOR if session else VALIDATOR).validate(value)
    except (ValidationError, TypeError, RecursionError) as exc:
        # Do not echo evidence content through a validator exception.
        raise ValueError("MARKET_VIEW_SCHEMA_INVALID") from None

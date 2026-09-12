"""Validate build configuration without printing credentials or input contents."""
import json
import re
import sys


def validate(value):
    if not isinstance(value, dict):
        raise ValueError()
    if set(value) != {"host", "port", "secure", "user", "password", "from"}:
        raise ValueError()
    if not isinstance(value["host"], str) or not re.fullmatch(r"[a-zA-Z0-9.-]{1,253}", value["host"]):
        raise ValueError()
    if type(value["port"]) is not int or not 1 <= value["port"] <= 65535:
        raise ValueError()
    if type(value["secure"]) is not bool:
        raise ValueError()
    for field, limit in (("user", 320), ("password", 2048), ("from", 254)):
        if not isinstance(value[field], str) or len(value[field]) > limit:
            raise ValueError()
    if not re.fullmatch(r"[^\s@<>]+@[^\s@<>]+\.[^\s@<>]+", value["from"]):
        raise ValueError()


if __name__ == "__main__":
    try:
        with open(sys.argv[1], encoding="utf-8") as source:
            validate(json.load(source))
    except (OSError, ValueError, IndexError):
        sys.exit("Invalid SMTP configuration; check the example schema (details suppressed).")

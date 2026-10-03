"""Separate bounded JSON decoder for one eFax image, without outbound cap changes."""

import json

from cosmas_os.ports.efax_inbound import MAX_IMAGE_BYTES, Failure


def parse_image_json(raw: bytes) -> dict:
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError
            result[key] = value
        return result

    def invalid(_):
        raise ValueError

    try:
        if type(raw) is not bytes or len(raw) > MAX_IMAGE_BYTES:
            raise ValueError
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=unique, parse_constant=invalid)
        if type(value) is not dict:
            raise ValueError
        return value
    except (ValueError, UnicodeError, TypeError, RecursionError):
        raise Failure("response_invalid") from None

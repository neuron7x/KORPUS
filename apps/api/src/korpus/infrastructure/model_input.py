"""Resource ceiling applied before model material crosses an egress boundary."""

MAX_MODEL_INPUT_BYTES = 65_536


def bounded_model_input(value: str) -> str:
    if len(value.encode("utf-8")) > MAX_MODEL_INPUT_BYTES:
        raise ValueError(f"model input exceeds {MAX_MODEL_INPUT_BYTES} UTF-8 bytes")
    return value

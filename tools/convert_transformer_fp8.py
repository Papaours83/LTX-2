"""Pre-convert an LTX transformer checkpoint to FP8 for ``--quantization fp8-cast``.

fp8-cast downcasts the large transformer-block Linears (to_q/k/v, to_out.0, ff.net.*) to
float8_e4m3fn every time the model loads. Doing it once on disk gives a checkpoint about half
the size with identical weights at inference (fp8-cast then loads these tensors as a no-op),
which halves disk reads with ``--offload disk``.

Tensors are converted and written one at a time, so RAM use stays low.

Usage:
    python tools/convert_transformer_fp8.py INPUT.safetensors OUTPUT.safetensors
"""

import argparse
import json
import struct
from pathlib import Path

import torch
from tqdm import tqdm

from ltx_core.quantization.fp8_cast import _FP8_CAST_KEY_PREFIX, _is_fp8_cast_linear

DTYPES = {
    "F64": torch.float64,
    "F32": torch.float32,
    "F16": torch.float16,
    "BF16": torch.bfloat16,
    "F8_E4M3": torch.float8_e4m3fn,
    "F8_E5M2": torch.float8_e5m2,
    "I64": torch.int64,
    "I32": torch.int32,
    "I16": torch.int16,
    "I8": torch.int8,
    "U8": torch.uint8,
    "BOOL": torch.bool,
}


def should_downcast(key: str) -> bool:
    """Same rule as fp8_cast's TRANSFORMER_LINEAR_DOWNCAST_MAP (weights and biases)."""
    module, _, param = key.rpartition(".")
    if param not in ("weight", "bias") or _FP8_CAST_KEY_PREFIX not in module:
        return False
    return _is_fp8_cast_linear(module)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("input", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()

    with open(args.input, "rb") as src:
        header_len = struct.unpack("<Q", src.read(8))[0]
        header = json.loads(src.read(header_len))
        data_start = 8 + header_len

        metadata = header.pop("__metadata__", None)
        out_header: dict = {} if metadata is None else {"__metadata__": metadata}
        plan = []  # (key, src_offsets, convert)
        offset = 0
        for key, entry in sorted(header.items(), key=lambda kv: kv[1]["data_offsets"][0]):
            convert = should_downcast(key) and entry["dtype"] in ("BF16", "F16", "F32")
            numel = 1
            for dim in entry["shape"]:
                numel *= dim
            dtype = "F8_E4M3" if convert else entry["dtype"]
            nbytes = numel * DTYPES[dtype].itemsize if convert else entry["data_offsets"][1] - entry["data_offsets"][0]
            out_header[key] = {"dtype": dtype, "shape": entry["shape"], "data_offsets": [offset, offset + nbytes]}
            plan.append((key, entry, convert))
            offset += nbytes

        header_bytes = json.dumps(out_header, separators=(",", ":")).encode()
        header_bytes += b" " * (-len(header_bytes) % 8)  # safetensors aligns the data section to 8 bytes

        tmp = args.output.with_suffix(args.output.suffix + ".part")
        converted = 0
        with open(tmp, "wb") as dst:
            dst.write(struct.pack("<Q", len(header_bytes)))
            dst.write(header_bytes)
            for key, entry, convert in tqdm(plan, desc="Conversion", unit="tensor"):
                start, end = entry["data_offsets"]
                src.seek(data_start + start)
                raw = src.read(end - start)
                if convert:
                    t = torch.frombuffer(bytearray(raw), dtype=DTYPES[entry["dtype"]]).reshape(entry["shape"])
                    raw = t.to(torch.float8_e4m3fn).contiguous().view(torch.uint8).numpy().tobytes()
                    converted += 1
                if len(raw) != out_header[key]["data_offsets"][1] - out_header[key]["data_offsets"][0]:
                    raise RuntimeError(f"Size mismatch for {key}")
                dst.write(raw)
        tmp.replace(args.output)

    print(  # noqa: T201 - CLI output
        f"{converted} tensors converted to FP8. "
        f"{args.input.stat().st_size / 1e9:.1f} GB -> {args.output.stat().st_size / 1e9:.1f} GB: {args.output}"
    )


if __name__ == "__main__":
    main()

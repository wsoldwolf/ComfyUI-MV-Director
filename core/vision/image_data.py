"""Canonical pixel fingerprinting and MTMD image preparation."""

from __future__ import annotations

import base64
import hashlib
from dataclasses import dataclass
from io import BytesIO
from typing import Any


MAX_IMAGE_PIXELS = 100_000_000


class VisionImageError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class PreparedVisionImage:
    data_uri: str
    image_sha256: str
    source_width: int
    source_height: int
    analysis_width: int
    analysis_height: int
    channels: int
    batch_size: int
    warnings: tuple[str, ...] = ()


def pixel_fingerprint(
    pixels: bytes, *, width: int, height: int, channels: int
) -> str:
    """Hash normalized 8-bit pixels with their shape."""

    if width < 1 or height < 1 or channels not in {1, 3, 4}:
        raise VisionImageError("invalid image dimensions or channel count")
    expected = width * height * channels
    if len(pixels) != expected:
        raise VisionImageError(
            f"pixel byte count {len(pixels)} does not match expected {expected}"
        )
    digest = hashlib.sha256()
    digest.update(f"u8\0{width}x{height}x{channels}\0".encode("ascii"))
    digest.update(pixels)
    return digest.hexdigest()


def prepare_comfy_image(image: Any, analysis_max_edge: int) -> PreparedVisionImage:
    """Convert the first ComfyUI IMAGE batch item to a bounded PNG data URI.

    Torch, NumPy and Pillow stay behind this runtime boundary so the pure core
    test suite remains importable outside a ComfyUI Python environment.
    """

    if not isinstance(analysis_max_edge, int) or isinstance(analysis_max_edge, bool):
        raise VisionImageError("analysis_max_edge must be an integer")
    if not 256 <= analysis_max_edge <= 2048:
        raise VisionImageError("analysis_max_edge must be in 256..2048")
    try:
        import torch  # type: ignore
        from PIL import Image  # type: ignore
    except Exception as exc:  # pragma: no cover - depends on ComfyUI runtime
        raise VisionImageError(
            "ComfyUI image dependencies (torch and Pillow) are unavailable"
        ) from exc

    if not torch.is_tensor(image) or image.ndim != 4:
        raise VisionImageError(
            "image must be a ComfyUI IMAGE tensor [batch,height,width,channels]"
        )
    batch, height, width, channels = (int(value) for value in image.shape)
    if batch < 1 or height < 1 or width < 1 or channels not in {1, 3, 4}:
        raise VisionImageError("image has an unsupported shape")
    if width * height > MAX_IMAGE_PIXELS:
        raise VisionImageError(
            f"image exceeds {MAX_IMAGE_PIXELS:,} decoded pixels"
        )
    first = image[0].detach().to(device="cpu", dtype=torch.float32)
    if not bool(torch.isfinite(first).all()):
        raise VisionImageError("image contains NaN or infinity")
    minimum = float(first.min())
    maximum = float(first.max())
    if minimum < -1e-6 or maximum > 1.0 + 1e-6:
        raise VisionImageError("image pixels must be in 0.0..1.0")
    array = (
        first.clamp(0.0, 1.0)
        .mul(255.0)
        .round()
        .to(dtype=torch.uint8)
        .contiguous()
        .numpy()
    )
    pixels = array.tobytes(order="C")
    image_sha256 = pixel_fingerprint(
        pixels, width=width, height=height, channels=channels
    )
    if channels == 1:
        pil_image = Image.fromarray(array[..., 0], mode="L").convert("RGB")
    elif channels == 4:
        rgba = Image.fromarray(array, mode="RGBA")
        pil_image = Image.new("RGB", rgba.size, "white")
        pil_image.paste(rgba, mask=rgba.getchannel("A"))
    else:
        pil_image = Image.fromarray(array, mode="RGB")

    longest = max(pil_image.size)
    if longest > analysis_max_edge:
        scale = analysis_max_edge / longest
        target = (
            max(1, round(pil_image.width * scale)),
            max(1, round(pil_image.height * scale)),
        )
        pil_image = pil_image.resize(target, Image.Resampling.LANCZOS)
    output = BytesIO()
    pil_image.save(output, format="PNG", optimize=False)
    encoded = base64.b64encode(output.getvalue()).decode("ascii")
    warnings = (
        (f"IMAGE batch contains {batch} images; only the first was analyzed",)
        if batch > 1
        else ()
    )
    return PreparedVisionImage(
        data_uri=f"data:image/png;base64,{encoded}",
        image_sha256=image_sha256,
        source_width=width,
        source_height=height,
        analysis_width=pil_image.width,
        analysis_height=pil_image.height,
        channels=channels,
        batch_size=batch,
        warnings=warnings,
    )


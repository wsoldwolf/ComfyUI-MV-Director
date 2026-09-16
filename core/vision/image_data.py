"""Canonical pixel fingerprinting and MTMD image preparation."""

from __future__ import annotations

import base64
import hashlib
import math
from dataclasses import dataclass
from io import BytesIO
from typing import Any


MAX_IMAGE_PIXELS = 100_000_000
MAX_REFERENCE_VIEWS = 9


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
    """Convert a ComfyUI IMAGE batch to one bounded analysis PNG.

    Torch, NumPy and Pillow stay behind this runtime boundary so the pure core
    test suite remains importable outside a ComfyUI Python environment. A batch
    of two through nine images is arranged as one labelled contact sheet so a
    full-body view, face detail, side view, and rear view can be observed as one
    character identity.
    """

    if not isinstance(analysis_max_edge, int) or isinstance(analysis_max_edge, bool):
        raise VisionImageError("analysis_max_edge must be an integer")
    if not 256 <= analysis_max_edge <= 2048:
        raise VisionImageError("analysis_max_edge must be in 256..2048")
    try:
        import torch  # type: ignore
        from PIL import Image, ImageDraw  # type: ignore
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
    if batch > MAX_REFERENCE_VIEWS:
        raise VisionImageError(
            f"image batch supports at most {MAX_REFERENCE_VIEWS} reference views"
        )
    if batch * width * height > MAX_IMAGE_PIXELS:
        raise VisionImageError(
            f"image exceeds {MAX_IMAGE_PIXELS:,} decoded pixels"
        )
    normalized = image.detach().to(device="cpu", dtype=torch.float32)
    if not bool(torch.isfinite(normalized).all()):
        raise VisionImageError("image contains NaN or infinity")
    minimum = float(normalized.min())
    maximum = float(normalized.max())
    if minimum < -1e-6 or maximum > 1.0 + 1e-6:
        raise VisionImageError("image pixels must be in 0.0..1.0")
    array = (
        normalized.clamp(0.0, 1.0)
        .mul(255.0)
        .round()
        .to(dtype=torch.uint8)
        .contiguous()
        .numpy()
    )
    pixels = array.tobytes(order="C")
    if batch == 1:
        image_sha256 = pixel_fingerprint(
            array[0].tobytes(order="C"),
            width=width,
            height=height,
            channels=channels,
        )
    else:
        digest = hashlib.sha256()
        digest.update(
            f"u8-views\0{batch}x{width}x{height}x{channels}\0".encode("ascii")
        )
        digest.update(pixels)
        image_sha256 = digest.hexdigest()

    def to_rgb(item: Any) -> Any:
        if channels == 1:
            return Image.fromarray(item[..., 0], mode="L").convert("RGB")
        if channels == 4:
            rgba = Image.fromarray(item, mode="RGBA")
            result = Image.new("RGB", rgba.size, "white")
            result.paste(rgba, mask=rgba.getchannel("A"))
            return result
        return Image.fromarray(item, mode="RGB")

    views = [to_rgb(array[index]) for index in range(batch)]
    if batch == 1:
        pil_image = views[0]
    else:
        columns = min(3, math.ceil(math.sqrt(batch)))
        rows = math.ceil(batch / columns)
        label_height = max(20, min(48, height // 16))
        gap = max(2, min(12, width // 128))
        pil_image = Image.new(
            "RGB",
            (
                columns * width + (columns + 1) * gap,
                rows * (height + label_height) + (rows + 1) * gap,
            ),
            "white",
        )
        draw = ImageDraw.Draw(pil_image)
        for index, view in enumerate(views):
            column = index % columns
            row = index // columns
            x = gap + column * (width + gap)
            y = gap + row * (height + label_height + gap)
            draw.text((x + 4, y + 2), f"REFERENCE VIEW {index + 1}", fill="black")
            pil_image.paste(view, (x, y + label_height))

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
        (f"combined {batch} IMAGE batch items as one character reference sheet",)
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

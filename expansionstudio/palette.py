from __future__ import annotations

import shutil
import struct
import zlib
from pathlib import Path
from typing import Any


PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
VALID_JASC_SIZES = {16, 224, 256}


class PaletteError(ValueError):
    pass


def _paeth(left: int, above: int, upper_left: int) -> int:
    predictor = left + above - upper_left
    pa = abs(predictor - left)
    pb = abs(predictor - above)
    pc = abs(predictor - upper_left)
    if pa <= pb and pa <= pc:
        return left
    if pb <= pc:
        return above
    return upper_left


def _png_bpp(color_type: int, bit_depth: int) -> int:
    samples = {
        0: 1,  # grayscale
        2: 3,  # RGB
        3: 1,  # indexed
        4: 2,  # grayscale + alpha
        6: 4,  # RGBA
    }.get(color_type)
    if samples is None:
        raise PaletteError(f"Unsupported PNG color type: {color_type}")
    return samples * bit_depth


def _color_type_name(color_type: int) -> str:
    return {
        0: "grayscale",
        2: "truecolor",
        3: "indexed",
        4: "grayscale_alpha",
        6: "truecolor_alpha",
    }.get(color_type, f"unknown_{color_type}")


def _parse_png(path: Path) -> dict[str, Any]:
    data = path.read_bytes()
    if not data.startswith(PNG_SIGNATURE):
        raise PaletteError("Input file is not a PNG.")
    pos = len(PNG_SIGNATURE)
    info: dict[str, Any] = {"plte": [], "idat": bytearray(), "trns": b""}
    while pos + 8 <= len(data):
        length = struct.unpack(">I", data[pos:pos + 4])[0]
        chunk_type = data[pos + 4:pos + 8]
        chunk_start = pos + 8
        chunk_end = chunk_start + length
        if chunk_end + 4 > len(data):
            raise PaletteError("PNG chunk is truncated.")
        chunk = data[chunk_start:chunk_end]
        pos = chunk_end + 4  # skip CRC
        if chunk_type == b"IHDR":
            if length != 13:
                raise PaletteError("Invalid PNG IHDR chunk.")
            width, height, bit_depth, color_type, compression, filter_method, interlace = struct.unpack(">IIBBBBB", chunk)
            if compression != 0 or filter_method != 0:
                raise PaletteError("Unsupported PNG compression/filter method.")
            if interlace != 0:
                raise PaletteError("Interlaced PNG is not supported.")
            info.update({"width": width, "height": height, "bit_depth": bit_depth, "color_type": color_type})
        elif chunk_type == b"PLTE":
            if length % 3:
                raise PaletteError("Invalid PNG PLTE chunk.")
            info["plte"] = [tuple(int(component) for component in chunk[index:index + 3]) for index in range(0, length, 3)]
        elif chunk_type == b"tRNS":
            info["trns"] = bytes(chunk)
        elif chunk_type == b"IDAT":
            info["idat"].extend(chunk)
        elif chunk_type == b"IEND":
            break
    if "width" not in info or not info["idat"]:
        raise PaletteError("PNG is missing IHDR or IDAT data.")
    return info


def _unfilter_rows(raw: bytes, width: int, height: int, bpp_bits: int) -> list[bytes]:
    stride = (width * bpp_bits + 7) // 8
    filter_bpp = max(1, (bpp_bits + 7) // 8)
    rows: list[bytes] = []
    pos = 0
    previous = bytes(stride)
    for _y in range(height):
        if pos + 1 + stride > len(raw):
            raise PaletteError("PNG image data is truncated.")
        filter_type = raw[pos]
        row = bytearray(raw[pos + 1:pos + 1 + stride])
        pos += 1 + stride
        for index, value in enumerate(row):
            left = row[index - filter_bpp] if index >= filter_bpp else 0
            above = previous[index] if index < len(previous) else 0
            upper_left = previous[index - filter_bpp] if index >= filter_bpp else 0
            if filter_type == 0:
                pass
            elif filter_type == 1:
                row[index] = (value + left) & 0xFF
            elif filter_type == 2:
                row[index] = (value + above) & 0xFF
            elif filter_type == 3:
                row[index] = (value + ((left + above) // 2)) & 0xFF
            elif filter_type == 4:
                row[index] = (value + _paeth(left, above, upper_left)) & 0xFF
            else:
                raise PaletteError(f"Unsupported PNG filter type: {filter_type}")
        previous = bytes(row)
        rows.append(previous)
    return rows


def _scale_sample(value: int, bit_depth: int) -> int:
    if bit_depth == 8:
        return value
    if bit_depth == 16:
        return value >> 8
    maximum = (1 << bit_depth) - 1
    return round(value * 255 / maximum)


def _unpack_low_bit_values(row: bytes, width: int, bit_depth: int) -> list[int]:
    values: list[int] = []
    mask = (1 << bit_depth) - 1
    per_byte = 8 // bit_depth
    for byte in row:
        for shift_index in range(per_byte):
            shift = 8 - bit_depth - (shift_index * bit_depth)
            values.append((byte >> shift) & mask)
            if len(values) >= width:
                return values
    return values


def _append_color(colors: list[tuple[int, int, int]], seen: set[tuple[int, int, int]], color: tuple[int, int, int]) -> None:
    if color not in seen:
        seen.add(color)
        colors.append(color)


def _decode_png(path: Path) -> tuple[list[tuple[int, int, int, int]], dict[str, Any]]:
    info = _parse_png(path)
    width = int(info["width"])
    height = int(info["height"])
    bit_depth = int(info["bit_depth"])
    color_type = int(info["color_type"])
    bpp_bits = _png_bpp(color_type, bit_depth)
    raw = zlib.decompress(bytes(info["idat"]))
    rows = _unfilter_rows(raw, width, height, bpp_bits)
    pixels: list[tuple[int, int, int, int]] = []
    trns = bytes(info.get("trns", b""))

    if color_type == 3:
        palette = info["plte"]
        if not palette:
            raise PaletteError("Indexed PNG is missing a PLTE chunk.")
        alpha_by_index = [255] * len(palette)
        for index, alpha in enumerate(trns[:len(alpha_by_index)]):
            alpha_by_index[index] = int(alpha)
        for row in rows:
            indices = list(row[:width]) if bit_depth == 8 else _unpack_low_bit_values(row, width, bit_depth)
            for index in indices:
                if index >= len(palette):
                    raise PaletteError(f"Indexed PNG references missing palette index: {index}")
                red, green, blue = palette[index]
                pixels.append((int(red), int(green), int(blue), alpha_by_index[index]))
    elif color_type == 0:
        transparent_gray: int | None = None
        if len(trns) >= 2:
            transparent_gray = _scale_sample(struct.unpack(">H", trns[:2])[0], bit_depth)
        for row in rows:
            if bit_depth < 8:
                values = _unpack_low_bit_values(row, width, bit_depth)
                for value in values:
                    gray = _scale_sample(value, bit_depth)
                    pixels.append((gray, gray, gray, 0 if transparent_gray == gray else 255))
            elif bit_depth == 8:
                for value in row[:width]:
                    pixels.append((value, value, value, 0 if transparent_gray == value else 255))
            elif bit_depth == 16:
                for x in range(width):
                    gray = row[x * 2]
                    pixels.append((gray, gray, gray, 0 if transparent_gray == gray else 255))
            else:
                raise PaletteError(f"Unsupported grayscale bit depth: {bit_depth}")
    elif color_type == 2:
        if bit_depth not in {8, 16}:
            raise PaletteError(f"Unsupported truecolor bit depth: {bit_depth}")
        transparent_rgb: tuple[int, int, int] | None = None
        if len(trns) >= 6:
            values = struct.unpack(">HHH", trns[:6])
            transparent_rgb = tuple(_scale_sample(value, bit_depth) for value in values)
        sample_bytes = bit_depth // 8
        pixel_bytes = 3 * sample_bytes
        for row in rows:
            for x in range(width):
                base = x * pixel_bytes
                rgb = (row[base], row[base + sample_bytes], row[base + (2 * sample_bytes)])
                pixels.append((*rgb, 0 if transparent_rgb == rgb else 255))
    elif color_type == 4:
        if bit_depth not in {8, 16}:
            raise PaletteError(f"Unsupported grayscale-alpha bit depth: {bit_depth}")
        sample_bytes = bit_depth // 8
        pixel_bytes = 2 * sample_bytes
        for row in rows:
            for x in range(width):
                base = x * pixel_bytes
                gray = row[base]
                alpha = row[base + sample_bytes]
                pixels.append((gray, gray, gray, alpha))
    elif color_type == 6:
        if bit_depth not in {8, 16}:
            raise PaletteError(f"Unsupported truecolor-alpha bit depth: {bit_depth}")
        sample_bytes = bit_depth // 8
        pixel_bytes = 4 * sample_bytes
        for row in rows:
            for x in range(width):
                base = x * pixel_bytes
                pixels.append((row[base], row[base + sample_bytes], row[base + (2 * sample_bytes)], row[base + (3 * sample_bytes)]))
    else:
        raise PaletteError(f"Unsupported PNG color type: {color_type}")

    metadata = {
        "width": width,
        "height": height,
        "bit_depth": bit_depth,
        "color_type": color_type,
        "color_type_name": _color_type_name(color_type),
        "indexed": color_type == 3,
        "palette_entries": len(info.get("plte", [])),
    }
    return pixels, metadata


def extract_png_colors(path: Path, include_transparent_rgb: bool = False) -> tuple[list[tuple[int, int, int]], dict[str, Any]]:
    pixels, metadata = _decode_png(path)
    colors: list[tuple[int, int, int]] = []
    seen: set[tuple[int, int, int]] = set()
    has_transparency = False
    for red, green, blue, alpha in pixels:
        if alpha < 255:
            has_transparency = True
            if not include_transparent_rgb:
                continue
        _append_color(colors, seen, (red, green, blue))
    metadata = {**metadata, "used_colors": len(colors), "transparent": has_transparency}
    return colors, metadata


def analyze_png(path: Path) -> dict[str, Any]:
    colors, metadata = extract_png_colors(path)
    color_count = len(colors)
    return {
        "ok": True,
        "png": str(path),
        "width": metadata["width"],
        "height": metadata["height"],
        "bit_depth": metadata["bit_depth"],
        "color_type": metadata["color_type"],
        "color_type_name": metadata["color_type_name"],
        "indexed": metadata["indexed"],
        "palette_entries": metadata["palette_entries"],
        "used_colors": color_count,
        "transparent": metadata["transparent"],
        "gba_4bpp": color_count <= 16,
        "gba_8bpp": color_count <= 256,
        "gba_224_color": color_count <= 224,
    }


def read_jasc_pal(path: Path) -> list[tuple[int, int, int]]:
    lines = path.read_text(encoding="ascii", errors="strict").splitlines()
    if len(lines) < 3 or lines[0].strip() != "JASC-PAL" or lines[1].strip() != "0100":
        raise PaletteError("Input palette is not a JASC-PAL file.")
    try:
        count = int(lines[2].strip())
    except ValueError as error:
        raise PaletteError("JASC-PAL color count is invalid.") from error
    colors: list[tuple[int, int, int]] = []
    for line in lines[3:3 + count]:
        parts = line.split()
        if len(parts) != 3:
            raise PaletteError("JASC-PAL color line is invalid.")
        red, green, blue = (int(part) for part in parts)
        if not all(0 <= component <= 255 for component in (red, green, blue)):
            raise PaletteError("JASC-PAL color component is out of range.")
        colors.append((red, green, blue))
    if len(colors) != count:
        raise PaletteError("JASC-PAL file ended before all colors were read.")
    return colors


def _ordered_colors(png_colors: list[tuple[int, int, int]], palette_size: int, base_palette: list[tuple[int, int, int]] | None) -> list[tuple[int, int, int]]:
    colors: list[tuple[int, int, int]] = []
    seen: set[tuple[int, int, int]] = set()
    if base_palette:
        for color in base_palette:
            _append_color(colors, seen, color)
            if len(colors) >= palette_size:
                break
    for color in png_colors:
        _append_color(colors, seen, color)
        if len(colors) >= palette_size:
            break
    return colors


def _nearest_color_index(color: tuple[int, int, int], palette: list[tuple[int, int, int]], start: int = 0) -> int:
    best_index = start
    best_distance: int | None = None
    for index in range(start, len(palette)):
        red, green, blue = palette[index]
        distance = ((color[0] - red) * (color[0] - red)) + ((color[1] - green) * (color[1] - green)) + ((color[2] - blue) * (color[2] - blue))
        if best_distance is None or distance < best_distance:
            best_index = index
            best_distance = distance
    return best_index


def _quantize_colors(colors: list[tuple[int, int, int]], limit: int) -> list[tuple[int, int, int]]:
    if len(colors) <= limit:
        return colors
    if limit <= 0:
        return []
    buckets: dict[tuple[int, int, int], list[tuple[int, int, int]]] = {}
    levels = max(1, round(limit ** (1 / 3)))
    step = max(1, 256 // levels)
    for color in colors:
        key = (min(levels - 1, color[0] // step), min(levels - 1, color[1] // step), min(levels - 1, color[2] // step))
        buckets.setdefault(key, []).append(color)
    ranked = sorted(buckets.values(), key=len, reverse=True)
    palette: list[tuple[int, int, int]] = []
    seen: set[tuple[int, int, int]] = set()
    for bucket in ranked:
        red = round(sum(color[0] for color in bucket) / len(bucket))
        green = round(sum(color[1] for color in bucket) / len(bucket))
        blue = round(sum(color[2] for color in bucket) / len(bucket))
        _append_color(palette, seen, (red, green, blue))
        if len(palette) >= limit:
            return palette
    for color in colors:
        _append_color(palette, seen, color)
        if len(palette) >= limit:
            break
    return palette


def jasc_pal_text(colors: list[tuple[int, int, int]], palette_size: int) -> str:
    if palette_size not in VALID_JASC_SIZES:
        raise PaletteError("Palette size must be 16, 224, or 256.")
    if len(colors) > palette_size:
        raise PaletteError(f"PNG uses {len(colors)} colors, which exceeds the selected palette size {palette_size}.")
    padded = [*colors, *([(0, 0, 0)] * (palette_size - len(colors)))]
    lines = ["JASC-PAL", "0100", str(palette_size)]
    lines.extend(f"{red} {green} {blue}" for red, green, blue in padded)
    return "\n".join(lines) + "\n"


def write_jasc_pal_from_png(png_path: Path, output_path: Path, palette_size: int, base_pal_path: Path | None = None) -> dict[str, Any]:
    if png_path.suffix.lower() != ".png":
        raise PaletteError("Input file must be a .png file.")
    if output_path.suffix.lower() != ".pal":
        raise PaletteError("Output file must use the .pal extension.")
    colors, metadata = extract_png_colors(png_path)
    base_palette = read_jasc_pal(base_pal_path) if base_pal_path else None
    ordered = _ordered_colors(colors, palette_size, base_palette)
    if any(color not in set(ordered) for color in colors):
        raise PaletteError(f"PNG uses colors that do not fit in the selected palette size {palette_size}.")
    text = jasc_pal_text(ordered, palette_size)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    backup_path: Path | None = None
    if output_path.exists():
        backup_path = output_path.with_name(output_path.name + ".bak")
        shutil.copy2(output_path, backup_path)
    output_path.write_text(text, encoding="ascii", newline="\n")
    return {
        "ok": True,
        "png": str(png_path),
        "output": str(output_path),
        "base_palette": str(base_pal_path) if base_pal_path else None,
        "palette_size": palette_size,
        "used_colors": len(colors),
        "written_colors": len(ordered),
        "padded_colors": palette_size - len(ordered),
        "backup": str(backup_path) if backup_path else None,
        "image": metadata,
    }


def _png_chunk(name: bytes, data: bytes) -> bytes:
    return struct.pack(">I", len(data)) + name + data + struct.pack(">I", zlib.crc32(name + data) & 0xFFFFFFFF)


def _write_indexed_png(path: Path, width: int, height: int, indices: list[int], palette: list[tuple[int, int, int]], transparent_index: int | None) -> None:
    raw_rows = bytearray()
    for y in range(height):
        start = y * width
        raw_rows.append(0)
        raw_rows.extend(indices[start:start + width])
    png = bytearray(PNG_SIGNATURE)
    png.extend(_png_chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 3, 0, 0, 0)))
    png.extend(_png_chunk(b"PLTE", b"".join(bytes(color) for color in palette)))
    if transparent_index is not None:
        alphas = bytearray([255] * len(palette))
        alphas[transparent_index] = 0
        png.extend(_png_chunk(b"tRNS", bytes(alphas)))
    png.extend(_png_chunk(b"IDAT", zlib.compress(bytes(raw_rows))))
    png.extend(_png_chunk(b"IEND", b""))
    path.write_bytes(bytes(png))


def write_indexed_png_from_png(
    png_path: Path,
    output_path: Path,
    palette_size: int,
    base_pal_path: Path | None = None,
    quantize: bool = True,
) -> dict[str, Any]:
    if palette_size not in VALID_JASC_SIZES:
        raise PaletteError("Palette size must be 16, 224, or 256.")
    if png_path.suffix.lower() != ".png" or output_path.suffix.lower() != ".png":
        raise PaletteError("Input and output files must use the .png extension.")
    pixels, metadata = _decode_png(png_path)
    base_palette = read_jasc_pal(base_pal_path) if base_pal_path else None
    has_transparency = any(alpha < 255 for *_rgb, alpha in pixels)
    source_colors: list[tuple[int, int, int]] = []
    seen: set[tuple[int, int, int]] = set()
    for red, green, blue, alpha in pixels:
        if alpha < 255:
            continue
        _append_color(source_colors, seen, (red, green, blue))

    available = palette_size - (1 if has_transparency else 0)
    if len(source_colors) > available and not quantize:
        raise PaletteError(f"PNG uses {len(source_colors)} opaque colors, which exceeds the selected palette size {palette_size}.")

    seed_palette = _ordered_colors(source_colors, available, base_palette)
    if len(source_colors) > available:
        seed_palette = _quantize_colors(source_colors, available)
    transparent_color = base_palette[0] if has_transparency and base_palette else (0, 0, 0)
    palette = [transparent_color] if has_transparency else []
    for color in seed_palette:
        if len(palette) >= palette_size:
            break
        if color not in palette:
            palette.append(color)
    while len(palette) < palette_size:
        palette.append((0, 0, 0))

    indices: list[int] = []
    lookup = {color: index for index, color in enumerate(palette)}
    start_index = 1 if has_transparency else 0
    for red, green, blue, alpha in pixels:
        if alpha < 255:
            indices.append(0)
            continue
        color = (red, green, blue)
        indices.append(lookup[color] if color in lookup else _nearest_color_index(color, palette, start=start_index))

    output_path.parent.mkdir(parents=True, exist_ok=True)
    backup_path: Path | None = None
    if output_path.exists():
        backup_path = output_path.with_name(output_path.name + ".bak")
        shutil.copy2(output_path, backup_path)
    _write_indexed_png(output_path, int(metadata["width"]), int(metadata["height"]), indices, palette, 0 if has_transparency else None)
    return {
        "ok": True,
        "png": str(png_path),
        "output": str(output_path),
        "base_palette": str(base_pal_path) if base_pal_path else None,
        "palette_size": palette_size,
        "source_colors": len(source_colors),
        "written_palette_entries": len(palette),
        "quantized": len(source_colors) > available,
        "transparent": has_transparency,
        "backup": str(backup_path) if backup_path else None,
        "image": metadata,
    }

from __future__ import annotations

import math
import xml.etree.ElementTree as ET
from pathlib import Path

from PIL import Image, ImageDraw


def render_replay_gif(
    *,
    net_file: str | Path,
    fcd_file: str | Path,
    output_file: str | Path,
    duration_seconds: int,
    title: str = "SimTrend replay",
    width: int = 900,
    height: int = 650,
    max_frames: int = 120,
    max_vehicles_per_frame: int = 450,
) -> dict:
    net_path = Path(net_file)
    fcd_path = Path(fcd_file)
    gif_path = Path(output_file)
    if not net_path.exists() or not fcd_path.exists():
        return {
            "ok": False,
            "message": "Missing network or FCD file.",
            "gif_file": str(gif_path),
        }

    lane_shapes = _load_lane_shapes(net_path)
    sample_interval = max(2.0, duration_seconds / max(max_frames, 1))
    frames = _load_fcd_frames(
        fcd_path,
        sample_interval=sample_interval,
        max_frames=max_frames,
        max_vehicles_per_frame=max_vehicles_per_frame,
    )
    if not frames:
        return {
            "ok": False,
            "message": "No vehicle trajectory frames were found in FCD output.",
            "gif_file": str(gif_path),
        }

    bounds = _build_bounds(lane_shapes, frames)
    images = [
        _draw_frame(
            lane_shapes=lane_shapes,
            frame=frame,
            bounds=bounds,
            width=width,
            height=height,
            title=title,
        )
        for frame in frames
    ]

    gif_path.parent.mkdir(parents=True, exist_ok=True)
    images[0].save(
        gif_path,
        save_all=True,
        append_images=images[1:],
        duration=110,
        loop=0,
        optimize=True,
    )
    return {
        "ok": True,
        "message": f"Generated replay GIF with {len(images)} frames.",
        "gif_file": str(gif_path),
        "frame_count": len(images),
        "sample_interval_s": round(sample_interval, 2),
        "fcd_file": str(fcd_path),
    }


def _load_lane_shapes(net_file: Path) -> list[list[tuple[float, float]]]:
    root = ET.parse(net_file).getroot()
    shapes: list[list[tuple[float, float]]] = []
    for lane in root.findall(".//lane"):
        lane_id = lane.get("id", "")
        shape_text = lane.get("shape", "")
        if not shape_text or lane_id.startswith(":"):
            continue
        points = _parse_shape(shape_text)
        if len(points) >= 2:
            shapes.append(points)
    return shapes


def _load_fcd_frames(
    fcd_file: Path,
    *,
    sample_interval: float,
    max_frames: int,
    max_vehicles_per_frame: int,
) -> list[dict]:
    frames: list[dict] = []
    last_time: float | None = None

    for event, elem in ET.iterparse(fcd_file, events=("end",)):
        if elem.tag != "timestep":
            continue
        time_value = _to_float(elem.get("time"), 0.0)
        if last_time is not None and time_value - last_time < sample_interval:
            elem.clear()
            continue

        vehicles = []
        for vehicle in elem.findall("vehicle"):
            vehicles.append(
                {
                    "id": vehicle.get("id", ""),
                    "x": _to_float(vehicle.get("x"), 0.0),
                    "y": _to_float(vehicle.get("y"), 0.0),
                    "angle": _to_float(vehicle.get("angle"), 0.0),
                    "speed": _to_float(vehicle.get("speed"), 0.0),
                }
            )
        if vehicles:
            vehicles.sort(key=lambda item: item["id"])
            frames.append(
                {
                    "time": time_value,
                    "vehicles": vehicles[:max_vehicles_per_frame],
                    "vehicle_count": len(vehicles),
                }
            )
            last_time = time_value
        elem.clear()

        if len(frames) >= max_frames:
            break
    return frames


def _build_bounds(lane_shapes: list[list[tuple[float, float]]], frames: list[dict]) -> tuple[float, float, float, float]:
    xs: list[float] = []
    ys: list[float] = []
    for shape in lane_shapes:
        for x, y in shape:
            xs.append(x)
            ys.append(y)
    for frame in frames:
        for vehicle in frame["vehicles"]:
            xs.append(vehicle["x"])
            ys.append(vehicle["y"])

    if not xs or not ys:
        return 0.0, 1.0, 0.0, 1.0
    min_x, max_x = min(xs), max(xs)
    min_y, max_y = min(ys), max(ys)
    if math.isclose(min_x, max_x):
        max_x += 1.0
    if math.isclose(min_y, max_y):
        max_y += 1.0
    return min_x, max_x, min_y, max_y


def _draw_frame(
    *,
    lane_shapes: list[list[tuple[float, float]]],
    frame: dict,
    bounds: tuple[float, float, float, float],
    width: int,
    height: int,
    title: str,
) -> Image.Image:
    image = Image.new("RGB", (width, height), "#f8fafc")
    draw = ImageDraw.Draw(image)

    for shape in lane_shapes:
        points = [_project(point[0], point[1], bounds, width, height) for point in shape]
        if len(points) >= 2:
            draw.line(points, fill="#cbd5e1", width=6, joint="curve")
            draw.line(points, fill="#64748b", width=2, joint="curve")

    for vehicle in frame["vehicles"]:
        x, y = _project(vehicle["x"], vehicle["y"], bounds, width, height)
        color = "#f97316" if vehicle["speed"] < 0.5 else "#2563eb"
        _draw_vehicle(draw, x, y, color)

    draw.rectangle((0, 0, width, 38), fill="#0f172a")
    draw.text((14, 11), f"{title} | t={frame['time']:.0f}s | vehicles={frame['vehicle_count']}", fill="#ffffff")
    return image


def _draw_vehicle(draw: ImageDraw.ImageDraw, x: float, y: float, color: str) -> None:
    half_w = 5
    half_h = 3
    box = (x - half_w, y - half_h, x + half_w, y + half_h)
    try:
        draw.rounded_rectangle(box, radius=2, fill=color, outline="#ffffff", width=1)
    except AttributeError:
        draw.rectangle(box, fill=color, outline="#ffffff")


def _project(
    x: float,
    y: float,
    bounds: tuple[float, float, float, float],
    width: int,
    height: int,
) -> tuple[float, float]:
    min_x, max_x, min_y, max_y = bounds
    margin = 42
    draw_width = max(width - margin * 2, 1)
    draw_height = max(height - margin * 2 - 38, 1)
    scale = min(draw_width / (max_x - min_x), draw_height / (max_y - min_y))
    used_width = (max_x - min_x) * scale
    used_height = (max_y - min_y) * scale
    offset_x = margin + (draw_width - used_width) / 2
    offset_y = margin + 38 + (draw_height - used_height) / 2
    px = offset_x + (x - min_x) * scale
    py = offset_y + (max_y - y) * scale
    return px, py


def _parse_shape(shape_text: str) -> list[tuple[float, float]]:
    points: list[tuple[float, float]] = []
    for pair in shape_text.split():
        try:
            x_text, y_text = pair.split(",", 1)
            points.append((float(x_text), float(y_text)))
        except ValueError:
            continue
    return points


def _to_float(value: str | None, default: float) -> float:
    try:
        return float(value) if value is not None else default
    except ValueError:
        return default

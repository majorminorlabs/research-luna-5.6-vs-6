#!/usr/bin/env python3
"""Generate the publication figures from the checked-in result tables.

The script intentionally uses only the standard library and Pillow. It reads
the public results files, so the figures can be regenerated without access to
the original research checkout.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


ROOT = Path(__file__).resolve().parents[1]
FIGURES = ROOT / "figures"
RESULTS = ROOT / "results"
WIDTH, HEIGHT = 1600, 920
BG = (250, 248, 244)
INK = (32, 38, 43)
MUTED = (91, 100, 106)
GRID = (218, 220, 218)
GREEN = (35, 105, 83)
ORANGE = (196, 91, 53)


def font(size: int, bold: bool = False) -> ImageFont.ImageFont:
    candidates = (
        "/System/Library/Fonts/Supplemental/Arial Bold.ttf"
        if bold
        else "/System/Library/Fonts/Supplemental/Arial.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
        if bold
        else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    )
    for candidate in candidates:
        if Path(candidate).exists():
            return ImageFont.truetype(candidate, size)
    return ImageFont.load_default()


def csv_rows(name: str) -> list[dict[str, str]]:
    with (RESULTS / name).open(newline="") as handle:
        return list(csv.DictReader(handle))


def canvas(title: str, subtitle: str = "") -> tuple[Image.Image, ImageDraw.ImageDraw]:
    image = Image.new("RGB", (WIDTH, HEIGHT), BG)
    draw = ImageDraw.Draw(image)
    draw.text((80, 55), title, fill=INK, font=font(42, bold=True))
    if subtitle:
        draw.text((82, 112), subtitle, fill=MUTED, font=font(22))
    draw.text(
        (80, HEIGHT - 42),
        "Source: luna-comparison-v1.0 final results; bars start at zero.",
        fill=MUTED,
        font=font(18),
    )
    return image, draw


def axis(draw: ImageDraw.ImageDraw, left: int, top: int, right: int, bottom: int, maximum: float, suffix: str = "") -> None:
    draw.line((left, top, left, bottom), fill=INK, width=3)
    draw.line((left, bottom, right, bottom), fill=INK, width=3)
    for i in range(6):
        value = maximum * i / 5
        y = bottom - (bottom - top) * i / 5
        draw.line((left, y, right, y), fill=GRID, width=2)
        if maximum >= 2:
            label = f"{value:.0f}{suffix}"
        elif maximum <= 0.2:
            label = f"{value:.2f}"
        else:
            label = f"{value:.1f}"
        draw.text((left - 65, y - 12), label, fill=MUTED, font=font(18))


def grouped_bars(
    path: Path,
    title: str,
    subtitle: str,
    labels: list[str],
    first: list[float],
    second: list[float],
    maximum: float,
    value_format: str = ".2f",
) -> None:
    image, draw = canvas(title, subtitle)
    left, top, right, bottom = 150, 190, WIDTH - 90, HEIGHT - 110
    axis(draw, left, top, right, bottom, maximum)
    group_width = (right - left) / len(labels)
    bar_width = min(72, group_width * 0.27)
    for index, label in enumerate(labels):
        center = left + group_width * (index + 0.5)
        for offset, value, color in ((-bar_width * 0.62, first[index], GREEN), (bar_width * 0.62, second[index], ORANGE)):
            x0 = center + offset - bar_width / 2
            x1 = center + offset + bar_width / 2
            y1 = bottom - (bottom - top) * value / maximum
            draw.rounded_rectangle((x0, y1, x1, bottom), radius=8, fill=color)
            draw.text((x0, y1 - 31), format(value, value_format), fill=INK, font=font(16, bold=True))
        box = draw.textbbox((0, 0), label, font=font(20, bold=True))
        draw.text((center - (box[2] - box[0]) / 2, bottom + 20), label, fill=INK, font=font(20, bold=True))
    legend_y = 150
    draw.rounded_rectangle((WIDTH - 470, legend_y, WIDTH - 450, legend_y + 20), radius=4, fill=GREEN)
    draw.text((WIDTH - 435, legend_y - 3), "GPT-5.6 Luna", fill=INK, font=font(18))
    draw.rounded_rectangle((WIDTH - 245, legend_y, WIDTH - 225, legend_y + 20), radius=4, fill=ORANGE)
    draw.text((WIDTH - 210, legend_y - 3), "GPT-6 Luna", fill=INK, font=font(18))
    image.save(path, "PNG", optimize=True)


def single_bars(path: Path, title: str, subtitle: str, labels: list[str], values: list[float], maximum: float, colors: list[tuple[int, int, int]], suffix: str = "") -> None:
    image, draw = canvas(title, subtitle)
    left, top, right, bottom = 170, 190, WIDTH - 110, HEIGHT - 110
    axis(draw, left, top, right, bottom, maximum, suffix)
    slot = (right - left) / len(labels)
    width = min(150, slot * 0.55)
    for index, (label, value, color) in enumerate(zip(labels, values, colors)):
        center = left + slot * (index + 0.5)
        x0, x1 = center - width / 2, center + width / 2
        y1 = bottom - (bottom - top) * value / maximum
        draw.rounded_rectangle((x0, y1, x1, bottom), radius=10, fill=color)
        draw.text((center - 48, y1 - 35), f"{value:.4f}" if maximum <= 1 else f"{value:.0f}", fill=INK, font=font(18, bold=True))
        box = draw.textbbox((0, 0), label, font=font(22, bold=True))
        draw.text((center - (box[2] - box[0]) / 2, bottom + 22), label, fill=INK, font=font(22, bold=True))
    image.save(path, "PNG", optimize=True)


def repeat_chart(path: Path, agreement: list[float], mad: list[float]) -> None:
    image, draw = canvas("Repeat consistency", "Exact agreement and mean absolute difference across the two repeats")
    left, top, right, bottom = 170, 190, WIDTH - 110, HEIGHT - 110
    panels = ((left, "Exact agreement", agreement, 1.0, [f"{value * 100:.1f}%" for value in agreement]),
              (WIDTH // 2 + 20, "Mean absolute difference", mad, 0.12, [f"{value:.4f}" for value in mad]))
    for panel_left, label, values, maximum, text_values in panels:
        panel_right = panel_left + 520
        axis(draw, panel_left, top, panel_right, bottom, maximum)
        slot = (panel_right - panel_left) / 2
        for index, (model, value, color, text_value) in enumerate(zip(("GPT-5.6", "GPT-6"), values, (GREEN, ORANGE), text_values)):
            center = panel_left + slot * (index + 0.5)
            width = 100
            y1 = bottom - (bottom - top) * value / maximum
            draw.rounded_rectangle((center - width / 2, y1, center + width / 2, bottom), radius=8, fill=color)
            draw.text((center - 35, y1 - 34), text_value, fill=INK, font=font(17, bold=True))
            draw.text((center - 48, bottom + 22), model, fill=INK, font=font(18, bold=True))
        draw.text((panel_left, top - 48), label, fill=INK, font=font(24, bold=True))
    image.save(path, "PNG", optimize=True)


def main() -> None:
    FIGURES.mkdir(parents=True, exist_ok=True)
    results = json.loads((RESULTS / "results.json").read_text())
    overall = {item["model"]: item for item in results["overall"]}
    categories = {(item["model"], item["category"]): item["capability_score"] for item in results["categories"]}
    pairwise = results["pairwise"]["counts"]
    performance = {
        (item["model"], item["run_id"]): item
        for item in results["performance"]
    }
    repeat_rows = csv_rows("repeat_consistency.csv")
    repeat = {
        (row["model"], row["component"]): float(row["exact_agreement_rate"])
        for row in repeat_rows
    }
    mad = {
        (row["model"], row["component"]): float(row["mean_absolute_difference"])
        for row in repeat_rows
    }
    pooled_56 = performance[("gpt-5.6-luna", "pooled")]
    pooled_6 = performance[("gpt-6-luna", "pooled")]
    single_bars(
        FIGURES / "overall-capability.png",
        "Overall capability",
        "Per-task normalized capability score; higher is better",
        ["GPT-5.6", "GPT-6"],
        [overall["gpt-5.6-luna"]["capability_score"], overall["gpt-6-luna"]["capability_score"]],
        1.0,
        [GREEN, ORANGE],
    )
    grouped_bars(
        FIGURES / "category-comparison.png",
        "Category comparison",
        "Final capability scores by frozen benchmark category",
        ["AGENT", "CODE", "CTX", "EVID", "EXTR", "REAS", "WRITE"],
        [categories[("gpt-5.6-luna", category)] for category in ("AGENT", "CODE", "CTX", "EVID", "EXTR", "REAS", "WRITE")],
        [categories[("gpt-6-luna", category)] for category in ("AGENT", "CODE", "CTX", "EVID", "EXTR", "REAS", "WRITE")],
        1.0,
    )
    single_bars(
        FIGURES / "pairwise-results.png",
        "Blind pairwise results",
        "59 judged pairs; one error pair was skipped",
        ["GPT-5.6 wins", "GPT-6 wins", "Ties"],
        [pairwise["gpt-5.6-luna"]["W"], pairwise["gpt-6-luna"]["W"], pairwise["gpt-5.6-luna"]["T"]],
        25,
        [GREEN, ORANGE, (122, 132, 137)],
    )
    grouped_bars(
        FIGURES / "latency-comparison.png",
        "End-to-end latency",
        "Pooled two-repeat observations, seconds; CLI versions differed",
        ["Mean", "Median", "P90"],
        [pooled_56["mean_latency_ms"] / 1000, pooled_56["median_latency_ms"] / 1000, pooled_56["p90_latency_ms"] / 1000],
        [pooled_6["mean_latency_ms"] / 1000, pooled_6["median_latency_ms"] / 1000, pooled_6["p90_latency_ms"] / 1000],
        50.0,
        ".1f",
    )
    repeat_chart(
        FIGURES / "repeat-consistency.png",
        [repeat[("gpt-5.6-luna", "capability_score")], repeat[("gpt-6-luna", "capability_score")]],
        [mad[("gpt-5.6-luna", "capability_score")], mad[("gpt-6-luna", "capability_score")]],
    )


if __name__ == "__main__":
    main()

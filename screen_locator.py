"""screen_locator.py - Locate terminal rows and link glyphs from a screenshot.

Pixel positions used to be predicted from a fixed line height (20 px) plus
per-machine calibration. That breaks on larger displays, other DPI scales and
resized windows: a 1920x1080 laptop renders the terminal at 14 px per line, so
predicted clicks drift a full line every three rows. Smartpoint's terminal does
not expose UIA text bounds, and the FS "D" link has no typed equivalent, so the
only ground truth is the rendered image.

Everything here is a pure function over a PIL image of the SmartRichTextBox
area (coordinates are relative to that image). Pillow's C-level operations do
the per-pixel work so a 4K terminal analyses in milliseconds.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import Optional

from PIL import Image, ImageChops

# A pixel differing from the background by more than this (summed over RGB,
# averaged by the L conversion) counts as ink.
_INK_THRESHOLD = 20
# Columns inked in more than this share of rows are borders/scrollbars.
_BORDER_COLUMN_SHARE = 0.6
# Link colours: one channel dominates the other two by this margin.
_LINK_MARGIN = 80
_LINK_MIN_LEVEL = 140
# Single glyphs (D, R) are narrower than this many pixels per pixel of pitch.
_GLYPH_MAX_WIDTH_PER_PITCH = 1.0
# BOOK sits in the left share of the row; D/R in the right share.
_BOOK_ZONE = 0.15
_DR_ZONE = 0.80
# Need this many equal band spacings to trust a measured pitch.
_MIN_PITCH_VOTES = 3

Point = tuple[int, int]


@dataclass(frozen=True)
class Band:
    """A horizontal run of rows containing ink (one rendered text line)."""

    top: int
    bottom: int  # exclusive

    @property
    def center(self) -> float:
        return (self.top + self.bottom - 1) / 2


@dataclass(frozen=True)
class TerminalLayout:
    background: tuple[int, int, int]
    content_left: int
    content_right: int  # exclusive
    bands: tuple[Band, ...]
    line_pitch: Optional[float]


@dataclass(frozen=True)
class OptionRow:
    """One FS pricing option's action row: «BOOK» +TQ ... D R."""

    y: int
    d: Point
    r: Optional[Point]
    book: Optional[Point]


def analyze_terminal(img: Image.Image) -> TerminalLayout:
    """Measure background, content columns, text bands and line pitch."""
    rgb = img.convert("RGB")
    background = _background_color(rgb)
    ink = _ink_mask(rgb, background)

    left, right = _content_columns(ink)
    bands = _text_bands(ink.crop((left, 0, right, ink.height))) if right > left else ()
    return TerminalLayout(
        background=background,
        content_left=left,
        content_right=right,
        bands=bands,
        line_pitch=_line_pitch(bands),
    )


def find_option_rows(img: Image.Image, layout: TerminalLayout) -> list[OptionRow]:
    """Return FS pricing-option action rows top to bottom.

    A row qualifies when it starts with a green link («BOOK») and ends with at
    least two single-glyph blue links (D, R). Aircraft codes and airports are
    blue too, but never on a row that starts with a green link.
    """
    if not layout.bands:
        return []
    rgb = img.convert("RGB")
    blue = _channel_dominant_mask(rgb, dominant=2)
    green = _channel_dominant_mask(rgb, dominant=1)
    width = layout.content_right - layout.content_left
    pitch = layout.line_pitch or _median_band_height(layout.bands)
    max_glyph = max(4, int(pitch * _GLYPH_MAX_WIDTH_PER_PITCH))

    rows: list[OptionRow] = []
    for band in layout.bands:
        y = round(band.center)
        green_runs = _runs_in_band(green, band, layout)
        book = next(
            (
                run
                for run in green_runs
                if run[0] < layout.content_left + width * _BOOK_ZONE
            ),
            None,
        )
        if book is None:
            continue
        right_blue = [
            run
            for run in _runs_in_band(blue, band, layout)
            if run[0] >= layout.content_left + width * _DR_ZONE
        ]
        if len(right_blue) < 2 or any(b - a > max_glyph for a, b in right_blue[:2]):
            continue
        d_run, r_run = right_blue[0], right_blue[1]
        rows.append(
            OptionRow(
                y=y,
                d=(_mid(d_run), y),
                r=(_mid(r_run), y),
                book=(_mid(book), y),
            )
        )
    return rows


def line_center_y(layout: TerminalLayout, text: str, line_idx: int) -> Optional[float]:
    """Y centre of copied-text line ``line_idx``, anchored on the rendered grid.

    The first inked band is the first non-blank text line. Its own centre can be
    skewed (the prompt row carries a taller cursor block), so the grid phase is
    taken from every band and the first band is snapped onto it. Assumes the
    terminal is scrolled to the top, as the fixed-height model did.
    """
    pitch = layout.line_pitch
    if pitch is None or not layout.bands:
        return None
    lines = text.split("\n")
    first_text_idx = next((i for i, line in enumerate(lines) if line.strip()), None)
    if first_text_idx is None:
        return None
    phase = _grid_phase(layout.bands, pitch)
    first_center = phase + round((layout.bands[0].center - phase) / pitch) * pitch
    return first_center + (line_idx - first_text_idx) * pitch


def visible_line_count(layout: TerminalLayout, viewport_height: int) -> int:
    """How many text lines the terminal shows at once."""
    if not layout.line_pitch:
        return 0
    return int(viewport_height // layout.line_pitch)


def text_line_count(text: str) -> int:
    """Rendered lines of copied terminal text (trailing blank lines dropped)."""
    return len(text.rstrip().split("\n")) if text.strip() else 0


def select_option_row(
    layout: TerminalLayout,
    rows: list[OptionRow],
    text: str,
    book_lines: list[int],
    ordinal: int,
    viewport: str,
) -> Optional[OptionRow]:
    """Pick pricing option ``ordinal``'s action row from the visible ``rows``.

    ``book_lines`` are the copied-text line indices of every option's
    «BOOK»/+TQ row, in order. ``viewport`` says where the terminal is scrolled:

    * ``"top"``: the first text line is the first rendered line, so the row is
      found at its predicted Y on the measured grid.
    * ``"bottom"``: the last option row is the last visible one, so the row is
      counted back from the end. Evenly spaced options make any Y-based guess
      ambiguous once the terminal is scrolled, which is why the caller scrolls
      to a known end instead of matching on Y.
    """
    if not rows or not 0 <= ordinal < len(book_lines):
        return None
    if viewport == "bottom":
        index = len(rows) - (len(book_lines) - ordinal)
        return rows[index] if 0 <= index < len(rows) else None
    target_y = line_center_y(layout, text, book_lines[ordinal])
    if target_y is None or layout.line_pitch is None:
        return None
    best = min(rows, key=lambda row: abs(row.y - target_y))
    return best if abs(best.y - target_y) <= layout.line_pitch / 2 else None


# ── internals ───────────────────────────────────────────────────────────────


def _background_color(rgb: Image.Image) -> tuple[int, int, int]:
    """Most common colour, sampled on a reduced copy (nearest keeps exact
    colours) so large terminals stay fast."""
    step = max(1, int((rgb.width * rgb.height / 40_000) ** 0.5))
    sample = rgb.reduce(step) if step > 1 else rgb
    colors = sample.getcolors(sample.width * sample.height)
    return max(colors)[1]


def _ink_mask(rgb: Image.Image, background: tuple[int, int, int]) -> Image.Image:
    diff = ImageChops.difference(rgb, Image.new("RGB", rgb.size, background))
    return diff.convert("L").point(lambda v: 255 if v > _INK_THRESHOLD else 0)


def _content_columns(ink: Image.Image) -> tuple[int, int]:
    """Columns between the borders: drop edge columns inked in most rows."""
    profile = list(ink.resize((ink.width, 1), Image.BOX).getdata())
    limit = 255 * _BORDER_COLUMN_SHARE
    left = 0
    while left < len(profile) and profile[left] > limit:
        left += 1
    right = len(profile)
    while right > left and profile[right - 1] > limit:
        right -= 1
    return left, right


def _text_bands(ink: Image.Image) -> tuple[Band, ...]:
    profile = list(ink.resize((1, ink.height), Image.BOX).getdata())
    bands: list[Band] = []
    start = None
    for y, value in enumerate(profile + [0]):
        if value and start is None:
            start = y
        elif not value and start is not None:
            bands.append(Band(start, y))
            start = None
    return tuple(bands)


def _line_pitch(bands: tuple[Band, ...]) -> Optional[float]:
    """Most common spacing between consecutive band tops (blank lines give
    multiples, which lose the vote)."""
    gaps = [b.top - a.top for a, b in zip(bands, bands[1:])]
    if not gaps:
        return None
    gap, votes = Counter(gaps).most_common(1)[0]
    # Antialiasing can shift a band top by a pixel: fold neighbours in.
    votes += gaps.count(gap - 1) + gaps.count(gap + 1)
    if votes < _MIN_PITCH_VOTES:
        return None
    near = [g for g in gaps if abs(g - gap) <= 1]
    return sum(near) / len(near)


def _grid_phase(bands: tuple[Band, ...], pitch: float) -> float:
    """A row-centre position on the text grid, robust to odd bands: the median
    band centre shifted by the median wrap-around residual of all bands."""
    centers = sorted(b.center for b in bands)
    ref = centers[len(centers) // 2]
    residuals = sorted(((c - ref + pitch / 2) % pitch) - pitch / 2 for c in centers)
    return ref + residuals[len(residuals) // 2]


def _median_band_height(bands: tuple[Band, ...]) -> float:
    heights = sorted(b.bottom - b.top for b in bands)
    return float(heights[len(heights) // 2])


def _channel_dominant_mask(rgb: Image.Image, dominant: int) -> Image.Image:
    """Mask of pixels where channel ``dominant`` (1=G, 2=B) clearly leads."""
    channels = rgb.split()
    main = channels[dominant]
    others = [c for i, c in enumerate(channels) if i != dominant]
    mask = main.point(lambda v: 255 if v >= _LINK_MIN_LEVEL else 0)
    for other in others:
        lead = ImageChops.subtract(main, other)
        mask = ImageChops.multiply(
            mask, lead.point(lambda v: 255 if v >= _LINK_MARGIN else 0)
        )
    return mask


def _runs_in_band(
    mask: Image.Image, band: Band, layout: TerminalLayout
) -> list[tuple[int, int]]:
    """Horizontal runs of masked pixels within a band, merging 1-2 px gaps."""
    strip = mask.crop(
        (layout.content_left, band.top, layout.content_right, band.bottom)
    )
    profile = list(strip.resize((strip.width, 1), Image.BOX).getdata())
    runs: list[list[int]] = []
    for x, value in enumerate(profile):
        if not value:
            continue
        abs_x = layout.content_left + x
        if runs and abs_x - runs[-1][1] <= 2:
            runs[-1][1] = abs_x
        else:
            runs.append([abs_x, abs_x])
    return [(a, b) for a, b in runs]


def _mid(run: tuple[int, int]) -> int:
    return (run[0] + run[1]) // 2

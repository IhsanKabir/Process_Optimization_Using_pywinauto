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

# Brightness step between horizontal neighbours that marks a glyph edge.
_EDGE_THRESHOLD = 30
# Fewer edge pixels than this in a row = no text (highlight/cursor sides).
_MIN_EDGES_PER_TEXT_ROW = 3.5
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
    # Glyph edges, not "differs from background": a selection highlight or
    # any other uniform block has no edges inside it, so text lines stay
    # separate even when the copy's Ctrl+A highlight is still on screen.
    ink = _edge_mask(rgb)

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
    rows: list[OptionRow],
    total_options: int,
    ordinal: int,
    viewport: str,
    all_visible: bool = False,
) -> Optional[OptionRow]:
    """Pick pricing option ``ordinal``'s action row from the visible ``rows``.

    Rows are counted, not matched by Y: a Y prediction needs an anchor line,
    and anything drawn above the first text line (tab strip, icons) or an
    unknown scroll position shifts it. ``viewport`` says which end of the
    output is on screen:

    * ``"top"``: visible rows are options 1, 2, 3... in order.
    * ``"bottom"``: the last visible row is the last option; count back.

    With ``all_visible`` (the output fits the terminal) the row count must equal
    ``total_options``; a mismatch means a row was missed or misread, so nothing
    is returned rather than risk clicking another option.
    """
    if not rows or not 0 <= ordinal < total_options or len(rows) > total_options:
        return None
    if all_visible and len(rows) != total_options:
        return None
    if viewport == "bottom":
        index = len(rows) - (total_options - ordinal)
    else:
        index = ordinal
    return rows[index] if 0 <= index < len(rows) else None


# ── internals ───────────────────────────────────────────────────────────────


def _pixel_values(img: Image.Image):
    """Flat pixel values; Pillow 12 renamed getdata (removed in Pillow 14)."""
    flat = getattr(img, "get_flattened_data", None)
    return flat() if flat else img.getdata()


def _background_color(rgb: Image.Image) -> tuple[int, int, int]:
    """Most common colour, sampled on a reduced copy (nearest keeps exact
    colours) so large terminals stay fast."""
    step = max(1, int((rgb.width * rgb.height / 40_000) ** 0.5))
    sample = rgb.reduce(step) if step > 1 else rgb
    colors = sample.getcolors(sample.width * sample.height)
    return max(colors)[1]


def _edge_mask(rgb: Image.Image) -> Image.Image:
    """Pixels whose brightness differs sharply from their right neighbour."""
    gray = rgb.convert("L")
    shifted = ImageChops.offset(gray, -1, 0)
    edges = ImageChops.difference(gray, shifted)
    # offset() wraps the first column onto the last; blank that column.
    edges.paste(0, (gray.width - 1, 0, gray.width, gray.height))
    return edges.point(lambda v: 255 if v > _EDGE_THRESHOLD else 0)


def _content_columns(ink: Image.Image) -> tuple[int, int]:
    """Columns between the borders, and blank out border/scrollbar columns.

    Border and scrollbar edges are lit in nearly every row; a text column
    never is (blank lines break it). Those columns are zeroed in ``ink`` so
    they cannot merge every row into one band, and the content area is the
    span between the outermost of them in each half.
    """
    profile = list(_pixel_values(ink.resize((ink.width, 1), Image.BOX)))
    limit = 255 * _BORDER_COLUMN_SHARE
    lit = [x for x, value in enumerate(profile) if value > limit]
    for x in lit:
        ink.paste(0, (x, 0, x + 1, ink.height))
    half = len(profile) / 2
    left = max((x + 1 for x in lit if x < half), default=0)
    right = min((x for x in lit if x >= half), default=len(profile))
    return left, right


def _text_bands(ink: Image.Image) -> tuple[Band, ...]:
    """Runs of rows with text. A row needs a few edge pixels: the sides of a
    highlight or cursor block contribute only two per row."""
    # Row sums from a float-mode resize, so a single edge pixel is not lost
    # to rounding on wide terminals.
    sums = ink.convert("F").resize((1, ink.height), Image.BOX)
    edges_per_row = [v * ink.width / 255 for v in _pixel_values(sums)]
    is_text = [count >= _MIN_EDGES_PER_TEXT_ROW for count in edges_per_row]
    bands: list[Band] = []
    start = None
    for y, value in enumerate(is_text + [False]):
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
    profile = list(_pixel_values(strip.resize((strip.width, 1), Image.BOX)))
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

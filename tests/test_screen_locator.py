"""Tests for screen_locator using a real Smartpoint FS screenshot.

fs_options_terminal.png is the SmartRichTextBox area of an FS result with four
pricing options, captured on a 1920x1080 display where the terminal renders at
14 px per line (the app's old fixed assumption was 20 px).
"""

import os

import pytest
from PIL import Image

from screen_locator import (
    analyze_terminal,
    find_option_rows,
    line_center_y,
    select_option_row,
    text_line_count,
    visible_line_count,
)

FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures", "fs_options_terminal.png")

# D glyph centres measured by hand on the fixture (fixture pixel coordinates).
EXPECTED_D = [(443, 131), (443, 201), (443, 271), (443, 355)]

# Copied text for the same screen: line 0 is the ">" prompt, line 9 is the
# first «BOOK» row (see the fixture).
FS_TEXT = "\n".join(
    [
        ">",
        "",
        "TTL OF 4   PRICING OPTIONS AND 13    ITINERARY OPTIONS RETURNED",
        "",
        "PRICING OPTION 1                  TOTAL AMOUNT          34797 BDT",
        "ADT                               TAX INCLUDED",
        "1   BS    205  I  12NOV DAC MAA   1045  1255    TH   738    IBMAAO",
        "2   UL    128  S  12NOV MAA CMB   1555  1715    TH   320     SOWIZ",
        "3   UL    225  S  12NOV CMB DXB   1840  2150    TH   332     SOWIZ",
        "\xabBOOK\xbb    +TQ                                         D  R  +5",
    ]
)


@pytest.fixture(scope="module")
def screen():
    return Image.open(FIXTURE).convert("RGB")


def _scaled(img, factor):
    size = (round(img.width * factor), round(img.height * factor))
    return img.resize(size, Image.NEAREST)


def _close(actual, expected, tol=4):
    return abs(actual[0] - expected[0]) <= tol and abs(actual[1] - expected[1]) <= tol


def test_measures_real_line_pitch(screen):
    layout = analyze_terminal(screen)

    assert layout.line_pitch == pytest.approx(14, abs=0.5)
    assert layout.background == (78, 78, 78)


def test_finds_every_d_button_in_order(screen):
    rows = find_option_rows(screen, analyze_terminal(screen))

    assert len(rows) == 4
    for row, expected in zip(rows, EXPECTED_D):
        assert _close(row.d, expected), (row.d, expected)


def test_finds_book_and_r_on_the_same_rows(screen):
    rows = find_option_rows(screen, analyze_terminal(screen))

    for row in rows:
        assert row.book is not None and row.book[0] < 80
        assert abs(row.book[1] - row.d[1]) <= 2
        assert row.r is not None and row.d[0] < row.r[0] < row.d[0] + 40


def test_bigger_screen_scales_without_calibration(screen):
    big = _scaled(screen, 1.5)

    layout = analyze_terminal(big)
    rows = find_option_rows(big, layout)

    assert layout.line_pitch == pytest.approx(21, abs=1)
    assert len(rows) == 4
    for row, (x, y) in zip(rows, EXPECTED_D):
        assert _close(row.d, (x * 1.5, y * 1.5), tol=6)


def test_line_center_matches_rendered_row(screen):
    layout = analyze_terminal(screen)

    book_row_y = line_center_y(layout, FS_TEXT, 9)
    prompt_y = line_center_y(layout, FS_TEXT, 0)

    assert book_row_y == pytest.approx(EXPECTED_D[0][1], abs=3)
    assert prompt_y == pytest.approx(5, abs=4)


def test_select_option_row_top_counts_from_first(screen):
    rows = find_option_rows(screen, analyze_terminal(screen))

    row = select_option_row(rows, 4, 2, "top", all_visible=True)

    assert _close(row.d, EXPECTED_D[2])


def test_select_option_row_ignores_tab_strip_above_text(screen):
    # A tab strip/icon band drawn above the first text line used to shift a
    # Y-anchored prediction by a line; counting rows is unaffected.
    shifted = Image.new("RGB", (screen.width, screen.height + 20), (78, 78, 78))
    shifted.paste(screen, (0, 20))
    shifted.paste((230, 230, 230), (5, 3, 200, 15))
    rows = find_option_rows(shifted, analyze_terminal(shifted))

    row = select_option_row(rows, 4, 3, "top", all_visible=True)

    assert _close(row.d, (EXPECTED_D[3][0], EXPECTED_D[3][1] + 20))


def test_select_option_row_refuses_row_count_mismatch(screen):
    rows = find_option_rows(screen, analyze_terminal(screen))

    # Text says 5 options all fit on screen, but only 4 rows were found.
    assert select_option_row(rows, 5, 1, "top", all_visible=True) is None
    # More rows on screen than options in the text: misread.
    assert select_option_row(rows, 3, 0, "top") is None


def test_select_option_row_bottom_counts_back_from_last(screen):
    rows = find_option_rows(screen, analyze_terminal(screen))
    # Output with 6 options where only the last 4 are visible after PageDown.

    assert _close(select_option_row(rows, 6, 5, "bottom").d, EXPECTED_D[3])
    assert _close(select_option_row(rows, 6, 2, "bottom").d, EXPECTED_D[0])
    assert select_option_row(rows, 6, 1, "bottom") is None


def test_visible_and_text_line_counts(screen):
    layout = analyze_terminal(screen)

    assert visible_line_count(layout, screen.height) == 920 // 14
    assert text_line_count(FS_TEXT + "\n\n\n") == 10
    assert text_line_count("   \n") == 0


def _with_selection_highlight(img, color=(51, 153, 255)):
    """Repaint the background of the text block like a Ctrl+A selection."""
    out = img.copy()
    px = out.load()
    for y in range(0, 460):
        for x in range(10, 500):
            if px[x, y] == (78, 78, 78):
                px[x, y] = color
    return out


def test_pitch_survives_selection_highlight(screen):
    layout = analyze_terminal(_with_selection_highlight(screen))

    assert layout.line_pitch == pytest.approx(14, abs=0.5)


def test_empty_terminal_has_no_rows_or_pitch():
    blank = Image.new("RGB", (400, 300), (78, 78, 78))

    layout = analyze_terminal(blank)

    assert layout.line_pitch is None
    assert find_option_rows(blank, layout) == []
    assert line_center_y(layout, FS_TEXT, 9) is None


def test_light_theme_is_detected():
    # White background, standard link blue D/R, green BOOK: synthetic rows.
    img = Image.new("RGB", (500, 200), (255, 255, 255))
    for top in (20, 40, 60, 80):
        for x in range(10, 300, 9):  # dark text runs
            img.paste((0, 0, 0), (x, top, x + 6, top + 10))
    for top in (100, 160):
        img.paste((0, 160, 0), (10, top, 50, top + 10))  # «BOOK»
        img.paste((0, 102, 204), (420, top, 427, top + 10))  # D
        img.paste((0, 102, 204), (440, top, 447, top + 10))  # R

    rows = find_option_rows(img, analyze_terminal(img))

    assert len(rows) == 2
    assert _close(rows[0].d, (423, 105), tol=1)
    assert _close(rows[1].d, (423, 165), tol=1)


# Live failure (2026-10-07): teal theme, larger font, the copy's selection
# highlight still on screen, and a green "@" (connection marker) mid-row.
HIGHLIGHTED = os.path.join(
    os.path.dirname(__file__), "fixtures", "fs_highlighted_teal.png"
)


def test_highlighted_teal_screen_finds_exactly_the_five_option_rows():
    img = Image.open(HIGHLIGHTED).convert("RGB")

    rows = find_option_rows(img, analyze_terminal(img))

    # «BOOK» rows at y~190, 330, 470, 590, 710; D at x~610, R at x~641.
    assert [round(r.y / 10) * 10 for r in rows] == [190, 330, 470, 590, 710]
    for row in rows:
        assert abs(row.d[0] - 610) <= 6, row
        assert abs(row.r[0] - 641) <= 6, row
        assert row.book[0] < 60


def test_green_marker_mid_row_is_not_a_book_link(screen):
    # A row whose first text is white and which has a green "@" further in
    # must not count as an option row.
    img = screen.copy()
    px = img.load()
    for x in range(60, 66):
        for y in range(120, 128):
            px[x, y] = (0, 181, 85)  # green "@" on an itinerary row (y~124)

    rows = find_option_rows(img, analyze_terminal(img))

    assert len(rows) == 4

"""FS tax-breakdown parsing, checked against real Smartpoint FS screens."""

import pytest

from tax_breakdown_parser import parse_fs_tax_breakdown

FZ_OW = """DXB FZ DAC 145.10LOL7AE1 Q DXBDAC14.51NUC159.61END ROE3.673315
FARE AED590 EQU BDT19850 AE2524 F61683 TP169 ZR169 YQ3089 YR2595
TAXES BDT10229  TOT BDT30079"""

# Round trip: a Q before each fare component plus a journey Q at the end.
FZ_RT = """DXB FZ DAC Q16.55 165.51KRL7AE1 FZ DXB Q16.55 165.52KRL7AE1 Q
DXBDXB33.10NUC397.23END ROE3.673315
FARE AED1460 EQU BDT49120 BD500 OW2500 P71236 P81236 UT4000 AE2524
F61683 TP169 ZR338 E5446 YQ6178 YR5190  TAXES BDT26000  TOT BDT75120"""

EK_RT = """ 2   EK   7005  L  12NOV DXB ZVJ   1500  1715    TH   BUS   LXAAPBD1
DAC EK X/DXB EK AUH 253.50LXAAPBD1 EK X/DXB EK DAC 253.50LXAAPBD1 Q
DACDAC2.60NUC509.60END ROE1.0
FARE USD510.00 EQU BDT63006 BD500 OW2500 P71236 P81236 UT4000 AE2524
F61683 TP169 ZR338 E5446  TAXES BDT14632  TOT BDT77638"""


@pytest.mark.parametrize(
    "text, expected_q",
    [
        (FZ_OW, 14.51),
        (FZ_RT, 66.20),  # 16.55 + 16.55 + 33.10
        (EK_RT, 2.60),
        # Two Q amounts written back to back (MH KUL-DAC capture).
        ("KUL MH DAC Q27.13Q20.00 269.09NBXOWMY NUC316.22END ROE4.054267", 47.13),
        # Q before the component and a journey Q (OD DAC-KUL capture).
        ("DAC OD KUL Q10.00 223.00TOWBSSBD Q DACKUL3.00NUC236.00END ROE1.0", 13.00),
    ],
)
def test_q_sums_every_q_in_the_fare_construction(text, expected_q):
    assert parse_fs_tax_breakdown(text)["q_charge"] == pytest.approx(expected_q)


def test_booking_class_q_in_itinerary_is_not_a_surcharge():
    text = "1   FZ    501  Q  12NOV DXB DAC   0020  0655\n" + FZ_OW

    assert parse_fs_tax_breakdown(text)["q_charge"] == pytest.approx(14.51)


def test_fare_components_plus_q_equal_nuc_total():
    # 165.51 + 165.52 + 66.20 = 397.23 NUC, as printed before END.
    parsed = parse_fs_tax_breakdown(FZ_RT)

    assert 165.51 + 165.52 + parsed["q_charge"] == pytest.approx(397.23)


def test_taxes_and_carrier_charges():
    parsed = parse_fs_tax_breakdown(FZ_RT)

    assert parsed["yq_charge"] == 6178.0
    assert parsed["yr_charge"] == 5190.0
    assert parsed["total_taxes"] == 26000.0
    assert parsed["exchange_rate"] == pytest.approx(49120 / 1460, abs=1e-3)

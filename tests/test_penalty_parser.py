import gc
from pathlib import Path

import openpyxl

from penalty_parser import extract_penalty_section, parse_penalty_text
from penalty_report import generate_penalty_report

RAW_SAMPLE = """
FARES LAST UPDATED 09APR  1:29 A
GF       DAC-MED DEPART 09APR
MPM 3812 EH
**ADDITIONAL TAXES/FEES MAY APPLY**
PUBLIC FARES
     CX    FARE   FARE     C  AP  MIN/    SEASONS...... MR GI DT
           USD     BASIS             MAX
DACMED
  1  GF  460.00R  WCLIT1BD W       3/3M                 R  EH
  2  GF  480.00R  SCLIT1BD S       3/3M                 R  EH

                                                    Close
 16. PENALTIES
UNLESS OTHERWISE SPECIFIED   NOTE - RULE 0100 IN IPRG100
ALSO APPLIES
  CHANGES
    ANY TIME
      CHARGE USD 95.00 FOR REISSUE.
         NOTE -
          CHANGE FEES MUST BE CODED AS OA IN THE TAX FIELD.
    CHARGE USD 190.00 FOR NO-SHOW.
         NOTE -
          PASSENGER WILL BE TREATED AS NO SHOW IF THE
          BOOKING IS NOT CANCELLED AT LEAST 4 HOURS BEFORE
          THE DEPARTURE OF THE FLIGHT.
  CANCELLATIONS
    ANY TIME
      CHARGE USD 150.00 FOR CANCEL/REFUND.
    CHARGE USD 300.00 FOR NO-SHOW.
         NOTE -
          SERVICE CHARGES COLLECTED UNDER CODES
          DU/DV/OC/OA/OB/OD/OE ARE NON-REFUNDABLE.
UNLESS OTHERWISE SPECIFIED
  FOR TICKETING ON/AFTER 26MAR 26
    IF TRAVEL COMMENCES ON/BEFORE 31MAR 27
      FOR TRAVEL ON/BEFORE 31MAR 27
        CHANGES
          CHANGES PERMITTED.
         NOTE -
          FIRST CHANGE PERMITTED FOC UPTO FOUR HOURS BEFORE
          FLIGHT DEPARTURE AND SUBSEQUENT CHANGE AT CHARGE.

 14  GF  324.00   WDSMR3BD W                            R  EH
      END
"""


def test_extract_penalty_section_stops_before_fare_grid_resumes():
    section = extract_penalty_section(RAW_SAMPLE)

    assert section.startswith("16. PENALTIES")
    assert "CHARGE USD 95.00 FOR REISSUE." in section
    assert "14  GF  324.00" not in section


def test_parse_penalty_text_extracts_structured_rules():
    record = parse_penalty_text(
        RAW_SAMPLE,
        airline="GF",
        route="DAC-MED",
        fare_basis="WCLIT1BD",
        rbd="W",
        fare_amount=460.0,
        journey_type="RT",
    )

    assert record["fare_basis"] == "WCLIT1BD"
    assert len(record["rules"]) == 5

    change_rule = next(
        rule
        for rule in record["rules"]
        if rule["category"] == "CHANGES" and rule["amount"] == 95.0
    )
    assert change_rule["currency"] == "USD"
    assert change_rule["criteria_text"] == "ANY TIME"
    assert "CHANGE FEES MUST BE CODED AS OA" in change_rule["note_text"]

    no_show_refund_rule = next(
        rule
        for rule in record["rules"]
        if rule["category"] == "CANCELLATIONS" and rule["amount"] == 300.0
    )
    assert no_show_refund_rule["subtype"] == "no_show"
    assert "NON-REFUNDABLE" in no_show_refund_rule["note_text"]

    permitted_rule = next(
        rule for rule in record["rules"] if rule["status"] == "permitted"
    )
    assert "FOR TICKETING ON/AFTER 26MAR 26" in permitted_rule["criteria_text"]
    assert "FOR TRAVEL ON/BEFORE 31MAR 27" in permitted_rule["criteria_text"]


def test_generate_penalty_report_creates_expected_sheets():
    record = parse_penalty_text(
        RAW_SAMPLE,
        airline="GF",
        route="DAC-MED",
        fare_basis="WCLIT1BD",
        rbd="W",
        fare_amount=460.0,
        journey_type="RT",
    )

    output_path = Path.cwd() / "penalty_report_test.xlsx"
    workbook = None
    try:
        generate_penalty_report([record], str(output_path))

        workbook = openpyxl.load_workbook(output_path, read_only=True, data_only=True)
        assert workbook.sheetnames == [
            "Penalty Summary",
            "Penalty Details",
            "Raw Captures",
        ]
        assert workbook["Penalty Summary"]["A2"].value == "GF"
        assert workbook["Penalty Details"]["D2"].value == "WCLIT1BD"
    finally:
        if workbook is not None:
            workbook.close()
            workbook = None
            gc.collect()
        if output_path.exists():
            output_path.unlink()

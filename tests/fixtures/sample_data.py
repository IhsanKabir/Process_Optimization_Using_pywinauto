"""
Test fixtures and sample data for Travelport automation tests.
"""

# Sample fare display output (FD command)
SAMPLE_FD_OUTPUT = """FARES LAST UPDATED 14MAR 17:04 P
BG        DAC CGP DEPART 14MAR
**ADDITIONAL TAXES/FEES MAY APPLY**
PUBLIC FARES
BDT CURRENCY FARES EXIST
    CX   FARE   FARE   C AP MIN/    SEASONS...... MR GI DT
         USD    BASIS       MAX
DACCGP
  1 -BG  100.00   YOW      Y                            R  EH
  2  BG  200.00R  JRT      J                            R  EH
  3 -BG  150.00   COW      C                            R  EH
  4  BG  80.00    NOW      N                            R  EH
END"""

# Sample FD output with multiple pages
SAMPLE_FD_OUTPUT_MULTI_PAGE = """FARES LAST UPDATED 14MAR 17:04 P
BG        DAC MLE DEPART 14MAR
**ADDITIONAL TAXES/FEES MAY APPLY**
PUBLIC FARES
    CX   FARE   FARE   C AP MIN/    SEASONS...... MR GI DT
         USD    BASIS       MAX
DACMLE
  1  BG  300.00   FOW      F                            R  EH
  2  BG  600.00R  FRT      F                            R  EH
«More Fares»
  3  BG  250.00   AOW      A                            R  EH
  4  BG  500.00R  ART      A                            R  EH
END"""

# Sample FTAX list output
SAMPLE_FTAX_LIST = """THE FOLLOWING TAX ASSESSMENTS APPLY TO SINGAPORE:
AIRPORT DEVELOPMENT LEVY                >FTAX-SG/L7·
AVIATION LEVY                           >FTAX-SG/OP·
PASSENGER SERVICE CHARGE                >FTAX-SG/SG·
END"""

# Sample FTAX detail output
SAMPLE_FTAX_DETAIL = """FTAX-SG/L7
L7 - AIRPORT DEVELOPMENT LEVY
TAX RATE
    DEPARTURES FROM CHANGI SIN
    INTERNATIONAL DEPARTURES FROM
    TERMINAL 1 2 3
    -TKT/TVL ON/BEFORE 31MAR25              SGD 46.40
    -TKT ON/AFTER 01JAN25 AND
     TVL ON/AFTER 01APR25 AND
     ON/BEFORE 31MAR27                       SGD 46.40
    TLV ON/AFTER 01APR27 AND
     ON/BEFORE 31MAR28                       SGD 49.40
    TVL ON/AFTER 01APR28 AND
     ON/BEFORE 31MAR29                       SGD 52.40
    TVL ON/AFTER 01APR29 AND
END"""

# Sample FS output (flight shopping with pricing options)
SAMPLE_FS_OUTPUT = """FS DACCGP 15MAR/BG
PRICING OPTION 1
  1 BG 123  DAC CGP 15MAR 1000A 1130A
BASE FARE: BDT 5000
TAXES: BDT 1500
TOTAL: BDT 6500
«BOOK»  D  R  +TQ
PRICING OPTION 2
  1 BG 456  DAC CGP 15MAR 1500P 1630P
BASE FARE: BDT 5500
TAXES: BDT 1500
TOTAL: BDT 7000
«BOOK»  D  R  +TQ
END"""

# Sample config.json for testing
SAMPLE_CONFIG = {
    "commands_file": "commands.txt",
    "excel_output_filename": "fare_report_{date}.xlsx",
    "rbd_sort_order": ["F", "A", "J", "C", "D", "Y", "B", "M", "H", "K", "Q"],
    "domestic_airports": ["DAC", "CGP"],
    "airline_names": {
        "BG": "Biman Bangladesh",
        "BS": "US-Bangla"
    },
    "city_names": {
        "DAC": "Dhaka",
        "CGP": "Chittagong",
        "MLE": "Male"
    },
    "tax_airports": {
        "SIN": {"country": "SG", "name": "Singapore"},
        "MLE": {"country": "MV", "name": "Maldives"}
    }
}

# Sample commands
SAMPLE_COMMANDS = [
    "FDDACCGP/BG",
    "FDDACMLE/BG",
    "FDDACMLE/BS"
]

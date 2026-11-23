# TravelportAuto Fare Report – Rules (v1.5.36)

You are reading or checking an Excel fare report made by TravelportAuto. The app reads airline fares and taxes from the Travelport Smartpoint terminal. Use these rules to read the report, check its numbers, or rebuild it. All amounts are per adult passenger.

## 1. Data sources
- **FD (fare display):** published fares for each booking class (RBD), one-way (OW) and round-trip (RT), in the fare's currency (for example USD or THB). FD shows the fares for **travel today**.
- **FS (flight shopping), with its "D" detail screen:** the taxes for one priced option of the same airline and route:
  - **FARE / EQU:** the base fare, and the same fare in BDT. **R** (the BDT exchange rate) = EQU ÷ FARE.
  - **YQ, YR:** carrier surcharges, in BDT.
  - **T (TAXES):** total taxes, in BDT. T includes YQ and YR.
  - **TOT:** Smartpoint's ticket total.
  - **Q:** surcharges in the fare construction line, in NUC (= USD). Several Q amounts are added together. Q is part of the fare, not part of TAXES. In BDT: **Q(BDT) = Q × ROE × R**, where ROE is the IATA rate of exchange from the same screen.
- **FS travel dates:**
  - By default, FS tries 7 consecutive days starting 30 days from today, then 7 days starting 90 days from today.
  - It checks only the first FS page of each date. It stops at the first date that has an option flown only by that airline. It never pages with "more flights"; it moves to the next date instead.
  - The user can replace these dates with their own (the "FS dates" box, or `--fs-dates`):
    - `15DEC..22DEC`, `15DEC-22DEC`, `10JAN`, `2026-12-15..2026-12-22`, or `+45..+50` (days from today);
    - separate several with commas; they are tried in the order given.
    - Past dates, dates more than 331 days ahead, and more than 60 dates in total are refused before the run starts.
- Route keys look like `BS_DAC-BKK` (airline_origin-destination). Domestic airports are DAC, CGP, ZYL and CXB.

## 2. Order (on every sheet)
- **Airlines:** BS (US-Bangla) first, BG (Biman) second, then all others A→Z.
- **Routes:** grouped by international airport. The outbound leg (DAC→BKK, title "→") comes before the inbound leg (BKK→DAC, title "←"), because DAC is the hub. When one city is served from several domestic airports, they are listed in the order DAC, CGP, ZYL, CXB.
- **Booking classes:**
  - Upper cabins (First, Business) come first, then a blank row, then economy.
  - Within each group, classes are sorted by highest fare first.
  - Unsaleable fares come last and are labelled "X (Unsaleable)".
  - The cabin of each class is set per airline (for example, BG Business = J C D R Z).

## 3. Formulas (Individual Tables sheet)
R = BDT exchange rate; YQ, YR and T are in BDT; Q is in BDT as defined above.

| Column | Formula |
|---|---|
| With YQ/OW | OW + (YQ + YR) ÷ R |
| OW Gross | Route starting at DAC: **OW × R + T + Q** (in BDT). Other origins: OW + (T + Q) ÷ R (in the fare currency) |
| With YQ/RT | RT + 2 × (YQ + YR) ÷ R |
| RT Gross | Route starting at DAC: **RT × R + T_rt** (in BDT). Other origins: RT + T_rt ÷ R |

- **T_rt** = G_out + G_return + 2 × (YQ + YR of the starting leg) + Q of the starting leg, once.
  - G is the government taxes of a leg: T − YQ − YR.
  - Carrier charges follow where the ticket starts, so the return leg's own YQ/YR is replaced by the starting leg's.
  - India's K3 is removed when the journey does not start in India.
- **Q is added once per ticket, and only to Gross.** It is never added to the With YQ columns, and it is not doubled on RT. This is what makes Gross match Smartpoint's TOT.
- **Gross check:**
  - The report takes the class FS actually priced and compares that class's OW Gross with Smartpoint's TOT.
  - The class is found from the **fare basis** FS priced, matched to the FD fare with that fare basis. It is not taken from the booking class of the first flight: Saudia MED-DAC books the MED-JED flight in B but prices fare basis QAOTSAB4, the Q fare. Only if no FD fare has that fare basis is the booking class used.
  - If the two differ by more than 1%, the table title shows: "⚠ check: FS priced X for DDMMM at BDT n; today's X fare gives BDT m".
  - The usual reason is the **date**: FD fares are for travel today, while FS prices a later date, where the airline may charge a different fare (season, peak days). Example: US-Bangla DAC-DOH class I was USD 265 today, but FS priced USD 375 for 02DEC. A warning is therefore a price difference for that date, not an error in the report's fares.
- **Fares in a different currency:** if the FD fares are in one currency and FS priced in another (for example TG BKK-DAC: THB fares, USD pricing), the FD fares are converted with the same day's rate for their currency, taken from another route in the same run.

## 4. Never show figures built from incomplete data
- A With YQ or Gross figure is shown only when all of its inputs are present. If any input is missing, those columns are left out of that table (not filled with zero or a guess). The table title turns red: "⚠ INCOMPLETE – re-run: <what is missing>".
- These count as missing:
  - no tax breakdown captured;
  - no total tax;
  - no FARE/EQU line, so no real exchange rate (the default rate of 1.0 is never used);
  - FD and FS in different currencies with no same-day rate available;
  - Q present but no ROE on a fare that is not in USD;
  - for RT Gross only, the return leg is missing or incomplete.
- **Exception: return routes with no fares.** If Smartpoint showed no fares for the return direction (for example US-Bangla DOH-ZYL), nothing is missing:
  - the outbound table is not marked INCOMPLETE; it simply has no RT Gross column;
  - the return route is not listed for re-run, because re-running it would not help.
  - The report remembers these routes, so later re-runs don't list them either.
- Every other incomplete route, plus any return route that was never fetched, is listed on the **Re-run Needed** sheet.

## 5. Sheets (in order)
1. **Side-by-Side Comparison:**
   - One block per destination and direction. Columns: RBD, then OW and RT for each airline.
   - The block title shows the city, code and currency.
   - Each block starts with a legend; the header rows stay frozen.
2. **Re-run Needed** (only present when something is missing):
   - Columns: Airline, Route, Airline Name, Missing (the reason), Route filter, Airline filter.
   - The GUI's "Re-run missing" button reads this sheet.
3. **Individual Tables:**
   - One table per airline and route, side by side, with one empty column between tables.
   - Title row: "Airline / DAC-BKK", plus any warning (INCOMPLETE, or the gross check).
   - Summary row: "Charges (BDT): YQ YR Q | Taxes (BDT): each tax code | Total Tax (BDT) | Baggage".
   - Columns: RBD, OW, With YQ/OW, OW/Gross, RT, With YQ/RT, RT/Gross. The With YQ and Gross columns appear only when their data is complete. RT/Gross is also left out when the return direction has no fares.
4. **Currency Conversion:** today's date, then "1 XXX | Exchange Rate To BDT" (6 decimals), one row per fare currency.
5. **YQ-YR-Q Charges:**
   - Only routes that have surcharges are included.
   - Amounts are in the fare's currency: YQ ÷ R, YR ÷ R, Q × ROE, plus a total.
6. **Tax Breakdowns:**
   - Only routes with tax data are included.
   - Columns: Tax/Charge | Amount (BDT) | Original (the fare's currency, = BDT ÷ R).
   - Rows: YQ, YR, Q, Charges Subtotal, each tax code A→Z, then Total Taxes and Total Amount.
7. **Changes Summary** (only when there are changes):
   - Columns: Route, RBD, Change, Old/New OW, Old/New RT.
   - Each row has a "View →" link to the matching cell on the comparison sheet.
- A hidden sheet, `_run_info`, stores the report's route list, its change markers and the routes with no fares. Re-run missing uses it to update the report. Don't edit or delete it.

## 6. Change markers (compared with the previous run)
- Fares are real numbers that Excel can add up. The marker is part of the cell's number format only:
  - ↑ increased: red. Used when OW, or RT, went up.
  - ↓ decreased: green.
  - NEW: yellow, for a class that wasn't there before.
  - SOLD OUT: grey, for a class that disappeared. The cell shows the old fare.

## 7. Files
- File name: `fare_report_YYYY-MM-DD_HHMM.xlsx`. A run that is stopped early saves `..._partial.xlsx`.
- **Re-run missing** fetches only the listed airline/route pairs and writes them back into the **original report**:
  - The previous version is first copied to `reports\backup` (`<name>_before_rerun_HHMMSS.xlsx`).
  - Routes that were not re-run keep their change markers. A re-run route gets new markers only if its fares changed since the original run.
  - It writes a new file instead if the original is open in Excel, was made before v1.5.34, or a route's saved screens are missing. Close the report in Excel before re-running.
- Re-run and Resume never save the same routes to the database twice.

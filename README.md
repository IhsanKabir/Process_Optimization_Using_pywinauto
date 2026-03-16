# Travelport Smartpoint Automation Suite

![Travelport Automation](https://img.shields.io/badge/Automation-Python_UIA-blue)
![Status](https://img.shields.io/badge/Status-Active_Development-success)

A robust, intelligent Python automation toolkit designed to interact directly with **Travelport Smartpoint**. This project eliminates manual data extraction burdens by autonomously navigating the Smartpoint terminal, parsing complex Global Distribution System (GDS) formats, and exporting business-critical data into structured, automated Excel reports.

## 🚀 Key Capabilities

### 1. Automated Fare Extraction (`FD` Commands)
- Automatically drives the Smartpoint terminal to pull comprehensive public, private, and unsaleable fare datasets across requested airline/route combinations.
- **Intelligent Pagination:** Seamlessly navigates complex Fares pagination (e.g. `MD`, `FU*`, overcoming currency loops and handling `END` markers automatically).
- Generates polished, sortable Excel sheets containing `Fare Basis`, `OW/RT`, `Currency`, `Amount`, `Seasons`, `Min/Max` stays, and ticketing details.

### 2. Autonomous Tax Scraping (`FTAX` Commands)
- Navigates through multi-page Travelport terminal tax definitions (`FTAX-{CC}/{CODE}`).
- Intelligently skips verbose exemption pages to accurately locate and parse the crucial `TAX RATE:` blocks.
- Produces detailed Tax Reports grouping taxes by airport explicitly formatting the time/date-range ticket conditions, validities, and distinct transfer/departure amounts.

### 3. Queue Charge (YQ/YR) & Baggage Rule Extraction *(WIP)*
- Captures dynamic surcharges mapped against corresponding routes and fare bases.
- Pulls precise baggage allowances associated directly with specific fare basis codes.

### 4. Dynamic Currency Conversion Integration *(WIP)*
- Normalizes disparate global currencies directly within the reporting pipelines.

## 🛠️ Technology Stack
- **Python 3.10+**: Core extraction and data transformation logic.
- **pywinauto (UIA Base)** & **pyautogui**: Deep GUI inspection and robust macro execution directly targeting the Smartpoint application window.
- **openpyxl**: Complex Excel `.xlsx` generation, formatting, status color-coding, and data layout.
- **Regex Parsing Engine**: Highly customized logic configured strictly for Travelport GDS terminal output idiosyncrasies.

## ⚙️ Requirements & Installation

1. Must be run on a Windows machine actively logged into **Travelport Smartpoint**.
2. Requires a valid, authenticated GDS session with active focus on the primary terminal window.
3. Install dependencies:
```bash
pip install -r requirements.txt
```

## 🎮 Usage 

The orchestrator `main.py` is entirely configurable via `config.json`.

**Full Auto Extraction (Fares):**
```bash
python main.py --auto
```

**Tax Only Extraction (FTAX):**
```bash
python main.py --tax --auto
```

**Testing Limits:**
```bash
python main.py --tax --auto --limit 1
```

## 🏗️ Architecture Design 

* `main.py`: The core orchestrator managing the run loop, configuration loading, and saving final snapshots.
* `smartpoint_automation.py`: The workhorse. Interacts directly with the live terminal manipulating the clipboard buffer to extract screen states. It implements complex algorithms to defeat infinite loops, detect stuck pages, handle fallback navigation (Tab vs Direct commands), and recognize Smartpoint prompts instantly.
* `fare_parser.py` & `tax_parser.py`: Transforms raw, cryptic GDS strings into structured python dicts via extensive regular expressions.
* `report_generator.py` & `tax_report.py`: Ingests structured python dicts and executes dynamic Excel styling, conditional logic, and tab management.

## 📝 License
Proprietary - Internal Corporate Use Only.

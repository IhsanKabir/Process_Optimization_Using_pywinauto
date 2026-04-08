# Travelport Auto-Extractor User Guide

Welcome! This application automates the extraction and compilation of Fare and Tax data directly from your Smartpoint terminal.

## 1. Prerequisites
Before running the extractor, you must have the following prepared:

1. **Travelport Smartpoint** must be installed and actively open on your computer.
2. **Log In:** You must be fully logged into your Travelport terminal with an active session.

## 2. Installation & Setup
You do not need to install Python or any complicated software.

When you download your package from our website, extract the `.zip` file into a folder on your computer (e.g. `Desktop/TravelportAuto`).

Inside, you will find:
- **`TravelportAuto.exe`** (The application)
- **`config.json`** (Your configuration rules)
- **`commands.txt`** (Your list of search commands)

## 3. Configuring Your Search
If you want to customize your searches (e.g., adding a new route like `DAC-MCT`):
1. Open `commands.txt` with Notepad.
2. Add the command line directly to the file, using the format `FD{ORIGIN}{DEST}/{AIRLINE}` (e.g. `FDDACMCT/BG`).
3. Save the file.

*(Note: Advanced setup options such as configuring user login details and default limits are managed via your website profile and the included `config.json` file).*

## 4. Running the Extractor

**The Easy Way (Full Run):**
Simply double-click the `TravelportAuto.exe` file! 
It will automatically connect to your open Smartpoint terminal and run through all the routes configured in your `commands.txt` file. Please do not touch your mouse or keyboard while the terminal is rapidly searching.

**The Advanced Way (Command Prompt):**
If you want to use the advanced filtering tools (like searching a single route instead of the whole file), open your Command Prompt (`cmd`) in that folder and run:
- `TravelportAuto.exe --route dac-mct` (Runs only specific routes)
- `TravelportAuto.exe --only-fd` (Skips the slower tax/YQ extraction)

## 5. Locating Your Data
When the tool finishes, it will pause and say `Press Enter to exit...`
Inside the same folder where your `.exe` is located, a new `data/reports/` folder will be created.

1. Open `data/reports/fare_report_XXXX.xlsx`
2. You will find all your data neatly organized into Tabs (Side-by-Side Comparison, Individual Tables, Currency Conversion, Tax Breakdowns).

If you encounter any errors or missing data, check the `data/logs/` folder and provide the `.log` file to our support team for troubleshooting!

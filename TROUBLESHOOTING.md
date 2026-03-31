# Troubleshooting Guide

## Common Issues and Solutions

### Installation & Setup

#### Issue: Missing dependencies
**Error**: `ModuleNotFoundError: No module named 'pywinauto'`

**Solution**:
```bash
pip install -r requirements.txt
```

#### Issue: Config file not found
**Error**: `Configuration error: Config file not found: config.json`

**Solution**:
1. Copy the example config:
   ```bash
   cp config.dev.json.example config.json
   ```
2. Edit `config.json` with your settings

---

### Connection Issues

#### Issue: Cannot connect to Smartpoint
**Error**: `Window 'Application Window 1' not found`

**Solution**:
1. Ensure Smartpoint is running
2. Check the window title matches (use Task Manager to verify)
3. If title is different, update `DEFAULT_WINDOW_TITLE` in `constants.py` or pass custom title to SmartpointAutomation

#### Issue: Login fails
**Error**: `Login failed` or credentials rejected

**Solution**:
1. Verify credentials are set correctly:
   ```powershell
   $env:SMARTPOINT_USERNAME="your_username"
   $env:SMARTPOINT_PASSWORD="your_password"
   ```
2. Check PCC if required:
   ```powershell
   $env:SMARTPOINT_PCC="your_pcc"
   ```
3. Try manual login first to verify credentials work

---

### Clicking & UI Interaction Issues

#### Issue: D button clicks fail
**Error**: D-click does not expand tax details, or clicks wrong location

**Possible Causes & Solutions**:

1. **Screen DPI scaling**:
   - Check Windows Display Settings
   - Ensure scaling is set to 100%
   - If using different scaling, constants may need recalibration

2. **Window not at normal size**:
   - Don't maximize or minimize the Smartpoint window
   - Use normal/restored window state

3. **Font size changed**:
   - Verify terminal font hasn't been modified
   - Reset to default Smartpoint settings

4. **Monitor resolution changed**:
   - The empirical values in `constants.py` are calibrated for specific resolution
   - May need to recalibrate `LINE_HEIGHT` and `D_BUTTON_X_RATIO`

**Calibration Process**:
```python
# 1. Measure LINE_HEIGHT:
# - Open Smartpoint
# - Note Y-coordinate of first line of text
# - Note Y-coordinate of second line
# - LINE_HEIGHT = difference

# 2. Measure D_BUTTON_X_RATIO:
# - Open FS results with D button visible
# - Measure terminal pane width
# - Measure D button X position from left
# - D_BUTTON_X_RATIO = (D_X - terminal_left) / terminal_width
```

#### Issue: Currency link click doesn't work
**Error**: "BDT CURRENCY FARES EXISTS" link not clicked

**Solution**:
- Same calibration issues as D button above
- Check `CURRENCY_LINK_X_RATIO` in `constants.py`
- Verify link text appears in terminal output

---

### Data Extraction Issues

#### Issue: No fares extracted
**Error**: `No fare data could be parsed`

**Possible Causes**:
1. **Terminal returned INVALID**:
   - Check command syntax in `commands.txt`
   - Verify route codes are valid (3 letters each)
   - Ensure airline code is valid (2 characters)

2. **Insufficient wait time**:
   - Terminal may need more time to load
   - Increase `COMMAND_WAIT_*` constants in `constants.py`

3. **Pagination issues**:
   - Check logs for "stuck screen" messages
   - Terminal may not be refreshing properly

**Solution**:
```bash
# Enable debug logging
python main.py --auto 2>&1 | tee debug.log

# Check raw data files
cat data/raw/*.txt
```

#### Issue: Incomplete data (missing pages)
**Error**: Some fares missing from report

**Solution**:
1. Check `MAX_PAGES_FARE` in `constants.py`
2. Increase if needed (default is 10)
3. Review pagination logs for "END" signal detection

---

### Permission & Security Issues

#### Issue: Credentials in shell history
**Warning**: Command-line credentials visible

**Solution**:
- Never use `--username` or `--password` arguments (they've been removed)
- Always use environment variables:
  ```powershell
  $env:SMARTPOINT_USERNAME="user"
  $env:SMARTPOINT_PASSWORD="pass"
  ```
- Or create `.env` file (requires `python-dotenv`)

#### Issue: Config validation fails
**Error**: `ConfigurationError: Invalid airline code`

**Solution**:
1. Check `config.json` against schema in `config_schema.json`
2. Airline codes must be exactly 2 alphanumeric characters
3. Airport codes must be exactly 3 letters
4. Country codes must be exactly 2 letters

---

### Testing & Development Issues

#### Issue: Tests fail
**Error**: `pytest` errors

**Solution**:
```bash
# Install dev dependencies
pip install -r requirements-dev.txt

# Run tests with verbose output
pytest -v

# Run specific test file
pytest tests/test_parser.py -v

# Check coverage
pytest --cov=. --cov-report=html
```

#### Issue: Import errors in tests
**Error**: `ModuleNotFoundError` when running tests

**Solution**:
```bash
# Run pytest from project root
cd /path/to/Process_Optimization_Using_pywinauto
pytest

# Or install package in development mode
pip install -e .
```

---

### Performance Issues

#### Issue: Slow execution
**Symptom**: Commands take very long to complete

**Solutions**:
1. **Reduce scope**:
   ```bash
   # Test with single route
   python main.py --auto --limit 1

   # Test specific airline
   python main.py --auto --airline BG
   ```

2. **Check wait times**:
   - Review `constants.py` timing values
   - May be waiting longer than necessary
   - Try reducing `COMMAND_WAIT_*` values slightly

3. **UI tree caching**:
   - First `descendants()` call is slow (2-5s)
   - Subsequent calls should use cache
   - Check logs for repeated UI tree walks

---

### Output & Reporting Issues

#### Issue: Excel file not created
**Error**: No output file generated

**Solutions**:
1. Check `data/reports/` directory exists
2. Verify write permissions
3. Check if file is locked/open in Excel
4. Review logs for error messages

#### Issue: Changes not detected
**Error**: Change detection shows no changes when there should be

**Solution**:
1. Verify `data/archive/` contains previous snapshot
2. Check snapshot format matches current data format
3. Delete old snapshots if format changed:
   ```bash
   rm data/archive/fare/snapshot_*
   ```

---

## Debug Mode

Enable detailed logging:

```python
import logging
logging.getLogger('travelport').setLevel(logging.DEBUG)
```

Or check log files in `data/logs/`:
```bash
tail -f data/logs/run_*.log
```

---

## Getting Help

If issues persist:

1. Check the logs in `data/logs/`
2. Review raw data files in `data/raw/`
3. Enable debug logging
4. Create issue on GitHub with:
   - Error message
   - Relevant log excerpt
   - Config (without credentials)
   - Python version and OS

---

## Known Limitations

1. **Windows Only**: Uses Windows-specific APIs (pywinauto, ctypes.windll)
2. **Single Instance**: Cannot run multiple automation instances simultaneously
3. **Active Window Required**: Smartpoint must remain focused during execution
4. **Network Dependent**: Requires active GDS connection
5. **Resolution Specific**: Coordinate-based clicking calibrated for specific display settings

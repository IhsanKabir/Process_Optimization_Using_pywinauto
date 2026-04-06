# New Features Documentation

This document describes the three major improvements added to the Travelport Fare Automation Tool.

## 1. Progress Bars & Better Feedback

The automation now shows visual progress bars when processing commands, making it easier to track progress during long-running extractions.

### Features

- **Visual Progress Tracking**: Uses `tqdm` library to display real-time progress bars
- **Command-by-Command Updates**: Shows which command is currently being processed
- **ETA Display**: Automatically calculates estimated time remaining
- **Works in Multiple Modes**: Progress bars appear for:
  - Fare extraction (FD commands)
  - Tax extraction (FTAX commands)
  - Route data processing

### How to Use

Progress bars are enabled automatically when `tqdm` is installed:

```bash
pip install tqdm
python main.py --auto
```

If `tqdm` is not available, the tool falls back to standard text logging.

### Example Output

```
Executing commands: 100%|███████████████████| 50/50 [05:23<00:00,  6.47s/cmd]
Processing routes: 100%|██████████████████| 50/50 [00:12<00:00,  4.01route/s]
```

---

## 2. Checkpoint/Resume Functionality

Long-running extractions can now be interrupted and resumed without losing progress. The tool saves checkpoints periodically so you can pick up where you left off.

### Features

- **Automatic Progress Saving**: Saves checkpoint every 10 commands
- **Resume from Interruption**: Continue from last checkpoint if process fails or is stopped
- **Skip Completed Commands**: Automatically skips already-extracted commands when resuming
- **Failed Command Tracking**: Keeps track of which commands failed for reporting

### How to Use

#### Enable Checkpoint Mode

```bash
# Enable checkpoint mode (saves progress)
python main.py --auto --checkpoint
```

This creates checkpoint files in `data/checkpoints/` directory.

#### Resume from Checkpoint

If your extraction is interrupted, resume it with:

```bash
# Resume from the latest checkpoint
python main.py --auto --resume data/checkpoints/checkpoint_2026-04-06_1440.json
```

Or let the tool find the latest checkpoint automatically:

```bash
# Find and resume from latest checkpoint
python main.py --auto --checkpoint
```

### Checkpoint File Structure

Checkpoint files are JSON files containing:

```json
{
  "session_start": "2026-04-06T14:40:08.123456",
  "last_updated": "2026-04-06T14:55:12.789012",
  "completed_commands": ["FDDACMLE/BG", "FDDACDOH/BG"],
  "failed_commands": ["FDDACJFK/BG"],
  "total_completed": 2,
  "total_failed": 1
}
```

### Use Cases

**Perfect for:**
- Long-running extractions (100+ commands)
- Unstable network connections
- Testing new routes where failures are expected
- Large-scale data collection

**Example Workflow:**

```bash
# Start extraction with checkpoint
python main.py --auto --checkpoint --limit 500

# If interrupted, resume from checkpoint
python main.py --auto --resume data/checkpoints/checkpoint_2026-04-06_1440.json

# Continue until all commands complete
```

---

## 3. Data Validation & Sanity Checks

The tool now validates extracted data to catch quality issues early, preventing bad data from reaching reports.

### Features

#### Fare Amount Validation

- Checks that fares are positive (> 0)
- Warns about unusually high fares (> $50,000 or local equivalent)
- Validates fare amounts against reasonable ranges

#### Currency Code Validation

- Validates currency codes against ISO 4217 standard
- Checks format (must be 3 uppercase letters)
- Warns about unrecognized currency codes
- Supports 90+ common aviation currencies

#### Required Field Checks

- Validates that required fields are present:
  - RBD (Reservation Booking Designator)
  - Airline code
  - Fare basis code
- Warns when expected fields are missing

#### Data Format Validation

- Checks RBD format (should be single letter)
- Handles special formats like "Y (Unsaleable)"
- Validates airline codes (2 alphanumeric characters)

### How to Use

#### Enable Validation (Default)

Validation is enabled by default:

```bash
python main.py --auto
```

#### Disable Validation

To skip validation checks:

```bash
python main.py --auto --no-validation
```

### Validation Output

#### Warning Example

```
  [VALIDATION] Fare amount 75000.0 USD seems unusually high (max: 50000)
  [VALIDATION] Currency code 'XXY' is not recognized (might be valid but uncommon)
  [VALIDATION] BG_DAC-MLE: 2/15 fares have validation issues
```

#### Validation Statistics

At the end of parsing, you'll see:

```
  [VALIDATION] Found 3 validation issues in 50 fares
```

### Validation Rules

| Check | Rule | Action |
|-------|------|--------|
| Fare Amount | Must be > 0 | Warn |
| Fare Amount | Must be < $50,000 (or 10M local) | Warn |
| Currency Code | Must be 3 letters | Warn |
| Currency Code | Should be recognized ISO code | Info |
| RBD | Should be present | Warn |
| Airline | Should be present | Warn |
| Fare Basis | Should be present | Warn |

### Programmatic Validation

You can also use validation functions in your own scripts:

```python
from validators import (
    validate_fare_amount,
    validate_currency_code,
    validate_parsed_fares
)

# Validate single fare
is_valid = validate_fare_amount(150.0, "USD", warn_only=True)

# Validate currency
is_valid = validate_currency_code("BDT", warn_only=True)

# Validate entire fare list
stats = validate_parsed_fares(fares, currency="USD")
print(f"Valid: {stats['valid_fares']}, Invalid: {stats['invalid_fares']}")
```

---

## Testing

All new features have comprehensive test coverage:

```bash
# Run validation tests
python -m pytest tests/test_validation_features.py -v

# Run checkpoint tests
python -m pytest tests/test_checkpoint_manager.py -v

# Run all tests
python -m pytest tests/ -v
```

---

## Configuration

### Environment Variables

No new environment variables required. All features work with existing configuration.

### Dependencies

The new features require:

```
tqdm==4.66.1  # For progress bars
```

Install with:

```bash
pip install -r requirements.txt
```

---

## Examples

### Complete Workflow with All Features

```bash
# 1. Start extraction with all features enabled
python main.py --auto --checkpoint

# Progress bars show real-time status
# Checkpoints save every 10 commands
# Validation warnings appear for data issues

# 2. If interrupted, resume from checkpoint
python main.py --auto --resume data/checkpoints/checkpoint_2026-04-06_1440.json

# 3. Disable validation for faster processing (if needed)
python main.py --auto --checkpoint --no-validation

# 4. Review validation warnings in log file
cat data/logs/run_2026-04-06_1440.log | grep VALIDATION
```

### Cleanup Old Checkpoints

Checkpoints accumulate over time. To clean up:

```python
from checkpoint_manager import CheckpointManager

mgr = CheckpointManager('data/checkpoints')
mgr.cleanup_old_checkpoints(keep_recent=5)  # Keep only 5 most recent
```

---

## Troubleshooting

### Progress Bars Not Showing

**Problem**: No progress bars appear during extraction

**Solution**: Install tqdm:
```bash
pip install tqdm
```

### Checkpoint Not Resuming

**Problem**: Tool doesn't skip completed commands when resuming

**Solution**: Ensure you're using the correct checkpoint file:
```bash
# List available checkpoints
ls -lh data/checkpoints/

# Use the most recent one
python main.py --auto --resume data/checkpoints/checkpoint_YYYY-MM-DD_HHMM.json
```

### Too Many Validation Warnings

**Problem**: Getting excessive validation warnings

**Solution**: Either:
1. Fix the data quality issues in the source
2. Disable validation temporarily with `--no-validation`
3. Review validation rules in `validators.py` and adjust thresholds if needed

---

## Performance Impact

| Feature | Performance Impact | Notes |
|---------|-------------------|-------|
| Progress Bars | Negligible (<1%) | Minimal overhead from tqdm |
| Checkpoints | ~2-3% | Saves every 10 commands, minimal I/O |
| Validation | ~5-10% | Can be disabled with `--no-validation` |

**Overall**: Approximately 5-13% slower with all features enabled, but significant UX and reliability improvements.

---

## API Reference

See the following modules for detailed API documentation:

- `checkpoint_manager.py` - Checkpoint/resume functionality
- `validators.py` - Data validation functions
- `main.py` - CLI arguments and integration

For programmatic use, import the modules directly:

```python
from checkpoint_manager import CheckpointManager
from validators import validate_fare_amount, validate_currency_code

# Your code here
```

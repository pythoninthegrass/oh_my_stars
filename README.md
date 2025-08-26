# oh_my_stars

oh_my_stars uses exported Google Takeout maps data for saved places and your places to analyze visited, reviewed, and of course, saved places across space and time.

## Minimum Requirements

* [Python 3.12+](https://www.python.org/downloads/)
* [uv](https://github.com/astral/uv)

## Recommended Requirements

* [mise](https://mise.jdx.dev)

## Setup

### Export Google Maps data

* Navigate to [Google Takeout](https://takeout.google.com/u/1/settings/takeout)
* Create a new export
  * Select data to include
    * Deselect all
    * Choose **Maps (your places)** only
    * Next step
  * Choose file type, frequency & destination
    * Defaults are fine
* Create export
* It will be emailed to you, but can also be downloaded from [Google Takeout Summary](https://takeout.google.com/u/1/manage) once finished

### Extract takeout data

1. **Download your Google Takeout export** - You'll receive a file named like `takeout-YYYYMMDDTHHMMSSZ-1-001.zip`

2. **Place the zip file** in the root directory of this project (same directory as `main.py`)

3. **Extract the data automatically**:
   ```bash
   # Automatically extract and organize takeout data
   uv run main.py extract-takeout
   ```

   **Advanced options:**
   ```bash
   # Specify zip file path explicitly
   uv run main.py extract-takeout --zip-file path/to/takeout.zip
   
   # Delete zip file after successful extraction
   uv run main.py extract-takeout --cleanup
   ```

4. **Verify extraction** - You should now have:
   ```
   takeout/maps/your_places/
   ├── reviews.json        # Your Google Maps reviews (28KB)
   └── saved_places.json   # Your saved places with timestamps (717KB)
   ```

## Quickstart

Once your takeout data is properly organized, run the complete analysis pipeline:

```bash
# Run the full analysis pipeline (default command)
./main.py

# Or explicitly run the pipeline command
uv run main.py run-pipeline
```

This will:
- Extract data from your Google Maps exports
- Correlate photos with geographic regions  
- Generate a comprehensive travel timeline
- Create a summary report at `data/summary_report.md`

## Output

After running the pipeline, you'll find your analysis results in the `data/` directory:

- **`data/summary_report.md`** - Main human-readable analysis report with travel insights
- `data/visit_timeline.json` - Complete chronological visit data
- `data/regional_centers.json` - Geographic clustering results
- `data/saved_places.json` - Processed saved places data
- `data/photo_locations.json` - Photo geolocation correlations
- `data/review_visits.json` - Review visit confirmations

## Architecture

### Module Structure

The project is organized into a modular architecture with the following structure:

```
oh_my_stars/
├── core/              # Core processing modules
│   ├── __init__.py    # Core package initialization
│   ├── takeout.py     # Google Takeout data extraction (planned)
│   ├── places.py      # Location and place processing (planned)  
│   ├── photos.py      # Photo geolocation processing (planned)
│   ├── reviews.py     # Review visit extraction (planned)
│   ├── reports.py     # Timeline and summary generation (planned)
│   └── pipeline.py    # Main pipeline orchestration (planned)
├── utils/             # Supporting utilities
│   ├── __init__.py    # Utils package initialization
│   ├── geocoding.py   # Location geocoding and caching (planned)
│   ├── validation.py  # Data validation and testing (planned)
│   └── helpers.py     # Common utility functions (planned)
└── main.py            # CLI interface and entry point
```

### Design Principles

- **Modular architecture** - Separate concerns into focused modules
- **Read-only operations** - Never modifies source Google Takeout data
- **Resume capability** - Can restart from last completed pipeline step
- **Comprehensive caching** - Geocoding cache prevents redundant API calls

## Development

For development and debugging, individual pipeline steps can be executed independently:

```bash
# Extract takeout zip file (do this first)
uv run main.py extract-takeout

# Extract starred and labeled places data
uv run main.py extract-labeled-places

# Extract saved places with timestamps
uv run main.py extract-saved-places

# Extract photo geolocation metadata
uv run main.py extract-photo-metadata

# Correlate photos to geographic regions
uv run main.py correlate-photos-to-regions

# Extract review visit timestamps
uv run main.py extract-review-visits

# Generate chronological visit timeline
uv run main.py generate-visit-timeline

# Create summary analysis report
uv run main.py generate-summary-report
```

Additional utility commands:
```bash
# Validate data integrity
uv run main.py validate-data

# View geocoding cache statistics
uv run main.py cache-stats

# Clear geocoding cache
uv run main.py cache-clear
```

## TODO

Outstanding tasks can be reviewed in [TODO.md](TODO.md)

## Further Reading

<!-- TODO -->

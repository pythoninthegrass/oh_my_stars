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
# Run the full analysis pipeline
uv run main.py run-pipeline
```

This will:
- Extract data from your Google Maps exports
- Correlate photos with geographic regions  
- Generate a comprehensive travel timeline
- Create summary reports in `data/`

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

<!-- TODO: todo -->
## TODO


<!-- TODO: further reading -->
## Further Reading

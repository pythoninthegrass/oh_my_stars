# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

`oh_my_stars` is a Google Takeout Maps data analysis tool that processes starred locations, saved places, and photo geolocations to generate travel pattern insights. The project is a completed MVP with all 10 planned tasks finished.

## Commands

### Execution

```bash
# Run complete analysis pipeline
uv run main.py run-pipeline

# Individual pipeline steps
uv run main.py extract-labeled-places
uv run main.py extract-saved-places
uv run main.py extract-photo-metadata
uv run main.py correlate-photos-to-regions
uv run main.py extract-review-visits
uv run main.py generate-visit-timeline
uv run main.py generate-summary-report

# Utilities
uv run main.py validate-data
uv run main.py cache-stats
uv run main.py cache-clear
```

### Development

```bash
# Linting
ruff format --check --diff .  # Check formatting
ruff format .                 # Apply formatting

# Documentation
repomix                      # Generate codebase summary
```

## Architecture

### Core Design

- **Single executable**: main.py (3,065 LOC) using PEP 723 inline dependencies
- **Self-contained**: All functionality in one script with `#!/usr/bin/env -S uv run --script`
- **7-step pipeline**: Extract → Correlate → Analyze → Report
- **Read-only operations**: Never modifies source Google Takeout data

### Key Components

- **Geocoding cache**: Prevents redundant Nominatim API calls
- **Regional clustering**: 10-mile radius for grouping locations
- **Multi-source integration**: Starred places, saved places, photos, reviews
- **Resume capability**: Can restart from last completed pipeline step

### Data Flow

```
takeout/maps/ → main.py → data/
├── saved/              ├── *.json (structured)
├── your_places/        └── *.md (reports)
└── photos/
```

### Dependencies

- **Runtime**: Python 3.12+ managed by UV
- **Core**: geopy, python-decouple, sh, httpx, python-dateutil
- **Dev**: ruff (linting), pytest (testing), renovate (updates)

## Configuration

### Linting

#### Ruff

- Line length: 130 characters
- Python target: 3.12
- Enabled: pycodestyle, pyflakes, pyupgrade, bugbear, simplify, isort

#### Markdownlint

- `markdownlint -f -c .markdownlint.jsonc <MARKDOWN_FILE>`

### Project Management

- Task tracking in `/backlog/` directory
- After completing tasks, use project-manager-backlog agent to mark them off
- Completed tasks move to `@backlog/completed/`

## Current TODO Items

1. **Golf `main.py` to <1000 LOC** (currently 3,065 lines)
2. **Remove emoji visual indicators** from output
3. **Fill out README.md** (currently placeholder)

## Development Notes

- Project is in completed MVP state with comprehensive test coverage
- Uses UV for dependency management with locked versions
- Non-destructive analysis - safe to run multiple times
- Generates both structured JSON and human-readable markdown reports

---
title: Extract Saved Places with Timestamps
status: Completed
priority: high
labels: [data-extraction, location-analysis]
---

## Description

Extract saved places from `your_places/Saved Places.json` including their timestamps, and integrate them with the regional grouping system established in task 001.

## Acceptance Criteria

1. **Data Extraction**
   - [x] Successfully parse `takeout/maps/your_places/Saved Places.json`
   - [x] Extract place names, coordinates, and saved timestamps
   - [x] Handle different timestamp formats in the JSON
   - [x] Validate coordinate data and flag invalid entries

2. **Timestamp Processing**
   - [x] Parse timestamps using python-dateutil for flexible format handling
   - [x] Convert all timestamps to ISO 8601 format
   - [x] Track earliest and latest saved dates per region
   - [x] Handle missing or malformed timestamps gracefully

3. **Regional Integration**
   - [x] Match saved places to existing regional centers from task 001
   - [x] For new regions not in labeled places, create new regional entries
   - [x] Update regional center calculations with new place coordinates
   - [x] Maintain separate counts for labeled vs saved places

4. **Output**
   - [x] Generate `data/saved_places.json` with timestamp data
   - [x] Update `data/regional_centers.json` with saved place information
   - [x] Include saved place timestamps in regional summaries
   - [x] Track total saved places and date ranges in metadata

## Technical Requirements

- Dependencies: python-dateutil for timestamp parsing
- Merge with existing regional data without overwriting
- Maintain data integrity between labeled and saved places
- Handle duplicate places (same location in both datasets)

## Example Output Structure

```json
// data/saved_places.json
{
  "metadata": {
    "extraction_date": "2025-01-19T10:00:00Z",
    "total_saved_places": 200,
    "date_range": {
      "earliest": "2015-01-01T00:00:00Z",
      "latest": "2025-01-15T00:00:00Z"
    }
  },
  "places": [
    {
      "id": "saved_001",
      "name": "Golden Gate Bridge",
      "coordinates": {
        "latitude": 37.8199,
        "longitude": -122.4783
      },
      "saved_date": "2020-05-15T14:30:00Z",
      "region": "San Francisco, CA"
    }
  ]
}
```

## Dependencies

- Task 001: Regional centers must be established first

## Estimated Effort

3 hours

## Completion Summary

**Completed on:** 2025-08-19

**Results:**
- Successfully parsed takeout/maps/your_places/Saved Places.json (1,478 entries, 1,230 valid)
- Extracted place names, coordinates, and saved timestamps with python-dateutil
- Converted all timestamps to ISO 8601 format
- Integrated with existing regional centers from task 001 
- Created new regional entries for new locations not in labeled places
- Updated regional center calculations with saved place coordinates
- Generated data/saved_places.json with complete timestamp data
- Updated data/regional_centers.json with integrated labeled + saved place information
- Successfully processed 1,230 saved places across 285 regions
- Date range spans from 1970-01-01 to 2025-08-17
- Optimized geocoding to respect API limits and handle invalid coordinates

The implementation successfully integrated saved places data with the existing regional system, maintaining separate counts for labeled vs saved places while updating regional centers with the combined dataset.
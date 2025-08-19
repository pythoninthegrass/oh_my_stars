---
title: Extract Saved Places with Timestamps
status: To Do
priority: high
labels: [data-extraction, location-analysis]
---

## Description

Extract saved places from `your_places/Saved Places.json` including their timestamps, and integrate them with the regional grouping system established in task 001.

## Acceptance Criteria

1. **Data Extraction**
   - [ ] Successfully parse `takeout/maps/your_places/Saved Places.json`
   - [ ] Extract place names, coordinates, and saved timestamps
   - [ ] Handle different timestamp formats in the JSON
   - [ ] Validate coordinate data and flag invalid entries

2. **Timestamp Processing**
   - [ ] Parse timestamps using python-dateutil for flexible format handling
   - [ ] Convert all timestamps to ISO 8601 format
   - [ ] Track earliest and latest saved dates per region
   - [ ] Handle missing or malformed timestamps gracefully

3. **Regional Integration**
   - [ ] Match saved places to existing regional centers from task 001
   - [ ] For new regions not in labeled places, create new regional entries
   - [ ] Update regional center calculations with new place coordinates
   - [ ] Maintain separate counts for labeled vs saved places

4. **Output**
   - [ ] Generate `data/saved_places.json` with timestamp data
   - [ ] Update `data/regional_centers.json` with saved place information
   - [ ] Include saved place timestamps in regional summaries
   - [ ] Track total saved places and date ranges in metadata

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
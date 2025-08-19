---
title: Extract Photo Geolocation Data
status: To Do
priority: high
labels: [data-extraction, photo-analysis]
---

## Description

Extract geolocation data from photo metadata JSON files in the Google Takeout Maps Photos directory. Parse coordinates and timestamps to enable correlation with saved places and regional visits.

## Acceptance Criteria

1. **Photo Metadata Extraction**
   - [ ] Scan `takeout/maps/saved/Photos and videos/` directory for all .json files
   - [ ] Parse each JSON file to extract geolocation coordinates
   - [ ] Extract photo creation timestamp from metadata
   - [ ] Handle missing geolocation data (some photos may not have coordinates)
   - [ ] Link metadata to corresponding photo filename

2. **Data Validation**
   - [ ] Validate coordinate ranges (latitude: -90 to 90, longitude: -180 to 180)
   - [ ] Parse timestamps using python-dateutil
   - [ ] Flag photos without geolocation data
   - [ ] Count total photos vs geotagged photos

3. **Batch Processing**
   - [ ] Process photos in batches to handle large collections
   - [ ] Implement progress tracking for long-running extractions
   - [ ] Handle .data files (non-image files) appropriately
   - [ ] Create index of all processed photos

4. **Output**
   - [ ] Generate `data/photo_metadata.json` with all extracted data
   - [ ] Include statistics: total photos, geotagged count, date range
   - [ ] Store raw coordinates for later regional matching
   - [ ] Maintain photo filename associations

## Technical Requirements

- Handle various photo metadata formats
- Efficient file system traversal
- Memory-efficient processing for large photo collections
- Robust error handling for corrupted metadata files

## Example Output Structure

```json
// data/photo_metadata.json
{
  "metadata": {
    "extraction_date": "2025-01-19T10:00:00Z",
    "total_photos": 150,
    "geotagged_photos": 145,
    "date_range": {
      "earliest": "2015-01-09T00:00:00Z",
      "latest": "2025-07-23T00:00:00Z"
    }
  },
  "photos": [
    {
      "filename": "2016-08-17-59a6e83a.jpg",
      "timestamp": "2016-08-17T15:30:00Z",
      "coordinates": {
        "latitude": 40.7128,
        "longitude": -74.0060
      },
      "has_geolocation": true
    }
  ]
}
```

## Dependencies

- None (can run in parallel with tasks 001 and 002)

## Estimated Effort

3 hours
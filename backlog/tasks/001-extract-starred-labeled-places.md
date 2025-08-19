---
title: Extract and Group Starred/Labeled Places by Region
status: To Do
priority: high
labels: [data-extraction, location-analysis]
---

## Description

Extract starred and labeled places from Google Takeout Maps data and group them by city/region for regional analysis. This will serve as the foundation for identifying visited locations and creating regional center points.

## Acceptance Criteria

1. **Data Extraction**
   - [ ] Successfully parse `takeout/maps/saved/My labeled places/Labeled places.json`
   - [ ] Extract all labeled places with their coordinates, names, and labels
   - [ ] Handle malformed or missing data gracefully with appropriate logging
   - [ ] Extract address information from each place entry

2. **Regional Grouping**
   - [ ] Group places by city name extracted from address data
   - [ ] For places without city data, use reverse geocoding (Nominatim) to determine city
   - [ ] Implement geocoding cache to avoid redundant API calls
   - [ ] Respect Nominatim rate limits (1 request per second)
   - [ ] Use proper User-Agent header for Nominatim requests

3. **Regional Center Points**
   - [ ] Calculate geographic center for each city/region using all places in that region
   - [ ] Store center point coordinates for 10-mile radius calculations
   - [ ] Track count of places per region

4. **Output**
   - [ ] Generate `data/labeled_places.json` with extracted place data
   - [ ] Generate `data/regional_centers.json` with city centers and place counts
   - [ ] Include metadata: extraction timestamp, total places count, total regions

## Technical Requirements

- Use Python with PEP 723 format
- Dependencies: geopy for geocoding and distance calculations
- Implement proper error handling and logging
- Cache geocoding results to minimize API calls
- Read-only access to takeout directory

## Example Output Structure

```json
// data/regional_centers.json
{
  "metadata": {
    "extraction_date": "2025-01-19T10:00:00Z",
    "total_places": 150,
    "total_regions": 25
  },
  "regions": {
    "San Francisco, CA": {
      "center": {
        "latitude": 37.7749,
        "longitude": -122.4194
      },
      "place_count": 45,
      "places": ["place_id_1", "place_id_2", ...]
    }
  }
}
```

## Dependencies

- None (this is the first task)

## Estimated Effort

4 hours
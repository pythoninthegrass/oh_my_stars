---
title: Correlate Photos to Regions and Saved Places
status: To Do
priority: medium
labels: [data-correlation, photo-analysis, location-analysis]
---

## Description

Match geotagged photos to saved places and regional centers using distance calculations. Group photos by their nearest city/region within a 10-mile radius threshold.

## Acceptance Criteria

1. **Distance Calculations**
   - [ ] Calculate distance between each photo and all regional centers
   - [ ] Use geopy's distance.distance() for accurate calculations
   - [ ] Find nearest regional center for each photo
   - [ ] Apply 10-mile radius threshold for regional assignment

2. **Place Correlation**
   - [ ] For each photo, find saved/labeled places within 0.1 mile radius
   - [ ] Identify photos taken at specific saved locations
   - [ ] Track photos that match multiple nearby places
   - [ ] Handle photos outside all regional boundaries

3. **Regional Grouping**
   - [ ] Group photos by assigned region
   - [ ] Create chronological photo lists per region
   - [ ] Track photo count and date range per region
   - [ ] Identify regions with no photo activity

4. **Output**
   - [ ] Generate `data/photo_locations.json` with regional groupings
   - [ ] Include distance to nearest place for each photo
   - [ ] Create summary statistics per region
   - [ ] Track unmatched photos (outside all regions)

## Technical Requirements

- Use geopy for all distance calculations
- Optimize for performance with many photos and regions
- Handle edge cases (photos at regional boundaries)
- Implement configurable distance thresholds

## Example Output Structure

```json
// data/photo_locations.json
{
  "metadata": {
    "processing_date": "2025-01-19T10:00:00Z",
    "total_photos_processed": 145,
    "photos_matched_to_regions": 140,
    "unmatched_photos": 5
  },
  "regions": {
    "San Francisco, CA": {
      "photo_count": 35,
      "date_range": {
        "first_photo": "2016-08-17T15:30:00Z",
        "last_photo": "2024-06-11T10:15:00Z"
      },
      "photos": [
        {
          "filename": "2016-08-17-59a6e83a.jpg",
          "timestamp": "2016-08-17T15:30:00Z",
          "distance_to_center": 2.5,
          "nearest_place": {
            "name": "Golden Gate Bridge",
            "distance": 0.05
          }
        }
      ]
    }
  },
  "unmatched_photos": [...]
}
```

## Dependencies

- Task 001: Regional centers must be established
- Task 002: Saved places data needed for correlation  
- Task 003: Photo metadata must be extracted

## Estimated Effort

4 hours
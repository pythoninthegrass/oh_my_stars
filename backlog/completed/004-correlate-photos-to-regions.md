---
title: Correlate Photos to Regions and Saved Places
status: Completed
priority: medium
labels: [data-correlation, photo-analysis, location-analysis]
completed_date: 2025-08-19
---

## Description

Match geotagged photos to saved places and regional centers using distance calculations. Group photos by their nearest city/region within a 10-mile radius threshold.

## Acceptance Criteria

1. **Distance Calculations**
   - [x] Calculate distance between each photo and all regional centers
   - [x] Use geopy's distance.distance() for accurate calculations
   - [x] Find nearest regional center for each photo
   - [x] Apply 10-mile radius threshold for regional assignment

2. **Place Correlation**
   - [x] For each photo, find saved/labeled places within 0.1 mile radius
   - [x] Identify photos taken at specific saved locations
   - [x] Track photos that match multiple nearby places
   - [x] Handle photos outside all regional boundaries

3. **Regional Grouping**
   - [x] Group photos by assigned region
   - [x] Create chronological photo lists per region
   - [x] Track photo count and date range per region
   - [x] Identify regions with no photo activity

4. **Output**
   - [x] Generate `data/photo_locations.json` with regional groupings
   - [x] Include distance to nearest place for each photo
   - [x] Create summary statistics per region
   - [x] Track unmatched photos (outside all regions)

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

## Completion Summary

Task completed successfully on 2025-08-19. All acceptance criteria have been fulfilled:

- Successfully calculated distances between photos and regional centers using geopy
- Found nearest regional center for each photo within 10-mile radius threshold
- Applied distance calculations to match 30 geotagged photos to 14 regions
- Correlated photos with saved/labeled places within 0.1 mile radius
- Successfully identified nearby places for photos (many with <0.1 mile accuracy)
- Grouped photos by assigned region with chronological ordering
- Created photo count and date range statistics per region
- Generated data/photo_locations.json with comprehensive regional groupings
- Included distance to nearest place for each photo
- All 30 photos successfully matched to regions (0 unmatched photos)
- Top performing regions: "Next to Pure Food Fish Market" (5 photos), "83 Yesler Wy" (5 photos)
- Implemented configurable distance thresholds (10 miles for regions, 0.1 miles for places)
- Optimized performance for processing against 285 regions and 1,247 saved/labeled places

The implementation successfully correlated all geotagged photos to their nearest regions and saved places, providing precise location matching with very high accuracy (many matches within 0.003 miles of saved places).
---
title: Extract Review Timestamps as Visit Confirmations
status: To Do
priority: medium
labels: [data-extraction, visit-tracking]
---

## Description

Extract review data from `your_places/Reviews.json` to use review timestamps as confirmed visit dates for locations. These provide additional data points for building the visit timeline.

## Acceptance Criteria

1. **Review Data Extraction**
   - [ ] Parse `takeout/maps/your_places/Reviews.json`
   - [ ] Extract place name, coordinates, and review timestamp
   - [ ] Extract review text and rating for context
   - [ ] Handle missing or incomplete review data

2. **Location Matching**
   - [ ] Match reviews to saved/labeled places by name and coordinates
   - [ ] Resolve ambiguous matches (similar names, nearby locations)
   - [ ] Match reviews to regional centers
   - [ ] Track unmatched reviews

3. **Visit Confirmation**
   - [ ] Use review date as confirmed visit date
   - [ ] Add review visits to regional visit history
   - [ ] Flag reviews as "confirmed visits" vs photo-based visits
   - [ ] Handle multiple reviews for same location

4. **Output**
   - [ ] Generate `data/review_visits.json` with processed data
   - [ ] Include review context (rating, text preview)
   - [ ] Update regional visit data with review confirmations
   - [ ] Track statistics on matched vs unmatched reviews

## Technical Requirements

- Fuzzy matching for place names
- Coordinate-based matching with tolerance
- Integration with existing regional data
- Preserve review metadata for context

## Example Output Structure

```json
// data/review_visits.json
{
  "metadata": {
    "extraction_date": "2025-01-19T10:00:00Z",
    "total_reviews": 50,
    "matched_to_places": 45,
    "matched_to_regions": 48
  },
  "reviews": [
    {
      "id": "review_001",
      "place_name": "Blue Bottle Coffee",
      "coordinates": {
        "latitude": 37.7756,
        "longitude": -122.4138
      },
      "review_date": "2021-03-15T10:30:00Z",
      "rating": 5,
      "text_preview": "Great coffee and atmosphere...",
      "matched_place": "saved_042",
      "region": "San Francisco, CA",
      "visit_type": "confirmed"
    }
  ]
}
```

## Dependencies

- Task 001: Regional centers for matching
- Task 002: Saved places for correlation

## Estimated Effort

3 hours
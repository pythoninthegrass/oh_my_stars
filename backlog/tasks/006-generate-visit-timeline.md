---
title: Generate Comprehensive Visit Timeline
status: To Do
priority: medium
labels: [data-aggregation, timeline-generation]
---

## Description

Aggregate all data sources (photos, saved places, reviews) to build a comprehensive chronological visit history for each region. Calculate visit frequency, identify patterns, and determine first/last visit dates.

## Acceptance Criteria

1. **Data Aggregation**
   - [ ] Combine photo timestamps from photo correlation data
   - [ ] Include saved place timestamps where available
   - [ ] Add review dates as confirmed visits
   - [ ] Deduplicate visits on same day to same region

2. **Timeline Generation**
   - [ ] Create chronological visit list per region
   - [ ] Group visits by year and month for pattern analysis
   - [ ] Calculate gaps between visits
   - [ ] Identify visit clusters (multiple visits in short period)

3. **Visit Analysis**
   - [ ] Calculate total visits per region
   - [ ] Determine first and last visit dates
   - [ ] Calculate average time between visits
   - [ ] Identify most frequently visited regions
   - [ ] Track visit trends over time (increasing/decreasing)

4. **Output**
   - [ ] Generate `data/visit_timeline.json` with complete timeline
   - [ ] Include visit source (photo/review/saved) for each entry
   - [ ] Create monthly and yearly summaries
   - [ ] Generate visit frequency rankings

## Technical Requirements

- Efficient date/time operations with python-dateutil
- Handle timezone considerations
- Implement configurable visit deduplication window
- Generate both detailed and summary views

## Example Output Structure

```json
// data/visit_timeline.json
{
  "metadata": {
    "generation_date": "2025-01-19T10:00:00Z",
    "total_regions": 25,
    "total_visits": 350,
    "date_range": {
      "first_visit": "2015-01-09T00:00:00Z",
      "last_visit": "2025-01-15T00:00:00Z"
    }
  },
  "regions": {
    "San Francisco, CA": {
      "visit_count": 85,
      "first_visit": "2015-01-09T14:30:00Z",
      "last_visit": "2024-12-20T16:45:00Z",
      "visit_frequency": {
        "avg_days_between_visits": 42,
        "visits_by_year": {
          "2015": 5,
          "2016": 12,
          "2017": 15
        }
      },
      "visits": [
        {
          "date": "2015-01-09T14:30:00Z",
          "source": "photo",
          "source_id": "2015-01-09-fe8b332f.jpg",
          "places_visited": ["Golden Gate Bridge"]
        }
      ]
    }
  }
}
```

## Dependencies

- Task 004: Photo-to-region correlations
- Task 005: Review visit data
- Task 002: Saved place timestamps

## Estimated Effort

4 hours
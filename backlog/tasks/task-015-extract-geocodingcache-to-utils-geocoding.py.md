---
id: task-015
title: Extract GeocodingCache to utils/geocoding.py
status: To Do
assignee: []
created_date: '2025-08-26 20:46'
labels:
  - refactoring
  - utils-module
dependencies: []
---

## Description

Move the GeocodingCache class (lines 175-421) from main.py to utils/geocoding.py. This class handles caching geocoding results with rate limiting and expiration

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 GeocodingCache class moved to utils/geocoding.py,SSL context setup included if needed,Proper imports added,Class imported in main.py
<!-- AC:END -->

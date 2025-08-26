---
id: task-006
title: Extract photo processing classes to core/photos.py
status: To Do
assignee: []
created_date: '2025-08-26 20:46'
labels:
  - refactoring
  - core-module
dependencies: []
---

## Description

Move PhotoMetadataExtractor (lines 878-1056) and PhotoLocationCorrelator (lines 1057-1293) classes from main.py to core/photos.py. These classes handle extracting geolocation from photos and correlating them to regions

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 PhotoMetadataExtractor moved to core/photos.py,PhotoLocationCorrelator moved to core/photos.py,Image metadata extraction logic preserved,Classes imported in main.py
<!-- AC:END -->

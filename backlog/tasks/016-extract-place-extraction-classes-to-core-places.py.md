---
id: task-005
title: Extract place extraction classes to core/places.py
status: To Do
assignee: []
created_date: '2025-08-26 20:46'
labels:
  - refactoring
  - core-module
dependencies: []
---

## Description

Move LabeledPlacesExtractor (lines 422-608) and SavedPlacesExtractor (lines 609-877) classes from main.py to core/places.py. These classes handle extracting starred and saved places from Google Takeout data

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 LabeledPlacesExtractor moved to core/places.py,SavedPlacesExtractor moved to core/places.py,Shared functionality abstracted if applicable,Classes imported in main.py
<!-- AC:END -->

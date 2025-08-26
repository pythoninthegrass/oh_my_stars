---
id: task-008
title: Extract timeline and report generators to core/reports.py
status: To Do
assignee: []
created_date: '2025-08-26 20:46'
labels:
  - refactoring
  - core-module
dependencies: []
---

## Description

Move VisitTimelineGenerator (lines 1539-1882) and SummaryReportGenerator (lines 1883-2209) classes from main.py to core/reports.py. These classes handle generating timelines and markdown reports

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 VisitTimelineGenerator moved to core/reports.py,SummaryReportGenerator moved to core/reports.py,Markdown formatting preserved,Classes imported in main.py
<!-- AC:END -->

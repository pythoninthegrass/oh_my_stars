---
id: task-020
title: Extract pipeline orchestration to core/pipeline.py
status: To Do
assignee: []
created_date: '2025-08-26 20:46'
labels:
  - refactoring
  - core-module
dependencies: []
---

## Description

Move DataAnalysisPipeline class (lines 2210-2420) from main.py to core/pipeline.py. This class orchestrates the entire data analysis workflow

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 DataAnalysisPipeline moved to core/pipeline.py,Step execution logic preserved,Progress tracking maintained,Class imported in main.py
<!-- AC:END -->

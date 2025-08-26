---
id: task-012
title: Create constants module in utils/constants.py
status: To Do
assignee: []
created_date: '2025-08-26 20:47'
updated_date: '2025-08-26 20:48'
labels:
  - refactoring
  - utils-module
dependencies: []
---

## Description

Extract constants to config.py

Move all hardcoded constants from main.py to the existing config.py file:
- Pipeline step names
- File paths
- Default values
- Magic numbers

This will centralize configuration without creating new files.

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 All constants moved to config.py,No hardcoded values in main.py,properly organized,All tests pass
<!-- AC:END -->

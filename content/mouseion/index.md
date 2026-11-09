---
title: MOUSEION
description: 三境居 — 书 · 影 · 音
---


```base
filters:
  and:
    - file.inFolder("mouseion")
    - file.hasProperty("cover")

views:
  - type: mouseion
    name: Mouseion

  - type: table
    name: Index
    order:
      - title
      - medium
      - creator
      - year
    sort:
      - property: medium
        direction: ASC
      - property: year
        direction: DESC
```

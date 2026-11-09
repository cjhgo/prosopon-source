---
title: Films
description: 影境 — 看过与想看的电影
---


```base
filters:
  and:
    - file.inFolder("mouseion/film")
    - file.hasProperty("cover")

views:
  - type: cards
    name: Covers
    image: note.cover
    cardSize: 220
    order:
      - title
      - creator
      - year
    sort:
      - property: year
        direction: DESC

  - type: table
    name: Table
    order:
      - title
      - creator
      - year
      - tags
    sort:
      - property: year
        direction: DESC

  - type: gallery
    name: Gallery
    image: note.cover
    cardSize: 4
    order:
      - title
      - year
    sort:
      - property: year
        direction: DESC
```

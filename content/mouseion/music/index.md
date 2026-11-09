---
title: Music
description: 音境 — 唱片与磁带
---


```base
filters:
  and:
    - file.inFolder("mouseion/music")
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

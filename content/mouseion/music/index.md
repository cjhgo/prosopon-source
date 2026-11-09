---
title: Music
description: 音境 — 以歌为单位
---

```base
filters:
  and:
    - file.inFolder("mouseion/music")
    - file.hasProperty("cover")

views:
  - type: cards
    name: Songs
    image: note.cover
    cardSize: 220
    order:
      - title
      - creator
      - album
      - year
    sort:
      - property: year
        direction: DESC

  - type: table
    name: All
    order:
      - title
      - creator
      - album
      - year
      - note.album_rating
      - tags
    sort:
      - property: year
        direction: DESC
    columnSize:
      note.title: 260
      note.album: 220
      note.year: 80

  - type: table
    name: Albums
    groupBy:
      property: note.album
      direction: ASC
    order:
      - title
      - creator
      - album
      - year
      - note.album_rating
    sort:
      - property: year
        direction: DESC

  - type: board
    name: Tags
    groupBy:
      property: note.tags
      direction: ASC
    order:
      - title
      - creator
      - album
      - year
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

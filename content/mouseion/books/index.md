---
title: Books
description: 书境 — 已读与在读的书
---

```base
filters:
  and:
    - file.inFolder("mouseion/books")
    - file.hasProperty("cover")

views:
  - type: table
    name: All
    order:
      - title
      - creator
      - year
      - note.neodb_rating
      - tags
    sort:
      - property: year
        direction: DESC
    columnSize:
      note.title: 320
      note.year: 80

  - type: cards
    name: Cards
    image: note.cover
    cardSize: 220
    order:
      - title
      - creator
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

  - type: board
    name: Board
    groupBy:
      property: note.tags
      direction: ASC
    order:
      - title
      - creator
      - year
    sort:
      - property: year
        direction: DESC

  - type: list
    name: List
    groupBy:
      property: note.tags
      direction: ASC
    order:
      - title
      - creator
      - year
    sort:
      - property: year
        direction: DESC
```

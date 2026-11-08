---
title: 图文混排示例(参考区)
date: 2026-11-08
tags: [参考, 写作]
description: _refer 参考区:只在本地预览可见,上线自动忽略。这里放各种排版的写法示例。
---
> 本目录(`content/_refer/`)**只在 `preview.sh` 本地可见**,`deploy.sh` 上线时被忽略
> (机制:`QUARTZ_PROD=1` → `ignorePatterns` 加 `_refer/**`)。放示例、草稿、写作参考都行。

## 1. 单图(默认块级)
![](image/例1.jpg)

## 2. 并排两张
<div class="grid2">
  <img src="image/例1.jpg">
  <img src="image/例2.jpg">
</div>

## 3. 三列
<div class="grid3">
  <img src="image/例1.jpg">
  <img src="image/例2.jpg">
  <img src="image/例1.jpg">
</div>

## 4. 自适应画廊
<div class="gallery">
  <img src="image/例1.jpg">
  <img src="image/例2.jpg">
  <img src="image/例1.jpg">
  <img src="image/例2.jpg">
</div>

## 5. 带图注
<figure>
  <img src="image/例2.jpg" width="480">
  <figcaption>图注:居中、小号灰字。一句话说清这张图在讲什么。</figcaption>
</figure>

## 6. 文字绕图
<img class="float-right" src="image/例1.jpg" width="220">
这是一段正文,图片浮在右侧,文字环绕它排版。适合把配图塞进段落,不打断阅读节奏。注意 HTML 块内部不解析 markdown,所以这段文字要写在 HTML 外面。再多写几句凑长度,才能看出绕排效果。
<div class="clearfix"></div>

## 7. 折叠标题与伸缩文本
### 这节默认折叠{+}
点标题展开才看得到这行。

```telescopic
* 我在深圳
  * 我在深圳骑了29公里
    * 我在深圳环石岩湖骑了29公里,阴天22度,体验很好
```

## 8. 站内链接
参见 [[再见了这里]](如果该页存在)。

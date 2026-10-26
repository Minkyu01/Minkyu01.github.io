---
title: IRC 메시지 한 줄의 구조
description: 접두사, 명령, 인자, 마지막 인자. RFC 2812 의 메시지 형식을 예시 한 줄로 뜯어봅니다.
date: 2026-10-26
tags: [42, ft_irc, 네트워크]
series: ft_irc 만들기
series_description: IRC 프로토콜을 읽고 poll 하나로 도는 서버를 만듭니다.
draft: true
---

## 한 줄 뜯어보기

```text
:nick!user@host PRIVMSG #42seoul :안녕하세요, 다들
```

| 부분 | 값 |
|---|---|
| 접두사 | `nick!user@host` (보낸 사람, 서버가 붙임) |
| 명령 | `PRIVMSG` |
| 인자 | `#42seoul` |
| 마지막 인자 | `안녕하세요, 다들` (`:` 뒤는 빈칸까지 한 인자) |

> [!NOTE]
> 한 줄은 끝의 `\r\n` 까지 합쳐 512바이트를 넘을 수 없습니다.

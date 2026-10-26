---
title: 요청 줄과 머리글 읽기
description: 요청이 어디서 끝나는지 알아내는 세 가지 경우와, 머리글 끝을 찾는 법.
date: 2026-10-23
tags: [42, webserv, HTTP]
series: webserv 만들기
draft: true
---

## 머리글의 끝

요청은 한 번에 오지 않습니다. 받은 바이트를 손님별 버퍼에 쌓다가, 빈 줄(`\r\n\r\n`)이 보이면 머리글이 끝난 것입니다.

```cpp
std::string::size_type end = buf.find("\r\n\r\n");
if (end == std::string::npos)
    return false;   // 아직 머리글이 다 오지 않음
```

## 본문은 어디까지인가

| 경우 | 알아내는 법 |
|---|---|
| `Content-Length: 42` | 머리글 뒤로 42바이트 |
| `Transfer-Encoding: chunked` | 길이·내용 조각을 길이 0 조각이 올 때까지 |
| 둘 다 없음 | 본문 없음 (`GET` 등) |

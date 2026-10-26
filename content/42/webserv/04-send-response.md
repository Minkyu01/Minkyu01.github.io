---
title: 응답 만들어 보내기
description: 상태 줄과 머리글을 붙여 응답을 만들고, 한 번에 다 나가지 않는 send 를 다루는 법.
date: 2026-10-24
tags: [42, webserv, HTTP]
series: webserv 만들기
draft: true
---

## 응답의 모양

```http
HTTP/1.1 200 OK
Content-Type: text/html
Content-Length: 1337

<!doctype html>…
```

머리글 뒤의 빈 줄을 빠뜨리면 브라우저가 본문을 머리글로 읽습니다.

## 나눠서 보내기

`send` 는 보낸 바이트 수를 돌려줍니다. 버퍼에서 보낸 만큼만 지우고, 남은 게 있으면 다음 `POLLOUT` 때 이어서 보냅니다.

```cpp
ssize_t n = send(fd, out.data(), out.size(), 0);
if (n > 0)
    out.erase(0, n);
```

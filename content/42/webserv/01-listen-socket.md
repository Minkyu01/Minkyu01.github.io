---
title: 소켓 열고 연결 기다리기
description: socket·bind·listen 세 줄로 8080 포트를 여는 법과, 다시 띄울 때 생기는 "Address already in use" 막기.
date: 2026-10-21
tags: [42, webserv, 네트워크]
series: webserv 만들기
series_description: 소켓을 여는 데서 CGI 까지, webserv 과제를 처음부터 순서대로 따라갑니다.
draft: true
---

## 세 단계

서버 소켓은 만들고(`socket`), 주소를 붙이고(`bind`), 기다리는 상태로 바꾸는(`listen`) 순서로 엽니다. 아래는 오류 검사를 뺀 뼈대입니다.

```cpp title="srcs/Server.cpp"
int fd = socket(AF_INET, SOCK_STREAM, 0);
int on = 1;
setsockopt(fd, SOL_SOCKET, SO_REUSEADDR, &on, sizeof(on));   // 바로 다시 띄워도 bind 가 실패하지 않게

sockaddr_in addr;
std::memset(&addr, 0, sizeof(addr));
addr.sin_family = AF_INET;
addr.sin_addr.s_addr = htonl(INADDR_ANY);
addr.sin_port = htons(8080);

bind(fd, reinterpret_cast<sockaddr*>(&addr), sizeof(addr));
listen(fd, SOMAXCONN);
fcntl(fd, F_SETFL, O_NONBLOCK);
```

> [!WARNING]
> 실제 코드에서는 네 호출 모두 반환값이 -1 인지 확인하고, 실패하면 `fd` 를 닫은 뒤 이유를 알려야 합니다.

## 왜 SO_REUSEADDR 인가

서버를 끄면 방금 쓰던 포트가 잠시 `TIME_WAIT` 상태로 남습니다. 이 옵션이 없으면 그동안 같은 포트로 `bind` 가 실패합니다.

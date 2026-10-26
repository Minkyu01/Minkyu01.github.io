---
title: poll 로 여러 연결 돌보기
description: 듣는 소켓 하나와 손님 소켓 여러 개를 한 루프에서 돌보는 법.
date: 2026-10-22
tags: [42, webserv, 네트워크]
series: webserv 만들기
draft: true
---

## 루프에 올리기

1편에서 연 소켓을 `poll` 감시 목록 맨 앞에 넣습니다. 손님이 들어올 때마다 `accept` 로 받은 소켓을 뒤에 붙입니다.

```cpp
std::vector<pollfd> fds;
pollfd listener = { fd, POLLIN, 0 };
fds.push_back(listener);
```

루프 전체 뼈대와 잊기 쉬운 점은 [poll() 하나로 소켓 여러 개 다루기](../poll-socket.md)에 따로 정리했습니다.

## 쓰기는 필요할 때만

보낼 응답이 생긴 소켓에만 `POLLOUT` 을 켭니다. 늘 켜 두면 보낼 게 없어도 `poll` 이 계속 깨어나서 CPU 를 씁니다.

---
title: poll() 하나로 소켓 여러 개 다루기
description: ft_irc 와 webserv 에서 쓴 I/O 멀티플렉싱의 뼈대. 스레드 없이 접속 수십 개를 한 루프에서 받는 법.
date: 2026-10-20
tags: [42, C++, 네트워크]
---

## 왜 poll 인가

`accept()` 와 `recv()` 는 기본적으로 블로킹이다. 클라이언트 하나가 아무것도 안 보내면 서버 전체가 거기서 멈춘다. 스레드를 쓰면 되지만 42 과제는 보통 금지하거나, 쓰더라도 디버깅이 괴롭다.

`poll()` 은 "이 fd 들 중 하나라도 읽을 준비가 되면 깨워 달라"는 시스템 콜이다. 그러면 한 루프에서 모든 소켓을 번갈아 볼 수 있다.

> [!NOTE]
> `select()` 는 fd 번호가 1024 를 넘으면 못 쓰고, `epoll`/`kqueue` 는 OS 마다 다르다. 과제 범위에서는 `poll()` 이 가장 무난하다.

## 뼈대

![poll 이벤트 루프 도표](../guide/images/poll-loop.svg "poll 이 깨어나면 준비된 fd 만 골라 처리하고 다시 잠든다")

```cpp title="server.cpp"
std::vector<pollfd> fds;
fds.push_back((pollfd){listen_fd, POLLIN, 0});

while (running) {
    int n = poll(fds.data(), fds.size(), -1);
    if (n < 0) {
        if (errno == EINTR) continue;      // 시그널로 깨어난 경우
        throw std::runtime_error("poll");
    }
    for (size_t i = 0; i < fds.size(); ++i) {
        if (fds[i].revents & POLLIN) {
            if (fds[i].fd == listen_fd)
                acceptClient(fds);          // 새 접속 → fds 에 추가
            else
                readClient(fds[i].fd);      // 데이터 → 버퍼에 쌓고 줄 단위로 처리
        }
        if (fds[i].revents & (POLLHUP | POLLERR))
            closeClient(fds, i--);
    }
}
```

## 잊기 쉬운 것들

- **논블로킹으로 바꿔 두기.** `fcntl(fd, F_SETFL, O_NONBLOCK)`. 안 그러면 `recv()` 가 다시 막힐 수 있다.
- **루프 중간에 fds 를 지우지 않기.** 인덱스가 밀린다. 지울 것을 표시만 해 두고 루프가 끝난 뒤 한꺼번에 지운다.
- **부분 수신.** 한 번의 `recv()` 로 메시지 하나가 오지 않는다. 클라이언트마다 버퍼를 두고 `\r\n` 이 나올 때까지 모은다.
- **쓰기도 poll 로.** 보낼 게 남았으면 `events` 에 `POLLOUT` 을 켜고, 다 보내면 끈다. 항상 켜 두면 루프가 바쁘게 돈다.

| 상황 | revents | 할 일 |
|---|---|---|
| 새 접속 | `POLLIN` (listen fd) | `accept()` 후 fds 에 추가 |
| 데이터 도착 | `POLLIN` | `recv()`, 0 이면 연결 종료 |
| 보낼 수 있음 | `POLLOUT` | 보낼 버퍼에서 `send()` |
| 끊김·오류 | `POLLHUP`, `POLLERR` | 닫고 fds 에서 제거 |

> [!WARNING]
> `send()` 가 보낸 바이트 수를 꼭 확인한다. 큰 응답은 한 번에 다 나가지 않는다.

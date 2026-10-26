---
title: CGI 에 넘기는 환경 변수
description: CGI 프로그램은 요청 정보를 환경 변수로 받습니다. RFC 3875 에 나오는 것 중 자주 쓰는 것만 추렸습니다.
date: 2026-10-25
tags: [42, webserv, CGI]
series: webserv 만들기
draft: true
---

## 자주 쓰는 변수

| 변수 | 예 | 뜻 |
|---|---|---|
| `GATEWAY_INTERFACE` | `CGI/1.1` | CGI 판 |
| `REQUEST_METHOD` | `POST` | 요청 메서드 |
| `QUERY_STRING` | `q=poll&page=2` | 주소의 `?` 뒤 |
| `CONTENT_LENGTH` | `27` | 본문 길이 (본문이 있을 때) |
| `CONTENT_TYPE` | `application/x-www-form-urlencoded` | 본문 형식 |
| `SCRIPT_NAME` | `/cgi-bin/hello.py` | 스크립트 경로 |
| `PATH_INFO` | `/extra/path` | 스크립트 경로 뒤에 붙은 부분 |
| `SERVER_PROTOCOL` | `HTTP/1.1` | 요청의 HTTP 판 |

본문은 표준 입력으로 넘기고, CGI 가 표준 출력에 쓴 내용을 받아 응답으로 만듭니다.

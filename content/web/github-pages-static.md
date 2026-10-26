---
title: GitHub Pages 에 정적 사이트 올리기
description: Actions 로 빌드해서 배포하는 흐름과, 하위 경로 때문에 링크가 깨지는 문제를 피하는 법.
date: 2026-10-25
tags: [웹, GitHub]
---

## 두 가지 주소

| 저장소 이름 | 주소 | base path |
|---|---|---|
| `<아이디>.github.io` | `https://<아이디>.github.io/` | 없음 |
| 그 밖의 이름 | `https://<아이디>.github.io/<저장소>/` | `/<저장소>` |

두 번째 경우 `/assets/style.css` 처럼 루트로 시작하는 링크가 전부 깨진다. 빌드할 때 접두어를 붙여야 한다. `actions/configure-pages` 가 `base_path` 출력으로 알려 주므로 그 값을 빌드 스크립트에 넘기면 된다.

```yaml title=".github/workflows/pages.yml"
- id: pages
  uses: actions/configure-pages@v5
- run: uv run --no-project build.py --base "${{ steps.pages.outputs.base_path }}"
```

## 한 번만 하는 설정

1. 저장소 **Settings › Pages › Build and deployment › Source** 를 *GitHub Actions* 로 바꾼다.
2. 워크플로에 `pages: write` 와 `id-token: write` 권한을 준다.
3. 빌드 결과 폴더에 `.nojekyll` 빈 파일을 둔다. 없으면 `_` 로 시작하는 파일을 Jekyll 이 숨긴다.

> [!TIP]
> 워크플로 로그의 **deploy** 단계에 최종 주소가 찍힌다.

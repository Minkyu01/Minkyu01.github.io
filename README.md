# Minkyu's Blog

https://minkyu01.github.io/

GitBook 문서 사이트의 레이아웃에 토스 디자인 시스템(TDS)의 글자·간격·색을 입힌 정적 기술 블로그 생성기. Markdown 을 쓰고 main 에 푸시하면 GitHub Pages 에 올라간다.

## 구조

```
site.yaml            제목·설명·그룹 순서·바닥 카드
content/             글 (index.md = 홈, 폴더 = 사이드바 폴더, _index.md = 폴더 소개)
theme/templates/     page.html (Jinja2)
theme/static/        style.css · app.js
build.py             content → _site
dev.py               로컬 미리보기 (저장하면 열린 창이 저절로 새로고침)
.github/workflows/   Pages 배포
```

## 로컬 미리보기

```bash
uv run --no-project dev.py 4900
```

- http://127.0.0.1:4900/ — 작업 미리보기. 지금 폴더의 파일 그대로 보여 주고, 초안(`draft: true`)과 로컬 전용 글도 보인다. 파일을 저장하면 열려 있는 창이 저절로 새로고침되고, 다른 글을 저장하면 그 글로 넘어간다.
- http://127.0.0.1:4901/ — 배포 미리보기. main 에 커밋된 것만 GitHub Actions 와 같은 방법으로 빌드한 모습이다.

## 올리지 않는 것

`.gitignore` 의 "로컬 전용" 목록은 이 컴퓨터에만 있고 저장소에는 올라가지 않는다. `build.py` 를 초안 없이 돌리면 이 파일들도 빼고 빌드해서, GitHub 에서 만드는 사이트와 같은 결과가 나온다.

## 배포

글은 draft 브랜치에서 쓰고, 다 쓴 것만 main 으로 옮겨 올린다. main 에 푸시하면 `.github/workflows/pages.yml` 이 빌드해서 Pages 에 올린다.

```bash
git fetch . draft:main     # draft 의 커밋을 main 으로 (빨리 감기만)
git push origin main
```

빌드는 머리말 오류, 주소 겹침, 깨진 링크·그림(없는 파일, 초안·로컬 전용 글로 가는 링크)이 있으면 멈추고, 그러면 배포하지 않는다.

저장소 이름이 `<아이디>.github.io` 라서 사이트가 https://minkyu01.github.io/ 바로 아래에 놓인다. 다른 이름이면 주소 뒤에 `/저장소이름/` 이 붙으니, `site.yaml` 의 `url`·`repo`·`footer_card.href` 도 맞춘다. 처음 한 번은 저장소 **Settings › Pages › Source** 를 **GitHub Actions** 로 바꿔 둔다.

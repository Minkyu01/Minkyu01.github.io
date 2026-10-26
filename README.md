# tech_blog

GitBook 문서 사이트의 레이아웃에 토스 디자인 시스템(TDS)의 글자·간격·색을 입힌 정적 기술 블로그 생성기. Markdown 을 쓰고 푸시하면 GitHub Pages 에 올라간다.

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

http://127.0.0.1:4900/ 에서 본다. 초안(`draft: true`)과 로컬 전용 글도 보인다. 파일을 저장하면 열려 있는 창이 저절로 새로고침되고, 다른 글을 저장하면 그 글로 넘어간다.

## 올리지 않는 것

`.gitignore` 의 "로컬 전용" 목록은 이 컴퓨터에만 있고 저장소에는 올라가지 않는다. `build.py` 를 초안 없이 돌리면 이 파일들도 빼고 빌드해서, GitHub 에서 만드는 사이트와 같은 결과가 나온다.

## 배포

```bash
gh repo create tech_blog --public --source=. --push
```

그다음 저장소 **Settings › Pages › Source** 를 **GitHub Actions** 로 바꾼다. 이후로는 `git push` 만 하면 된다. 저장소 이름을 바꾸면 `site.yaml` 의 `url`·`repo`·`footer_card.href` 도 맞춘다.

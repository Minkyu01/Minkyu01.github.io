# tech_blog

GitBook 문서 사이트의 레이아웃에 토스 디자인 시스템(TDS)의 글자·간격·색을 입힌 정적 기술 블로그 생성기. Markdown 을 쓰고 푸시하면 GitHub Pages 에 올라간다.

- 분석 근거: [DESIGN.md](DESIGN.md)
- 글 쓰는 법·문법: `content/guide/writing.md` (사이트의 "블로그 쓰는 법")
- 문법 견본: `content/guide/markdown-showcase.md` (그림·코드·표·힌트·수식·Mermaid 도표가 실제로 보이는 모습)

## 구조

```
site.yaml            제목·설명·그룹 순서·바닥 카드
content/             글 (index.md = 홈, 폴더 = 사이드바 그룹)
theme/templates/     page.html (Jinja2)
theme/static/        style.css · app.js
build.py             content → _site
dev.py               로컬 미리보기 (빌드 + 자동 재빌드 + no-store 서버)
.github/workflows/   Pages 배포
```

## 로컬 미리보기

```bash
uv run --no-project dev.py 4900
```

→ http://127.0.0.1:4900/ (초안 `draft: true` 도 보인다)

## 배포 (처음 한 번)

```bash
git init -b main
git add -A
git commit -m "블로그 시작"
gh repo create tech_blog --public --source=. --push
```

그다음 저장소 **Settings › Pages › Source** 를 **GitHub Actions** 로 바꾼다. 이후로는 `git push` 만 하면 된다.

저장소 이름을 바꾸면 `site.yaml` 의 `url`·`repo`·`footer_card.href` 도 맞춘다.

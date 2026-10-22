# Suggested incremental Git workflow

Run these as separate commits in your own repository after reviewing the files. These are suggestions, not fabricated history.

```bash
git init
git add README.md requirements.txt .gitignore .env.example
git commit -m "chore: scaffold CT-200 API project"

git add app/parser.py tests/test_parser.py data/ct200_manual.pdf data/ct200_manual_v2.pdf data/ASSIGNMENT_UPDATE.txt data/assignment.pdf
git commit -m "feat: parse CT-200 PDF into structured hierarchy"

git add app/models.py app/database.py app/main.py
git commit -m "feat: add versioned document browse and selection APIs"

git add app/llm.py app/generation_store.py app/schemas.py tests/test_api.py
git commit -m "feat: add validated QA generation and stale traceability"

git add docs/
git commit -m "docs: explain parsing decisions and validation strategy"

python -m pytest -q
git status
git log --oneline
```

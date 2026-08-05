#!/usr/bin/env bash
# One-shot: clean up, commit, push, set repo metadata, and enable GitHub Pages.
# Run once from the repo root:   bash push.sh
set -uo pipefail

REPO="VijayChamakuri/creator-pulse"
PAGES_URL="https://VijayChamakuri.github.io/creator-pulse/"
cd "$(dirname "$0")"

echo "1/5  Removing tracked macOS junk (.DS_Store)…"
git ls-files -z | grep -ziE '(^|/)\.DS_Store$' | xargs -0 -r git rm --cached -q
find . -name .DS_Store -not -path './.git/*' -delete 2>/dev/null || true

echo "2/5  Committing and pushing…"
git add -A
git commit -m "Results-first README, live Pages demo, real Claude report screenshots, provenance fix, .DS_Store cleanup" \
  || echo "   (nothing new to commit)"
git push

echo "3/5  Setting repo description, topics, and website…"
gh repo edit "$REPO" \
  --description "Automated weekly YouTube creator report: real public data + a labeled synthetic analytics layer, with an LLM-written narrative and an LLM QA pass." \
  --homepage "$PAGES_URL" \
  --add-topic youtube-analytics --add-topic data-pipeline --add-topic llm \
  --add-topic anthropic --add-topic creator-economy --add-topic ab-testing \
  --add-topic python --add-topic reporting-automation \
  || echo "   (gh repo edit failed — set these in Settings if needed)"

echo "4/5  Enabling GitHub Pages from /docs on main…"
enable_pages () { gh api -X "$1" "repos/$REPO/pages" --input - <<'JSON'
{"source":{"branch":"main","path":"/docs"}}
JSON
}
enable_pages POST 2>/dev/null \
  || enable_pages PUT 2>/dev/null \
  || echo "   (Pages may already be on — check Settings → Pages, source = main /docs)"

echo "5/5  Done."
echo
echo "✅ Live site (first build takes ~1 minute):"
echo "     $PAGES_URL"
echo "   Report:    ${PAGES_URL}report.html"
echo "   Dashboard: ${PAGES_URL}dashboard.html"

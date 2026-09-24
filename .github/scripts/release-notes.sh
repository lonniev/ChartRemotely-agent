#!/usr/bin/env bash
# Print release notes for an automatic release of VERSION ($1).
#
# A CHANGELOG section for VERSION wins, as it does for a tagged release.
# Otherwise: the [Unreleased] lines added since the previous tag (so a line is
# announced once, not on every release that follows it), then the subject of
# every commit merged since that tag - on a squash-merged repo, the PR titles.
set -euo pipefail

version=$1
previous=$(git tag -l 'v[0-9]*.[0-9]*.[0-9]*' --sort=-v:refname | head -1)

section() {  # print the body of the "## [$1]" / "## $1" section of CHANGELOG.md on stdin
  local re
  re=$(printf '%s' "$1" | sed 's/\./\\./g')
  awk "/^## [[]?${re}[]]?([ ]|\$)/{found=1; next} /^## /{if(found) exit} found{print}"
}

notes=$(section "$version" < CHANGELOG.md | sed '/^[[:space:]]*$/d')
if [ -n "$notes" ]; then
  section "$version" < CHANGELOG.md
  exit 0
fi

now=$(section Unreleased < CHANGELOG.md | sed '/^[[:space:]]*$/d')
if [ -n "$previous" ]; then
  before=$(git show "$previous:CHANGELOG.md" 2>/dev/null | section Unreleased | sed '/^[[:space:]]*$/d')
  range="$previous..HEAD"
else
  before=""
  range="HEAD"
fi
added=$(grep -vxF -f <(printf '%s\n' "$before") <<< "$now" || true)

if [ -n "$added" ]; then
  printf '%s\n\n' "$added"
fi
echo "### Merged"
git log --no-merges --format='- %s' "$range" -- chartremotely pyproject.toml

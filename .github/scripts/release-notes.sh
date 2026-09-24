#!/usr/bin/env bash
# Print release notes for an automatic release of VERSION ($1).
#
# A CHANGELOG section for VERSION wins, as it does for a tagged release.
# Otherwise: the section stamp_changelog.py will file this release under - the
# [Unreleased] entries added since the previous tag, with their ### headings -
# then the subject of every commit merged since that tag (the PR titles).
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

if [ -n "$previous" ]; then range="$previous..HEAD"; else range="HEAD"; fi
added=$(python3 "$(dirname "$0")/stamp_changelog.py" --notes "$version")

if [ -n "$added" ]; then
  printf '%s\n\n' "$added"
fi
echo "### Merged"
git log --no-merges --format='- %s' "$range" -- chartremotely pyproject.toml

#!/usr/bin/env bash
# Print the version the next automatic release publishes (without the "v").
#
# The next patch after the newest vX.Y.Z tag, unless pyproject.toml on this
# commit already says something higher - that is how a person asks for a minor
# or major release: raise the version in a PR, and the merge publishes it.
set -euo pipefail

declared=$(grep -m1 '^version' pyproject.toml | cut -d'"' -f2)
latest=$(git tag -l 'v[0-9]*.[0-9]*.[0-9]*' --sort=-v:refname | head -1)
latest=${latest#v}

if [ -z "$latest" ]; then
  echo "$declared"
  exit 0
fi

highest=$(printf '%s\n%s\n' "$declared" "$latest" | sort -V | tail -1)
if [ "$declared" = "$highest" ] && [ "$declared" != "$latest" ]; then
  echo "$declared"
else
  IFS=. read -r major minor patch <<< "$latest"
  echo "$major.$minor.$((patch + 1))"
fi

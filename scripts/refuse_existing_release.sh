#!/usr/bin/env bash
set -euo pipefail

: "${TAG:?TAG is required}"

set +e
git ls-remote --exit-code --refs --tags origin "refs/tags/${TAG}" >/dev/null 2>&1
remote_status=$?
set -e

case "$remote_status" in
  0)
    remote_tag_exists=true
    ;;
  2)
    remote_tag_exists=false
    ;;
  *)
    echo "Unable to verify remote tag absence for ${TAG}" >&2
    exit "$remote_status"
    ;;
esac

if [[ "$remote_tag_exists" == true ]] || gh release view "$TAG" >/dev/null 2>&1; then
  echo "Refusing to replace existing immutable tag or release: $TAG" >&2
  exit 1
fi

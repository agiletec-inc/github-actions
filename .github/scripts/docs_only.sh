#!/usr/bin/env bash
set -euo pipefail

repository=${1:-.}
base=${2:-unknown}
head=${3:-HEAD}

docs_only=false
heavy=true
secret_scan=true

emit_outputs() {
  printf 'docs_only=%s\nheavy=%s\nsecret_scan=%s\n' "$docs_only" "$heavy" "$secret_scan"
  if [ -n "${GITHUB_OUTPUT:-}" ]; then
    printf 'docs_only=%s\nheavy=%s\nsecret_scan=%s\n' "$docs_only" "$heavy" "$secret_scan" >> "$GITHUB_OUTPUT"
  fi
}

# An absent, sentinel, or locally unresolvable base must never suppress checks.
if [ -z "$base" ] || [ "$base" = unknown ] || [[ "$base" =~ ^0+$ ]] ||
   ! git -C "$repository" cat-file -e "$base^{commit}" 2>/dev/null ||
   ! git -C "$repository" cat-file -e "$head^{commit}" 2>/dev/null; then
  emit_outputs
  exit 0
fi

changed=0
non_docs=0
while IFS= read -r -d '' path; do
  changed=1
  case "$path" in
    .github/*|.gitmodules|package.json|pnpm-lock.yaml|yarn.lock|package-lock.json|npm-shrinkwrap.json|bun.lock|bun.lockb|deno.lock|Cargo.lock|uv.lock|poetry.lock|Pipfile.lock|supabase/*|Dockerfile|*/Dockerfile|*/Dockerfile.*)
      non_docs=1
      ;;
    docs/*|README|README.*|LICENSE|LICENSE.*|NOTICE|NOTICE.*|CHANGELOG|CHANGELOG.*)
      ;;
    *)
      non_docs=1
      ;;
  esac
done < <(git -C "$repository" diff --name-only -z "$base" "$head")

if [ "$changed" -eq 1 ] && [ "$non_docs" -eq 0 ]; then
  docs_only=true
  heavy=false
fi

emit_outputs

#!/usr/bin/env bash
set -euo pipefail

repository=${1:-.}
base=${2:-}
head=${3:-HEAD}
script_directory=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
migrations_file=${4:-"$script_directory/../native-gate-migrations.json"}

revision_exists() {
  git -C "$repository" cat-file -e "$1^{commit}" 2>/dev/null
}

workflows_with_job() {
  local revision=$1
  local wanted=$2
  local path

  while IFS= read -r -d '' path; do
    if git -C "$repository" show "${revision}:${path}" 2>/dev/null |
      awk -v wanted="$wanted" '
        /^jobs:[[:space:]]*$/ { in_jobs=1; next }
        in_jobs && /^[^[:space:]#]/ { in_jobs=0 }
        in_jobs && $0 ~ "^  " wanted ":[[:space:]]*($|#)" { found=1 }
        END { exit(found ? 0 : 1) }
      '; then
      printf '%s\0' "$path"
    fi
  done < <(git -C "$repository" ls-tree -r -z --name-only "$revision" -- .github/workflows)
}

revision_has_supabase() {
  git -C "$repository" cat-file -e "$1:supabase/config.toml" 2>/dev/null
}

protected_workflow_change_is_approved() {
  local path=$1
  local repository_name=${GITHUB_REPOSITORY:-}
  local base_blob
  local head_blob

  [ -n "$repository_name" ] || return 1
  [ -f "$migrations_file" ] || return 1
  base_blob=$(git -C "$repository" rev-parse "${base}:${path}" 2>/dev/null) || return 1
  head_blob=$(git -C "$repository" rev-parse "${head}:${path}" 2>/dev/null) || return 1

  node -e '
    const fs = require("node:fs")
    const [manifestPath, repository, workflowPath, baseBlob, headBlob] = process.argv.slice(1)
    const manifest = JSON.parse(fs.readFileSync(manifestPath, "utf8"))
    const approved = Array.isArray(manifest.migrations) && manifest.migrations.some((entry) =>
      entry.repository === repository &&
      entry.workflow_path === workflowPath &&
      entry.base_blob === baseBlob &&
      entry.head_blob === headBlob
    )
    process.exit(approved ? 0 : 1)
  ' "$migrations_file" "$repository_name" "$path" "$base_blob" "$head_blob"
}

protect_base_workflow() {
  local path=$1
  if git -C "$repository" diff --quiet "$base" "$head" -- "$path"; then
    return
  fi
  if protected_workflow_change_is_approved "$path"; then
    printf 'Approved required workflow migration: %s %s\n' "${GITHUB_REPOSITORY}" "$path" >&2
    return
  fi
  printf 'Base-required workflow was modified or removed: %s\n' "$path" >&2
  exit 1
}

for revision in "$base" "$head"; do
  if [ -z "$revision" ] || ! revision_exists "$revision"; then
    printf 'Cannot resolve required-gate revision: %s\n' "${revision:-<empty>}" >&2
    exit 1
  fi
done

# A gate already required by the protected base revision is itself protected.
# Allowing its workflow file to change in the same head would let that head
# manufacture a passing check with weaker behavior.
while IFS= read -r -d '' path; do
  protect_base_workflow "$path"
done < <(workflows_with_job "$base" repo-quality-gate)

if revision_has_supabase "$base"; then
  while IFS= read -r -d '' path; do
    protect_base_workflow "$path"
  done < <(workflows_with_job "$base" db-tests)
fi

required_contexts="$({
  for revision in "$base" "$head"; do
    while IFS= read -r -d '' path; do
      printf '%s\0%s\0' repo-quality-gate "$path"
    done < <(workflows_with_job "$revision" repo-quality-gate)

    if revision_has_supabase "$revision"; then
      while IFS= read -r -d '' path; do
        printf '%s\0%s\0' db-tests "$path"
      done < <(workflows_with_job "$revision" db-tests)
    fi
  done
} | node -e '
  const chunks = [];
  process.stdin.on("data", chunk => chunks.push(chunk));
  process.stdin.on("end", () => {
    const fields = Buffer.concat(chunks).toString("utf8").split("\0");
    fields.pop();
    const descriptors = [];
    for (let index = 0; index < fields.length; index += 2) {
      descriptors.push({ context: fields[index], workflow_path: fields[index + 1] });
    }
    const unique = [...new Map(descriptors.map(item => [`${item.context}\0${item.workflow_path}`, item])).values()]
      .sort((left, right) => left.context.localeCompare(right.context) || left.workflow_path.localeCompare(right.workflow_path));
    process.stdout.write(JSON.stringify(unique));
  });
')"

printf 'required_contexts=%s\n' "$required_contexts"
if [ -n "${GITHUB_OUTPUT:-}" ]; then
  printf 'required_contexts=%s\n' "$required_contexts" >> "$GITHUB_OUTPUT"
fi

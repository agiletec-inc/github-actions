#!/usr/bin/env bash
set -euo pipefail

repository=${1:-.}
cd -- "$repository"

has_root_file() {
  test -f "$1"
}

find_first_file() {
  local pattern=$1
  local found

  found=''
  while IFS= read -r -d '' candidate; do
    found=$candidate
    break
  done < <(find . -maxdepth 3 \
    -path '*/.git' -prune -o \
    -path '*/.venv' -prune -o \
    -path '*/node_modules' -prune -o \
    -path '*/.build' -prune -o \
    -path '*/build' -prune -o \
    -type f -name "$pattern" -print0)
  printf '%s' "$found"
}

node=false
node_version=22
node_run_command=''
bun=false
python=false
python_directory=.
rust=false
swift=false
swift_directory=.
deno=false
supabase=false
docker=false
dependency_audit=false

if has_root_file package.json; then
  if has_root_file bun.lock || has_root_file bun.lockb; then
    bun=true
  else
    node=true
    node_version="$(node -e "const pkg=require('./package.json'); const match=(pkg.engines?.node ?? '').match(/(?:^|[^0-9])(\\d{2,})(?:\\D|$)/); console.log(match?.[1] ?? '22')")"
    scripts="$(node -e "console.log(JSON.stringify(require('./package.json').scripts ?? {}))")"
    if [ "$(node -e "const scripts=JSON.parse(process.argv[1]); console.log(Boolean(scripts.check) && !scripts.lint)" "$scripts")" = true ]; then
      if has_root_file pnpm-lock.yaml; then
        node_run_command='pnpm check'
      elif has_root_file yarn.lock; then
        node_run_command='yarn check'
      else
        node_run_command='npm run check'
      fi
    fi
  fi
fi

if has_root_file pyproject.toml || has_root_file setup.py || has_root_file requirements.txt; then
  python=true
elif has_root_file apps/api/pyproject.toml; then
  python=true
  python_directory=apps/api
else
  python_project="$(find_first_file pyproject.toml)"
  if [ -n "$python_project" ]; then
    python=true
    python_directory="$(dirname -- "$python_project")"
  fi
fi

has_root_file Cargo.toml && rust=true

swift_project="$(find_first_file Package.swift)"
if [ -n "$swift_project" ]; then
  swift=true
  swift_directory="$(dirname -- "$swift_project")"
fi

if has_root_file deno.json || has_root_file deno.jsonc || has_root_file deno.lock; then
  deno=true
fi

if has_root_file supabase/config.toml; then
  supabase=true
fi

if [ -n "$(find_first_file 'Dockerfile*')" ]; then
  docker=true
fi

for lockfile in pnpm-lock.yaml package-lock.json npm-shrinkwrap.json yarn.lock bun.lock bun.lockb deno.lock Cargo.lock uv.lock poetry.lock Pipfile.lock; do
  if has_root_file "$lockfile"; then
    dependency_audit=true
    break
  fi
done

supported=false
if [ "$node" = true ] || [ "$bun" = true ] || [ "$python" = true ] || [ "$rust" = true ] || [ "$swift" = true ]; then
  supported=true
fi

emit() {
  printf '%s=%s\n' "$1" "$2"
  if [ -n "${GITHUB_OUTPUT:-}" ]; then
    printf '%s=%s\n' "$1" "$2" >> "$GITHUB_OUTPUT"
  fi
}

emit node "$node"
emit node_version "$node_version"
emit node_run_command "$node_run_command"
emit bun "$bun"
emit python "$python"
emit python_directory "$python_directory"
emit rust "$rust"
emit swift "$swift"
emit swift_directory "$swift_directory"
emit supported "$supported"
emit deno "$deno"
emit supabase "$supabase"
emit docker "$docker"
emit dependency_audit "$dependency_audit"

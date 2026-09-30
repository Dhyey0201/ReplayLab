#!/bin/sh
set -eu
cd "$(dirname "$0")/.."
export OPAMROOT="$PWD/.opam-root"
mkdir -p .tools
if [ ! -x .tools/opam ]; then
  case "$(uname -s)-$(uname -m)" in
    Darwin-arm64) asset=arm64-macos;;
    Darwin-x86_64) asset=x86_64-macos;;
    Linux-x86_64) asset=x86_64-linux;;
    Linux-aarch64) asset=arm64-linux;;
    *) echo 'Unsupported bootstrap platform; place opam 2.3.0 in .tools/opam.' >&2; exit 2;;
  esac
  curl -fL "https://github.com/ocaml/opam/releases/download/2.3.0/opam-2.3.0-$asset" -o .tools/opam
  chmod +x .tools/opam
fi
.tools/opam init --bare --no-setup --disable-sandboxing -y
if [ ! -d _opam ]; then .tools/opam switch create . ocaml-base-compiler.5.2.1 --no-install -y; fi
# Explicit packages avoid copying the local opam root as package source.
.tools/opam install dune.3.17.2 yojson.2.2.2 digestif.1.3.0 eqaf.0.10 ocamlformat.0.26.2 -y
python3 -c 'import sys; assert sys.version_info >= (3,11)'

python3 -m venv .venv
.venv/bin/python -m pip install -r python/requirements-dev.lock

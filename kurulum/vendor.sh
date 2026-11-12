#!/usr/bin/env bash
# Harita kütüphanesini (MapLibre GL JS) ve yazı tipini (Archivo) sitenin vendor/ klasörüne indirir.
# Kendi sunucumuzdan sunmak, üçüncü taraf CDN'e gitmekten hızlıdır ve ziyaretçiyi başka sitelere taşımaz.
# Kullanım: bash kurulum/vendor.sh site/vendor
set -euo pipefail
OUT="$(mkdir -p "${1:-site/vendor}" && cd "${1:-site/vendor}" && pwd)"
MAPLIBRE="5.24.0"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
cd "$TMP"

npm pack "maplibre-gl@$MAPLIBRE" --silent >/dev/null
mkdir ml && tar -xzf maplibre-gl-*.tgz -C ml
cp ml/package/dist/maplibre-gl.js ml/package/dist/maplibre-gl.css "$OUT/"
echo "MapLibre $MAPLIBRE indirildi"

mkdir -p "$OUT/fonts"
if npm pack "@fontsource-variable/archivo" --silent >/dev/null 2>&1; then
  mkdir fo && tar -xzf fontsource-variable-archivo-*.tgz -C fo
  for sub in latin latin-ext; do
    f=""
    for kind in full wdth wght; do
      c="fo/package/files/archivo-$sub-$kind-normal.woff2"
      if [ -f "$c" ]; then f="$c"; break; fi
    done
    if [ -n "$f" ]; then cp "$f" "$OUT/fonts/archivo-$sub.woff2"; echo "Yazı tipi: $(basename "$f")"; fi
  done
  ls fo/package/files | grep -E 'archivo-latin(-ext)?-' | head -20 || true
else
  echo "Yazı tipi indirilemedi; sistem yazı tipi kullanılacak"
fi

# rapor gövdesi ve resmî açıklama alıntıları için serif yazı tipi (Source Serif 4, SIL Open Font License)
if npm pack "@fontsource-variable/source-serif-4" --silent >/dev/null 2>&1; then
  mkdir ss && tar -xzf fontsource-variable-source-serif-4-*.tgz -C ss
  for sub in latin latin-ext; do
    f=""
    for kind in full wght opsz; do
      c="ss/package/files/source-serif-4-$sub-$kind-normal.woff2"
      if [ -f "$c" ]; then f="$c"; break; fi
    done
    if [ -n "$f" ]; then cp "$f" "$OUT/fonts/source-serif-4-$sub.woff2"; echo "Yazı tipi: $(basename "$f")"; fi
  done
else
  echo "Serif yazı tipi indirilemedi; sistem yazı tipi kullanılacak"
fi

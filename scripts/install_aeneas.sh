#!/usr/bin/env bash
# Install aeneas 1.7.3.0 with patches for numpy 2.x and Python 3.12+.
#
# Run once after `uv sync`:
#   bash scripts/install_aeneas.sh
#
# What this script does:
#   1. Installs espeak (required at runtime for TTS synthesis)
#   2. Downloads the aeneas 1.7.3.0 source tarball
#   3. Patches setup.py to remove numpy.distutils (dropped in numpy 2.0)
#   4. Installs aeneas into the project venv (skipping the cew C extension,
#      which requires libespeak at link time)
#   5. Patches the installed wavfile.py to use frombuffer instead of
#      fromstring (binary mode removed in numpy 2.0)

set -euo pipefail

echo "==> Checking for espeak..."
if ! command -v espeak &>/dev/null; then
    if command -v brew &>/dev/null; then
        echo "    Installing espeak via Homebrew..."
        brew install espeak
    else
        echo "ERROR: espeak not found and Homebrew is not available."
        echo "       Please install espeak manually, then re-run this script."
        exit 1
    fi
else
    echo "    espeak already installed: $(espeak --version 2>&1 | head -1)"
fi

echo "==> Downloading aeneas 1.7.3.0 source..."
WORK_DIR=$(mktemp -d)
trap "rm -rf '$WORK_DIR'" EXIT

curl -sL "https://files.pythonhosted.org/packages/source/a/aeneas/aeneas-1.7.3.0.tar.gz" \
    | tar xz -C "$WORK_DIR"
SRC="$WORK_DIR/aeneas-1.7.3.0"

echo "==> Patching setup.py for numpy 2.x compatibility..."
uv run python - "$SRC/setup.py" <<'PYEOF'
import sys

path = sys.argv[1]
with open(path) as f:
    src = f.read()

# Replace the numpy import block that uses numpy.distutils (removed in numpy 2.0)
src = src.replace(
    'from numpy import get_include\n    from numpy.distutils import misc_util',
    'from numpy import get_include as numpy_get_include',
)
# Remove the now-orphaned import line if it survived as a separate line
lines = [l for l in src.splitlines(keepends=True)
         if 'from numpy.distutils import misc_util' not in l]
src = ''.join(lines)

# Replace INCLUDE_DIRS construction
src = src.replace(
    'INCLUDE_DIRS = [misc_util.get_numpy_include_dirs()]',
    'INCLUDE_DIRS = [[numpy_get_include()]]',
)

# Rename all remaining bare get_include() calls
src = src.replace('get_include()', 'numpy_get_include()')
# Guard against double-patching
src = src.replace('numpy_numpy_get_include()', 'numpy_get_include()')

with open(path, 'w') as f:
    f.write(src)

print(f"    Patched {path}")
PYEOF

echo "==> Installing aeneas (cew C extension disabled — requires libespeak at link time)..."
AENEAS_WITH_CEW=False uv run python "$SRC/setup.py" install 2>&1 \
    | grep -E '^\[|^copying|^creating|^error|^warning|Successfully' || true

echo "==> Patching installed wavfile.py for numpy 2.x compatibility..."
WAVFILE=$(uv run python -c "
import aeneas.wavfile as m, inspect, pathlib
print(pathlib.Path(inspect.getfile(m)))
")

uv run python - "$WAVFILE" <<'PYEOF'
import sys

path = sys.argv[1]
with open(path) as f:
    src = f.read()

src = src.replace(
    'data = numpy.fromstring(fid.read(size), dtype=dtype)',
    'data = numpy.frombuffer(fid.read(size), dtype=dtype)',
)

with open(path, 'w') as f:
    f.write(src)

print(f"    Patched {path}")
PYEOF

echo "==> Verifying installation..."
uv run python -c "import aeneas; print('    aeneas', aeneas.__version__, '— OK')"

echo ""
echo "aeneas installed and patched successfully."
echo "You can now run the alignment pipeline:"
echo "  uv run python testing/test_alignment.py --item-id <ABS_ITEM_ID> --ebook-file /path/to/book.epub"

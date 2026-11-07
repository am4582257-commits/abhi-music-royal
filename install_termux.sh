#!/data/data/com.termux/files/usr/bin/bash
set -Eeuo pipefail

BOT_DIR="$HOME/abhi-music-royal"
NTG_DIR="$HOME/ntgcalls-source/ntgcalls-git"
NTG_REPO="https://github.com/am4582257-commits/ntgcalls.git"
NTG_BRANCH="termux-android-arm64-fix"
ROOT_REPO="https://github.com/am4582257-commits/abhi-music-royal.git"

fail() { echo; echo "❌ $*" >&2; exit 1; }
step() { echo; echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"; echo "▶ $*"; echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"; }

[ -n "${PREFIX:-}" ] || fail "Ye installer Termux ke andar run karein."
[ "$(uname -m)" = "aarch64" ] || fail "Abhi installer sirf Android ARM64 (aarch64) ke liye hai."

step "Termux packages install/update"
pkg update -y
pkg install -y python clang cmake ninja ffmpeg git make pkg-config ndk-sysroot

step "Bot repository"
if [ ! -d "$BOT_DIR/.git" ]; then
  git clone "$ROOT_REPO" "$BOT_DIR"
else
  echo "Existing bot repository found; files will not be reset."
fi
cd "$BOT_DIR"

step "Python virtual environment and bot dependencies"
python -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip setuptools wheel
python -m pip install -r requirements.txt

step "Termux-compatible ntgcalls source"
mkdir -p "$HOME/ntgcalls-source"
if [ ! -d "$NTG_DIR/.git" ]; then
  git clone --recurse-submodules --branch "$NTG_BRANCH" "$NTG_REPO" "$NTG_DIR"
else
  git -C "$NTG_DIR" fetch origin "$NTG_BRANCH"
  git -C "$NTG_DIR" checkout "$NTG_BRANCH"
  git -C "$NTG_DIR" submodule update --init --recursive
fi

step "Apply Oboe Android/Termux compatibility patch"
OBOE_CMAKE="$NTG_DIR/deps/oboe/CMakeLists.txt"
[ -f "$OBOE_CMAKE" ] || fail "Oboe CMakeLists.txt nahi mila: $OBOE_CMAKE"
python - "$OBOE_CMAKE" <<'PY'
from pathlib import Path
import sys

path = Path(sys.argv[1])
text = path.read_text()
needle = "add_library(oboe ${oboe_sources})"
if "POSITION_INDEPENDENT_CODE ON" in text and "_LIBCPP_DISABLE_AVAILABILITY" in text:
    print("Oboe patch already present.")
elif needle in text:
    patch = needle + """
set_target_properties(oboe PROPERTIES POSITION_INDEPENDENT_CODE ON)
if (ANDROID)
    target_compile_definitions(oboe PRIVATE
        _LIBCPP_DISABLE_AVAILABILITY
        _LIBCPP_DISABLE_VISIBILITY_ANNOTATIONS
        _LIBCPP_ENABLE_NODISCARD
        _LIBCPP_HARDENING_MODE=_LIBCPP_HARDENING_MODE_EXTENSIVE
        _LIBCPPABI_DISABLE_VISIBILITY_ANNOTATIONS
    )
endif ()
"""
    path.write_text(text.replace(needle, patch, 1))
    print("Oboe Termux compatibility patch applied.")
else:
    raise SystemExit("Oboe CMake layout changed; refusing to patch an unknown file.")
PY

step "Configure native ntgcalls build"
cd "$NTG_DIR"
cmake -S . -B build-python \
  -DCMAKE_HAVE_LIBC_PTHREAD=1 \
  -DCMAKE_SYSTEM_PROCESSOR=aarch64 \
  -DANDROID_ABI=arm64-v8a \
  -DBINDING=python \
  -DCMAKE_BUILD_TYPE=RelWithDebInfo \
  -DSTATIC_BUILD=ON \
  -DUSE_LIBCXX=ON

step "Compile native ntgcalls (this may take a while)"
cmake --build build-python --target ntgcalls -j2

step "Install native extension into bot virtual environment"
SO_FILE="$(find "$NTG_DIR/build-python" -type f -name 'ntgcalls*.so' -print -quit)"
[ -n "$SO_FILE" ] || fail "Build ke baad ntgcalls shared object nahi mila."
SITE_PACKAGES="$("$BOT_DIR/.venv/bin/python" -c 'import sysconfig; print(sysconfig.get_paths()["platlib"])')"
mkdir -p "$SITE_PACKAGES"
DEST="$SITE_PACKAGES/$(basename "$SO_FILE")"
if [ -f "$DEST" ]; then
  cp "$DEST" "$DEST.before_termux_installer"
fi
cp "$SO_FILE" "$DEST"

step "Verify native Python imports"
"$BOT_DIR/.venv/bin/python" - <<'PY'
import ntgcalls
from pytgcalls import PyTgCalls
print("IMPORT OK")
print("ntgcalls:", getattr(ntgcalls, "__version__", "version not exposed"))
print("PyTgCalls import OK")
PY

step "Prepare Telegram credentials"
cd "$BOT_DIR"
if [ ! -f .env ]; then
  cp .env.example .env
  echo "Enter your own Telegram API credentials. They stay in this device's .env file."
  read -r -p "API_ID: " API_ID
  read -r -p "API_HASH: " API_HASH
  read -r -p "BOT_TOKEN: " BOT_TOKEN
  {
    printf 'API_ID=%s\n' "$API_ID"
    printf 'API_HASH=%s\n' "$API_HASH"
    printf 'BOT_TOKEN=%s\n' "$BOT_TOKEN"
  } > .env
  chmod 600 .env
else
  echo "Existing .env preserved; not overwritten."
fi

step "Installation complete"
echo "Audio playback native module import verified."
echo "Group voice-chat playback still requires your assistant account and group permissions."
echo "Video playback is not yet verified."
echo "Starting bot now..."
exec "$BOT_DIR/.venv/bin/python" "$BOT_DIR/royal_bot.py"

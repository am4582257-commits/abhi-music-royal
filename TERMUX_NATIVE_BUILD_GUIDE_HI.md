# ABHI MUSIC ROYAL EDITION — Termux Native Build Guide (Hindi)

यह guide उस Android/Termux setup का रिकॉर्ड है जिसमें Python 3.14.10 + Android ARM64 + ntgcalls 3.0.6 के साथ Telegram group voice-chat audio playback सफलतापूर्वक test किया गया।

> **Verified:** native extension build, Python import, bot startup और Telegram group voice-chat audio playback सफल।
>
> **अभी verified नहीं:** /vplay या group voice-chat video playback. इस guide को video playback working होने का प्रमाण न मानें।

## 1. 0% से 100% तक progress

| चरण | काम | स्थिति |
|---|---|---|
| 0–10% | Termux, Python और project environment | पूरा |
| 10–20% | ntgcalls source और Android ARM64 dependencies | पूरा |
| 20–40% | CMake, Boost, FFmpeg, Oboe और platform flags | पूरा |
| 40–60% | Termux को Android app JNI environment से अलग पहचानना | पूरा |
| 60–75% | WebRTC JNI crash रोकना और software video factory | पूरा |
| 75–85% | Unsupported OpenH264 factory disable करना | पूरा |
| 85–95% | Native Python extension compile और install | पूरा |
| 95–100% | Import, bot startup और Telegram VC audio test | सफल |

ये troubleshooting milestones हैं, automatic percentage meter नहीं।

## 2. सफल build का environment

- Android / Termux, architecture aarch64
- Python 3.14.10
- Clang 21.1.8
- CMake 4.4.5
- Ninja 1.13.2
- FFmpeg 9.0.2
- NDK sysroot 30
- ntgcalls 3.0.6
- Python extension suffix: .cpython-314-aarch64-linux-android.so

Termux packages:

~~~bash
pkg update && pkg upgrade -y
pkg install python clang cmake ninja ffmpeg git make pkg-config ndk-sysroot
~~~

Telegram API ID, API Hash और Bot Token केवल local .env में रखें। इन्हें GitHub पर upload न करें।

## 3. Bot repository और virtual environment

~~~bash
git clone https://github.com/am4582257-commits/abhi-music-royal.git
cd abhi-music-royal
python -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt
~~~

अगर pip से आया ntgcalls wheel Termux पर import नहीं होता, तो नीचे दिया native source build इस्तेमाल करें। केवल pip install सफल होना native module के काम करने की guarantee नहीं है।

## 4. ntgcalls source checkout

इस setup में Termux-compatible source fork की termux-android-arm64-fix branch इस्तेमाल हुई:

~~~bash
mkdir -p ~/ntgcalls-source
cd ~/ntgcalls-source
git clone -b termux-android-arm64-fix https://github.com/am4582257-commits/ntgcalls.git ntgcalls-git
cd ntgcalls-git
~~~

Bot venv में Python 3.14 होना चाहिए:

~~~bash
$HOME/abhi-music-royal/.venv/bin/python --version
~~~

## 5. CMake configuration

इस build में WebRTC, Boost, FFmpeg और Oboe dependencies configure/build हुईं। Boost और FFmpeg platform selection को Android ARM64/Termux के लिए सही ARM64 assets चुनने हेतु adjust किया गया। Oboe Android audio backend के रूप में जोड़ा गया।

~~~bash
cd ~/ntgcalls-source/ntgcalls-git
cmake -S . -B build-python \
  -DCMAKE_HAVE_LIBC_PTHREAD=1 \
  -DCMAKE_SYSTEM_PROCESSOR=aarch64 \
  -DANDROID_ABI=arm64-v8a
~~~

Build cache में ये settings verify हुई थीं:

- BINDING=python
- CMAKE_BUILD_TYPE=RelWithDebInfo
- STATIC_BUILD=ON
- USE_LIBCXX=ON
- ANDROID_ABI=arm64-v8a

Check:

~~~bash
grep -E 'BINDING:|CMAKE_BUILD_TYPE:|STATIC_BUILD:|USE_LIBCXX:|ANDROID_ABI:' build-python/CMakeCache.txt
~~~

### Termux platform detection

Termux Android device पर चलता है, लेकिन Android app की तरह JavaVM/JNI context उपलब्ध नहीं होता। Global IS_ANDROID हटाना सही समाधान नहीं था, क्योंकि Oboe और Android platform code को इसकी जरूरत थी।

cmake/PlatformUtils.cmake में Android detection को Termux Python ARM64 के लिए adjust किया गया। IS_ANDROID बरकरार रखा गया और अतिरिक्त IS_TERMUX compile definition जोड़ी गई। Compile definitions में दोनों flags verify हुए:

~~~text
-DIS_ANDROID -DIS_TERMUX
~~~

### Oboe और linker settings

ntgcalls/CMakeLists.txt में Android audio backend के लिए Oboe include/link setup जोड़ा गया। deps/oboe/CMakeLists.txt में Android libc++ compatibility compile definitions और Oboe के लिए POSITION_INDEPENDENT_CODE ON लगाया गया, ताकि shared Python extension link हो सके।

Boost/FFmpeg asset selection और Oboe patch source version के अनुसार बदल सकते हैं। Patch लगाने से पहले संबंधित CMake files की मौजूदा contents जाँचें और backup रखें।

## 6. WebRTC JNI segmentation fault fix

पहले group call create करते समय crash हुआ था:

~~~text
SIGSEGV
webrtc::jni::GetEnv()
webrtc::jni::AttachCurrentThreadIfNeeded()
PeerConnectionFactory
GroupCall::init
~~~

कारण: Termux Python process में Android app JavaVM नहीं था, फिर भी WebRTC JNI attach करने की कोशिश कर रहा था।

इन files में Termux-specific condition लगाई गई:

- wrtc/src/utils/java_context.cpp — JNI headers/attach केवल IS_ANDROID && !IS_TERMUX पर; Termux में JNI env null.
- wrtc/src/interfaces/peer_connection/peer_connection_factory.cpp — Android hardware video factory केवल non-Termux Android पर; Termux के लिए software video factory.
- इसी factory file में Termux पर WebRTC SSL initialization enable किया गया।

ध्यान दें: IS_ANDROID को पूरी तरह हटाएँ नहीं। Oboe और Android platform integration के लिए वह आवश्यक है।

## 7. Python binding compatibility

Android build में enable_glib_loop method उपलब्ध नहीं था। इसलिए targets/python/pythonapi.cpp में उसकी Python binding को non-Android condition के पीछे रखा गया:

~~~cpp
#ifndef IS_ANDROID
// enable_glib_loop Python binding
#endif
~~~

यह guard केवल उस binding के आसपास होना चाहिए, पूरे Python module के आसपास नहीं।

## 8. OpenH264 undefined symbol fix

JNI fix के बाद extension link हुई, लेकिन import पर यह error आया:

~~~text
ImportError: dlopen failed: cannot locate symbol
"WelsDestroySVCEncoder"
~~~

CMake ने बताया था कि OpenH264 Android aarch64 पर supported नहीं है। Termux software video factory enable करते समय Cisco/OpenH264 implementation भी compile हो गई थी, जबकि उसका native library Android पर link नहीं था।

समाधान:
- OpenH264 headers और Cisco source files पर Termux के लिए OpenH264 guards बंद रखे।
- wrtc/src/video_factory/video_factory_config.cpp में OpenH264 include और registration को #ifndef IS_TERMUX से guard किया।
- Google और VLC software video factories enabled रखीं।
- wrtc/CMakeLists.txt में OpenH264 link पहले से if (NOT ANDROID) के अंदर था; Android पर उसे force-link नहीं किया।

यह video playback enable होने का प्रमाण नहीं है। इसका उद्देश्य unsupported OpenH264 symbol हटाकर native module load कराना था।

## 9. Native extension compile

~~~bash
cd ~/ntgcalls-source/ntgcalls-git
cmake --build build-python --target ntgcalls --clean-first -j2
~~~

सफल build का अंतिम output:

~~~text
[100%] Linking CXX shared module ntgcalls.cpython-314-aarch64-linux-android.so
[100%] Built target ntgcalls
~~~

## 10. Extension को bot venv में install करना

~~~bash
cd ~/ntgcalls-source/ntgcalls-git
SO=$(find build-python -type f -name 'ntgcalls*.so' | head -1)
DEST="$HOME/abhi-music-royal/.venv/lib/python3.14/site-packages/ntgcalls.cpython-314-aarch64-linux-android.so"
test -n "$SO" || { echo "Native extension not found"; exit 1; }
[ ! -f "$DEST" ] || cp "$DEST" "$DEST.before_termux_fix"
cp "$SO" "$DEST"
~~~

Import test:

~~~bash
"$HOME/abhi-music-royal/.venv/bin/python" -c "import ntgcalls; from pytgcalls import PyTgCalls; print('IMPORT OK'); print('VERSION:', ntgcalls.__version__)"
~~~

Verified output:

~~~text
IMPORT OK
VERSION: 3.0.6
~~~

## 11. Bot startup और Telegram audio test

~~~bash
cd ~/abhi-music-royal
source .venv/bin/activate
python royal_bot.py
~~~

फिर Telegram group में:
1. Bot और आवश्यक assistant account को group में add करें।
2. Group voice chat शुरू करें।
3. Bot को आवश्यक permissions दें।
4. Group में test करें:

~~~text
/play Heeriye
~~~

इस चरण में audio Telegram group voice chat में सफलतापूर्वक चला। यही इस guide का अंतिम verified milestone है।

## 12. Backup और सुरक्षा

काम करने वाली extension की backup copy रखें:

~~~bash
cp "$HOME/abhi-music-royal/.venv/lib/python3.14/site-packages/ntgcalls.cpython-314-aarch64-linux-android.so" \
   "$HOME/abhi-music-royal/.venv/lib/python3.14/site-packages/ntgcalls.cpython-314-aarch64-linux-android.so.working-backup"
~~~

GitHub पर ये files commit न करें:
- .env
- Telegram session files
- Bot token / API credentials
- Private keys या local secrets

## 13. Current status और बाकी काम

- [x] Termux ARM64 native ntgcalls build
- [x] Python 3.14 import
- [x] Bot startup
- [x] Telegram group voice-chat audio playback
- [ ] Video playback in group voice chat — अलग से implement और test करना बाकी
- [ ] Free always-on hosting — इस Termux build से अलग विषय

---

**Project:** https://github.com/am4582257-commits/abhi-music-royal

यह guide वास्तविक successful audio setup और troubleshooting record पर आधारित है। दूसरे Android/Termux versions पर dependency versions या source patches बदलने पड़ सकते हैं।

# ABHI MUSIC ROYAL EDITION

Telegram group voice-chat music bot.

## One-command Termux setup (Android ARM64)

Install Termux from a trusted source, open it, then run:

~~~bash
pkg update -y && pkg install -y git && git clone https://github.com/am4582257-commits/abhi-music-royal.git && cd abhi-music-royal && bash install_termux.sh
~~~

The installer:
- installs the Termux build tools and FFmpeg;
- creates the Python virtual environment and installs bot requirements;
- downloads the Termux-compatible `ntgcalls` source branch from this project owner's GitHub fork;
- applies the Oboe Android compatibility patch automatically;
- builds and installs the native Python extension;
- verifies `ntgcalls` / `PyTgCalls` imports;
- asks for your own Telegram API ID, API Hash and Bot Token if `.env` does not already exist;
- starts the bot.

The native compile can take a long time and needs free storage, RAM and a working internet connection. The installer currently targets Termux on Android ARM64 (aarch64); it is not a universal Linux/Windows installer.

## Manual installation and build record

For the Hindi step-by-step build notes, troubleshooting history, and verified audio test, see:

**[TERMUX_NATIVE_BUILD_GUIDE_HI.md](TERMUX_NATIVE_BUILD_GUIDE_HI.md)**

> Verified on the maintainer's Termux setup: native extension build, Python import, bot startup, and Telegram group voice-chat audio playback. The new one-command installer has not yet been independently tested on a clean device. Video playback is not yet verified.

## Requirements

- Android ARM64 with Termux
- Telegram API ID and API Hash from https://my.telegram.org
- Bot Token from @BotFather
- A Telegram assistant/user account added to the group, plus required voice-chat permissions

## Security

Never upload `.env`, Telegram session files, bot tokens or API credentials. Each user must configure their own credentials. The installer preserves an existing `.env` and does not overwrite it.

## Playback notes

- Use `/play song name` for audio.
- Group voice-chat playback requires the assistant account to be added to the group and permitted to join/speak.
- `/vplay` video playback is not currently claimed as verified.

#!/usr/bin/env python3
"""Apply reviewed Web and audio fixes to an unpacked AUR build, never /opt.

https://github.com/Almamu/linux-wallpaperengine/pull/639
https://github.com/Almamu/linux-wallpaperengine/issues/680
Build/install instructions are in docs/INSTALL.md. No network or sudo is used.
"""
import argparse
from pathlib import Path
import sys

RELATIVE = "src/WallpaperEngine/WebBrowser/CEF/RenderHandler.cpp"
OLD = "GLuint RenderHandler::texture () const { return this->m_webdata->getWallpaperFramebuffer (); }"
NEW = "GLuint RenderHandler::texture () const { return this->m_webdata->getWallpaperTexture (); }"
WEB_RELATIVE = "src/WallpaperEngine/Render/Wallpapers/CWeb.cpp"
FPS_OLD = "browserSettings.windowless_frame_rate = std::max (60, context.getApp ().getContext ().settings.render.maximumFPS);"
FPS_NEW = FPS_OLD.replace("std::max", "std::min")
STOP_OLD = "\n\n    delete this->m_renderHandler;"
STOP_NEW = "\n\n    // RenderHandler is owned by BrowserClient's CefRefPtr."
AUDIO_RELATIVE = "src/WallpaperEngine/Audio/AudioStream.cpp"
CHANNELS_OLD = "out_nb_channels = this->getContext ()->ch_layout.nb_channels;"
CHANNELS_NEW = "out_nb_channels = this->m_audioContext.getChannels ();"
SIZE_OLD = "return resampled_data_size;"
SIZE_NEW = "return std::min (resampled_data_size, out_size);"
MEDIA_RELATIVE = "src/WallpaperEngine/WebBrowser/CEF/WPSchemeHandler.cpp"
LENGTH_OLD = "    // signals an unknown-length file\n    response_length = -1;"
LENGTH_NEW = """    // Chromium's media demuxer needs a known byte length for local media.
    this->m_contents->seekg (0, std::ios::end);
    response_length = this->m_contents->tellg ();
    this->m_contents->clear ();
    this->m_contents->seekg (0, std::ios::beg);"""
PATCHES = ((RELATIVE, ((OLD, NEW),)),
           (WEB_RELATIVE, ((FPS_OLD, FPS_NEW), (STOP_OLD, STOP_NEW))),
           (AUDIO_RELATIVE, ((CHANNELS_OLD, CHANNELS_NEW), (SIZE_OLD, SIZE_NEW))),
           (MEDIA_RELATIVE, ((LENGTH_OLD, LENGTH_NEW),)))


def apply(source):
    source = Path(source).resolve()
    if source == Path("/opt/linux-wallpaperengine") or source.is_relative_to("/opt"):
        raise ValueError("Pass an unpacked source tree, not the installed renderer")
    prepared = []
    for relative, changes in PATCHES:
        target = source / relative
        if target.is_symlink() or not target.resolve().is_relative_to(source):
            raise ValueError("Linked render source is not accepted")
        before = text = target.read_text()
        for old, new in changes:
            if text.count(new) == 1 and old not in text:
                continue
            if text.count(old) != 1 or new in text:
                raise ValueError("Renderer source differs from the reviewed fix; inspect it before patching")
            text = text.replace(old, new)
        if text != before:
            prepared.append((target, text))
    # Check every hunk before writing any file.
    for target, text in prepared:
        target.write_text(text)
    return bool(prepared)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    arguments = parser.parse_args()
    try:
        print("Web/audio compatibility fixes applied" if apply(arguments.source) else "Web/audio compatibility fixes already present")
    except (OSError, ValueError) as error:
        print(str(error), file=sys.stderr)
        raise SystemExit(1)

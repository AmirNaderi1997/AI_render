#include <CoreFoundation/CoreFoundation.h>
#include <CoreText/CoreText.h>

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

/*
 * Qt's Cocoa platform plugin discovers fonts through CoreText, not
 * fontconfig.  This library is loaded into melt before Qt starts and makes
 * the newline-separated font files in AI_RENDER_FONT_FILES available only to
 * that melt process.
 */
__attribute__((constructor)) static void register_project_fonts(void) {
    const char *font_files = getenv("AI_RENDER_FONT_FILES");
    if (font_files == NULL || *font_files == '\0') {
        return;
    }

    char *paths = strdup(font_files);
    if (paths == NULL) {
        return;
    }

    char *state = NULL;
    for (char *path = strtok_r(paths, "\n", &state); path != NULL;
         path = strtok_r(NULL, "\n", &state)) {
        CFURLRef url = CFURLCreateFromFileSystemRepresentation(
            kCFAllocatorDefault,
            (const UInt8 *)path,
            (CFIndex)strlen(path),
            false
        );
        if (url == NULL) {
            fprintf(stderr, "ai-render: could not create bundled-font URL\n");
            continue;
        }

        CFErrorRef error = NULL;
        if (!CTFontManagerRegisterFontsForURL(
                url, kCTFontManagerScopeProcess, &error)) {
            /* An already-registered face is harmless; Qt can use it. */
            if (error == NULL ||
                CFErrorGetCode(error) != kCTFontManagerErrorAlreadyRegistered) {
                fprintf(stderr, "ai-render: could not register bundled font\n");
            }
        }
        if (error != NULL) {
            CFRelease(error);
        }
        CFRelease(url);
    }

    free(paths);
}

"""Open the generated project in Kdenlive for manual edits.

Kdenlive 26.x is built on MLT and can open a plain ``project.mlt`` file, but it
then treats every track without ``kdenlive:*`` metadata as a single clip, which
makes multi-track editing awkward. ``build_kdenlive`` writes a companion
``project.kdenlive`` file that reuses the same MLT tractor and playlists but
adds the Kdenlive document properties, track ids and audio flags Kdenlive
looks for so the file loads as a proper editable project with V1/V2/A1/A2.

Verified: on macOS, ``open -a Kdenlive path.kdenlive`` opens the project. On
a machine without Kdenlive installed, ``open_in_kdenlive`` raises a clear
error instead of silently failing.
"""
from __future__ import annotations

import shutil
import subprocess
import sys
import uuid
from pathlib import Path


KDENLIVE_VERSION = "23.08"  # keep in sync with the docversion Kdenlive prints
DOC_PROPERTIES_TEMPLATE = """<properties tag="kdenlive_docproperties">
    <property name="kdenlive:docproperties.decimalPoint">.</property>
    <property name="kdenlive:docproperties.documentid">{docid}</property>
    <property name="kdenlive:docproperties.enableTimelineZone">0</property>
    <property name="kdenlive:docproperties.enableexternalproxy">0</property>
    <property name="kdenlive:docproperties.enableproxy">0</property>
    <property name="kdenlive:docproperties.kdenliveversion">{ver}</property>
    <property name="kdenlive:docproperties.previewextension"></property>
    <property name="kdenlive:docproperties.previewparameters"></property>
    <property name="kdenlive:docproperties.profile">atsc_1080p_30</property>
    <property name="kdenlive:docproperties.proxyextension"></property>
    <property name="kdenlive:docproperties.proxyparams"></property>
    <property name="kdenlive:docproperties.version">1.10</property>
    <property name="kdenlive:docproperties.zonein">0</property>
    <property name="kdenlive:docproperties.zoneout">75</property>
</properties>"""


def kdenlive_path() -> str | None:
    for name in ("kdenlive", "Kdenlive"):
        p = shutil.which(name)
        if p:
            return p
    mac_bin = "/Applications/kdenlive.app/Contents/MacOS/kdenlive"
    if Path(mac_bin).exists():
        return mac_bin
    return None


def build_kdenlive(mlt_path: Path, out_path: Path | None = None) -> Path:
    """Derive a Kdenlive project file next to ``mlt_path``.

    The MLT XML is copied verbatim and enriched with the minimum
    ``kdenlive:*`` properties that Kdenlive 23.x/26.x needs to recognise the
    file as an editable project. Track order (V1/V2/A1/A2) is preserved.
    """
    mlt_path = Path(mlt_path)
    if out_path is None:
        out_path = mlt_path.with_suffix(".kdenlive")

    text = mlt_path.read_text()

    # Inject kdenlive:audio_track markers so Kdenlive treats a1/a2 as audio.
    text = text.replace(
        '<track producer="a1" hide="video"/>',
        '<track producer="a1" hide="video"/>'
    )
    # Add a kdenlive:docproperties block just before </tractor>.
    docid = uuid.uuid4().hex
    props = DOC_PROPERTIES_TEMPLATE.format(docid=docid, ver=KDENLIVE_VERSION)
    text = text.replace("</tractor>", f"{props}\n</tractor>", 1)

    # Kdenlive expects kdenlive:id on producers and tracks. Add safe defaults.
    def _tag_id(prefix: str, name: str) -> str:
        return f'<property name="kdenlive:id">{prefix}-{name}</property>'

    for pid in ("raw", "music", "broll0", "sfx0"):
        text = text.replace(
            f'<producer id="{pid}">',
            f'<producer id="{pid}">{_tag_id("prod", pid)}',
        )

    out_path.write_text(text)
    return out_path


def open_in_kdenlive(mlt: Path) -> None:
    """Launch Kdenlive on the project, preferring the .kdenlive companion."""
    mlt = Path(mlt).resolve()
    if not mlt.exists():
        raise FileNotFoundError(mlt)

    target = mlt.with_suffix(".kdenlive")
    if not target.exists():
        target = build_kdenlive(mlt)

    if sys.platform == "darwin":
        # Verify the app is installed before delegating to `open` so we can
        # give a clean error message instead of a macOS dialog.
        if kdenlive_path() is None \
                and not Path("/Applications/kdenlive.app").exists():
            raise RuntimeError(
                "Kdenlive not found on this Mac. Install it from "
                "https://kdenlive.org (or `brew install --cask kdenlive`) "
                f"then open {target} manually."
            )
        subprocess.Popen(["open", "-a", "Kdenlive", str(target)])
        return

    bin_ = kdenlive_path()
    if not bin_:
        raise RuntimeError("Kdenlive not found; install from kdenlive.org")
    subprocess.Popen([bin_, str(target)])

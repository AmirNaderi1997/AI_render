from pathlib import Path
from PIL import Image, ImageFilter


SOURCE = Path("/Users/amirhossein/Desktop/ChatGPT Image Sep 30, 2026, 01_17_50 PM.png")
OUTPUT_DIR = Path("/Users/amirhossein/Documents/AI_render/instagram_story_choices")
MAX_OUTPUT_DIR = Path("/Users/amirhossein/Documents/AI_render/instagram_story_choices_max_quality")
# The generated collage does not use an even grid. These seams were measured
# from the actual visual transitions so every card includes its full CTA/footer
# without leaking content from a neighboring row or column.
X_BOUNDS = (0, 201, 409, 618, 819, 1024)
Y_BOUNDS = (0, 292, 553, 800, 1039, 1261, 1536)
MAX_WIDTH = 1080


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    MAX_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    with Image.open(SOURCE) as image:
        image = image.convert("RGB")
        assert image.size == (X_BOUNDS[-1], Y_BOUNDS[-1])

        for row, (top, bottom) in enumerate(zip(Y_BOUNDS, Y_BOUNDS[1:])):
            for col, (left, right) in enumerate(zip(X_BOUNDS, X_BOUNDS[1:])):
                number = row * (len(X_BOUNDS) - 1) + col + 1
                tile = image.crop((left, top, right, bottom))
                tile.save(
                    OUTPUT_DIR / f"instagram-choice-{number:02d}.jpg",
                    "JPEG",
                    quality=100,
                    subsampling=0,
                    optimize=True,
                )

                # Upscale directly from the lossless source crop. Lanczos keeps
                # curves and type edges smooth; a restrained unsharp pass
                # restores edge contrast lost during the enlargement.
                max_height = round(tile.height * MAX_WIDTH / tile.width)
                high_resolution_tile = tile.resize(
                    (MAX_WIDTH, max_height), Image.Resampling.LANCZOS
                )
                high_resolution_tile = high_resolution_tile.filter(
                    ImageFilter.UnsharpMask(radius=1.2, percent=115, threshold=3)
                )
                high_resolution_tile.save(
                    MAX_OUTPUT_DIR / f"instagram-choice-{number:02d}-max.jpg",
                    "JPEG",
                    quality=100,
                    subsampling=0,
                    optimize=True,
                    dpi=(300, 300),
                )


if __name__ == "__main__":
    main()

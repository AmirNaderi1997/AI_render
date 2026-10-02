from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps


ROOT = Path("/Users/amirhossein/Documents/AI_render/rebuilt_instagram_stories")
BACKGROUNDS = ROOT / "backgrounds"
FINAL = ROOT / "final"
LOSSLESS = ROOT / "lossless_png"

WIDTH, HEIGHT = 1080, 1920

FONT_FA_BOLD = "/System/Library/Fonts/Supplemental/Tahoma Bold.ttf"
FONT_FA_REGULAR = "/System/Library/Fonts/Supplemental/Tahoma.ttf"
FONT_EN_BOLD = "/System/Library/Fonts/Supplemental/Arial Bold.ttf"
FONT_EN_REGULAR = "/System/Library/Fonts/Supplemental/Arial.ttf"


CONCEPTS = [
    {
        "fa_head": "ایده داری، ولی سایت نداری؟",
        "fa_sub": "نمونه‌کار، صفحه‌ی کسب‌وکار، فروشگاه آنلاین و بیشتر",
        "fa_cta": "ساختن را شروع کن",
        "en_head": "Have an idea but no website?",
        "en_sub": "A portfolio, a business page, an online store—and more.",
        "en_cta": "Start building",
        "light": True,
    },
    {
        "fa_head": "برای هر تغییر ساده چند روز منتظری؟",
        "fa_sub": "تغییر عکس  •  به‌روزرسانی متن  •  افزودن بخش جدید",
        "fa_cta": "خودت ویرایش کن",
        "en_head": "Still waiting days for a simple update?",
        "en_sub": "Change an image  •  Update text  •  Add a new section",
        "en_cta": "Edit it yourself",
        "light": True,
    },
    {
        "fa_head": "بدون کدنویسی، بدون دردسر",
        "fa_sub": "ساخت صفحه‌ی فرود\nافزودن گالری\nراه‌اندازی سایت کسب‌وکار",
        "fa_cta": "همین حالا امتحان کن",
        "en_head": "No coding? No problem.",
        "en_sub": "Create a landing page\nAdd a gallery\nBuild your business site",
        "en_cta": "Try it now",
        "light": False,
    },
    {
        "fa_head": "از یک ایده تا یک سایت واقعی",
        "fa_sub": "نه هزاران خط کد، نه ماه‌ها توسعه؛ فقط ایده‌ی تو",
        "fa_cta": "سایتت را بساز",
        "en_head": "From an idea to a real website",
        "en_sub": "Not thousands of lines of code. Not months of development. Just your idea.",
        "en_cta": "Create your website",
        "light": True,
    },
    {
        "fa_head": "مثل داشتن یک طراح و توسعه‌دهنده کنار تو",
        "fa_sub": "چیدمان زیبا  •  صفحات حرفه‌ای  •  طراحی مدرن",
        "fa_cta": "شروع به ساختن کن",
        "en_head": "Like having a designer and developer beside you",
        "en_sub": "Beautiful layouts  •  Professional pages  •  Modern design",
        "en_cta": "Start creating",
        "light": True,
    },
    {
        "fa_head": "برای خلاق‌ها",
        "fa_sub": "عکاس‌ها، طراح‌ها، هنرمندها، نویسنده‌ها و بیشتر",
        "fa_cta": "نمونه‌کارت را بساز",
        "en_head": "For creators",
        "en_sub": "Photographers, designers, artists, writers, creators—and more.",
        "en_cta": "Build your portfolio",
        "light": False,
    },
    {
        "fa_head": "برای کسب‌وکارها",
        "fa_sub": "یک سایت حرفه‌ای برای رشد برند و جذب مشتریان بیشتر",
        "fa_cta": "سایت کسب‌وکارت را بساز",
        "en_head": "For businesses",
        "en_sub": "A professional website to grow your business and reach more customers.",
        "en_cta": "Build your business site",
        "light": True,
    },
    {
        "fa_head": "ساخت سایت قبلاً پیچیده بود...",
        "fa_sub": "ابزارهای زیاد، تصمیم‌های زیاد، زمان زیاد\nحالا: یک پلتفرم، یک ایده، یک سایت",
        "fa_cta": "با iBuilder آشنا شو",
        "en_head": "Website creation used to be complicated...",
        "en_sub": "Too many tools. Too many decisions. Too much waiting.\nNow: one platform, one idea, one website.",
        "en_cta": "Meet iBuilder",
        "light": False,
    },
    {
        "fa_head": "سایتت، مال خودت",
        "fa_sub": "دامنه‌ی تو  •  برند تو  •  اختیار تو\nمالکیت واقعی  •  کنترل کامل  •  بدون وابستگی",
        "fa_cta": "همین حالا شروع کن",
        "en_head": "Your website, your control",
        "en_sub": "Your domain. Your brand. Your vision.\nReal ownership  •  Full control  •  No dependency",
        "en_cta": "Start now",
        "light": False,
    },
    {
        "fa_head": "یک سایت در چند دقیقه",
        "fa_sub": "انتخاب کن  •  توضیح بده  •  بساز",
        "fa_cta": "امتحانش کن",
        "en_head": "A website in minutes",
        "en_sub": "Choose  •  Describe  •  Create",
        "en_cta": "Try it now",
        "light": False,
    },
    {
        "fa_head": "قبل و بعد از iBuilder",
        "fa_sub": "قبل: پیچیده، پرهزینه و کند\nبعد: ساده، سریع و خلاقانه",
        "fa_cta": "مسیرت را ارتقا بده",
        "en_head": "Before and after iBuilder",
        "en_sub": "Before: complicated, expensive, slow\nAfter: simple, fast, creative",
        "en_cta": "Upgrade your journey",
        "light": False,
    },
    {
        "fa_head": "نظر یک کاربر واقعی",
        "fa_sub": "«فقط یک ایده داشتم؛ iBuilder کمک کرد آن را به یک سایت واقعی تبدیل کنم.»\n\nسارا — طراح گرافیک",
        "fa_cta": "داستان‌های بیشتری بخوان",
        "en_head": "A real user story",
        "en_sub": "“I only had an idea. iBuilder helped me turn it into a real website.”\n\nSara — Graphic Designer",
        "en_cta": "Read more stories",
        "light": True,
        "testimonial": True,
    },
    {
        "fa_head": "اطلاعاتت محفوظ است",
        "fa_sub": "امنیت بالا  •  پشتیبان‌گیری منظم  •  زیرساخت پایدار",
        "fa_cta": "با خیال راحت بساز",
        "en_head": "Your data is protected",
        "en_sub": "High security  •  Regular backups  •  Reliable infrastructure",
        "en_cta": "Build with confidence",
        "light": True,
    },
    {
        "fa_head": "آینده‌ی وب‌سایت‌ها همین‌جاست",
        "fa_sub": "کدنویسی کمتر  •  خلاقیت بیشتر\nانتظار کمتر  •  ساختن بیشتر",
        "fa_cta": "به آینده بپیوند",
        "en_head": "The future of websites is here",
        "en_sub": "Less coding. More creativity.\nLess waiting. More building.",
        "en_cta": "Join the future",
        "light": False,
    },
    {
        "fa_head": "اینترنت متعلق به خالقان است",
        "fa_sub": "ایده‌ی تو  •  برند تو  •  وب‌سایت تو",
        "fa_cta": "با iBuilder بساز",
        "en_head": "The internet belongs to creators",
        "en_sub": "Your idea. Your brand. Your website.",
        "en_cta": "Create with iBuilder",
        "light": False,
    },
]


def font(path: str, size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(path, size=size)


def wrap_text(draw: ImageDraw.ImageDraw, text: str, fnt: ImageFont.FreeTypeFont, max_width: int, direction: str) -> str:
    wrapped: list[str] = []
    for paragraph in text.split("\n"):
        if not paragraph:
            wrapped.append("")
            continue
        words = paragraph.split()
        line = words[0]
        for word in words[1:]:
            candidate = f"{line} {word}"
            if draw.textlength(candidate, font=fnt, direction=direction) <= max_width:
                line = candidate
            else:
                wrapped.append(line)
                line = word
        wrapped.append(line)
    return "\n".join(wrapped)


def fit_multiline(
    draw: ImageDraw.ImageDraw,
    text: str,
    font_path: str,
    start_size: int,
    min_size: int,
    max_width: int,
    max_height: int,
    direction: str,
    spacing: int,
) -> tuple[ImageFont.FreeTypeFont, str, tuple[int, int, int, int]]:
    for size in range(start_size, min_size - 1, -2):
        fnt = font(font_path, size)
        wrapped = wrap_text(draw, text, fnt, max_width, direction)
        box = draw.multiline_textbbox(
            (0, 0), wrapped, font=fnt, spacing=spacing, align="center", direction=direction
        )
        if box[2] - box[0] <= max_width and box[3] - box[1] <= max_height:
            return fnt, wrapped, box
    fnt = font(font_path, min_size)
    wrapped = wrap_text(draw, text, fnt, max_width, direction)
    return fnt, wrapped, draw.multiline_textbbox(
        (0, 0), wrapped, font=fnt, spacing=spacing, align="center", direction=direction
    )


def add_footer_gradient(image: Image.Image, dark: bool) -> Image.Image:
    layer = Image.new("RGBA", image.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    base = (4, 14, 44) if dark else (237, 246, 255)
    start = 1420
    for y in range(start, HEIGHT):
        progress = (y - start) / (HEIGHT - start)
        alpha = int(235 * progress**1.45)
        draw.line((0, y, WIDTH, y), fill=(*base, alpha), width=1)
    return Image.alpha_composite(image.convert("RGBA"), layer)


def draw_globe(draw: ImageDraw.ImageDraw, center: tuple[int, int], color: tuple[int, int, int, int]) -> None:
    x, y = center
    r = 22
    draw.ellipse((x - r, y - r, x + r, y + r), outline=color, width=4)
    draw.arc((x - 11, y - r, x + 11, y + r), 90, 270, fill=color, width=3)
    draw.arc((x - 11, y - r, x + 11, y + r), 270, 90, fill=color, width=3)
    draw.line((x - r + 2, y, x + r - 2, y), fill=color, width=3)


def render_card(concept_index: int, language: str) -> None:
    data = CONCEPTS[concept_index - 1]
    bg_path = BACKGROUNDS / f"background-{concept_index:02d}.png"
    with Image.open(bg_path) as source:
        image = ImageOps.fit(source.convert("RGB"), (WIDTH, HEIGHT), method=Image.Resampling.LANCZOS)
    image = add_footer_gradient(image, dark=not data["light"])

    draw = ImageDraw.Draw(image, "RGBA")
    is_fa = language == "fa"
    direction = "rtl" if is_fa else "ltr"
    bold_path = FONT_FA_BOLD if is_fa else FONT_EN_BOLD
    regular_path = FONT_FA_REGULAR if is_fa else FONT_EN_REGULAR
    headline = data[f"{language}_head"]
    sub = data[f"{language}_sub"]
    cta = data[f"{language}_cta"]
    card_number = concept_index if is_fa else concept_index + 15

    if data["light"]:
        panel = (255, 255, 255, 218)
        border = (255, 255, 255, 238)
        headline_color = (8, 31, 91, 255)
        sub_color = (20, 50, 103, 255)
        text_stroke = (255, 255, 255, 110)
    else:
        panel = (5, 20, 63, 214)
        border = (69, 154, 255, 150)
        headline_color = (255, 255, 255, 255)
        sub_color = (218, 239, 255, 255)
        text_stroke = (2, 11, 42, 160)

    # Frosted headline panel.
    panel_box = (54, 58, 1026, 520)
    draw.rounded_rectangle(panel_box, radius=42, fill=panel, outline=border, width=2)

    # Number badge.
    draw.ellipse((72, 82, 158, 168), fill=(7, 77, 181, 255), outline=(86, 197, 255, 255), width=3)
    number_font = font(FONT_EN_BOLD, 38 if card_number < 10 else 32)
    draw.text((115, 125), str(card_number), font=number_font, fill="white", anchor="mm")

    # Headline, fitted independently for long Persian and English lines.
    headline_font, headline_wrapped, headline_box = fit_multiline(
        draw,
        headline,
        bold_path,
        start_size=78,
        min_size=52,
        max_width=790,
        max_height=235,
        direction=direction,
        spacing=10,
    )
    headline_y = 88
    draw.multiline_text(
        (590, headline_y),
        headline_wrapped,
        font=headline_font,
        fill=headline_color,
        anchor="ma",
        align="center",
        direction=direction,
        spacing=10,
        stroke_width=1,
        stroke_fill=text_stroke,
    )
    headline_height = headline_box[3] - headline_box[1]

    if not data.get("testimonial"):
        sub_y = min(420, headline_y + headline_height + 28)
        sub_font, sub_wrapped, _ = fit_multiline(
            draw,
            sub,
            regular_path,
            start_size=38,
            min_size=28,
            max_width=850,
            max_height=185,
            direction=direction,
            spacing=8,
        )
        draw.multiline_text(
            (540, sub_y),
            sub_wrapped,
            font=sub_font,
            fill=sub_color,
            anchor="ma",
            align="center",
            direction=direction,
            spacing=8,
        )
    else:
        # The generated testimonial card intentionally contains a clean blank box.
        quote_font, quote_wrapped, _ = fit_multiline(
            draw,
            sub,
            regular_path,
            start_size=42,
            min_size=31,
            max_width=800,
            max_height=310,
            direction=direction,
            spacing=10,
        )
        draw.multiline_text(
            (540, 1025),
            quote_wrapped,
            font=quote_font,
            fill=(25, 37, 91, 255),
            anchor="mm",
            align="center",
            direction=direction,
            spacing=10,
        )

    # CTA shadow and blue gradient button.
    shadow = Image.new("RGBA", image.size, (0, 0, 0, 0))
    shadow_draw = ImageDraw.Draw(shadow)
    shadow_draw.rounded_rectangle((114, 1593, 966, 1731), radius=69, fill=(0, 16, 70, 150))
    shadow = shadow.filter(ImageFilter.GaussianBlur(20))
    image = Image.alpha_composite(image, shadow)
    button = Image.new("RGBA", image.size, (0, 0, 0, 0))
    button_draw = ImageDraw.Draw(button)
    for y in range(1580, 1710):
        t = (y - 1580) / 130
        color = (
            int(9 + (0 - 9) * t),
            int(174 + (83 - 174) * t),
            int(255 + (230 - 255) * t),
            255,
        )
        button_draw.line((120, y, 960, y), fill=color, width=1)
    # Mask gradient into a pill.
    mask = Image.new("L", image.size, 0)
    ImageDraw.Draw(mask).rounded_rectangle((120, 1580, 960, 1710), radius=65, fill=255)
    button.putalpha(mask)
    image = Image.alpha_composite(image, button)
    draw = ImageDraw.Draw(image, "RGBA")
    draw.rounded_rectangle((120, 1580, 960, 1710), radius=65, outline=(111, 224, 255, 230), width=3)

    cta_font, cta_wrapped, _ = fit_multiline(
        draw,
        cta,
        bold_path,
        start_size=53,
        min_size=36,
        max_width=730,
        max_height=90,
        direction=direction,
        spacing=4,
    )
    draw.multiline_text(
        (540, 1645),
        cta_wrapped,
        font=cta_font,
        fill="white",
        anchor="mm",
        align="center",
        direction=direction,
        spacing=4,
        stroke_width=1,
        stroke_fill=(0, 63, 177, 190),
    )

    # Domain pill with a deterministic globe icon and exact domain text.
    draw.rounded_rectangle((180, 1750, 900, 1860), radius=55, fill=(255, 255, 255, 246), outline=(192, 226, 255, 245), width=3)
    draw_globe(draw, (286, 1805), (0, 128, 224, 255))
    domain_font = font(FONT_EN_BOLD, 48)
    draw.text((565, 1805), "ibuilder.cam", font=domain_font, fill=(5, 31, 84, 255), anchor="mm")

    output_number = concept_index if is_fa else concept_index + 15
    language_label = "fa" if is_fa else "en"
    filename = f"ibuilder-story-{output_number:02d}-{language_label}"
    LOSSLESS.mkdir(parents=True, exist_ok=True)
    FINAL.mkdir(parents=True, exist_ok=True)
    image.convert("RGB").save(LOSSLESS / f"{filename}.png", "PNG", optimize=True)
    image.convert("RGB").save(
        FINAL / f"{filename}.jpg",
        "JPEG",
        quality=100,
        subsampling=0,
        optimize=True,
        dpi=(300, 300),
    )


def main() -> None:
    for index in range(1, 16):
        render_card(index, "fa")
        render_card(index, "en")


if __name__ == "__main__":
    main()

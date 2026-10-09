# AI Render — Plan (Rafiei Reel Style)

> نسخه ۱.۰ — ۲۰۲۶-۰۹-۲۹
> استک: **Kdenlive + MLT + FFmpeg + Whisper** (به‌جای Premiere + UXP)

> **به‌روزرسانی مرحلهٔ ۳ — ۲۰۲۶-۱۰-۰۴:** متن زیر سند تاریخی معماری اولیه است.
> رندر همچنان با MLT انجام می‌شود، اما مقصد پروژهٔ قابل‌ویرایش اکنون Premiere
> Pro است. خروجی جدید `project_premiere.zip` شامل FCP 7 XML، کپشن SRT و گزارش
> دقیق نگاشت transition است. قرارداد فعلی در
> [`docs/premiere-format.md`](docs/premiere-format.md) تعریف شده است؛ Kdenlive
> دیگر مسیر اصلی رابط کاربری یا معیار پذیرش مرحلهٔ ۳ نیست.

## ۱. هدف

یک ادیتور هوش مصنوعی که ویدیوی خام را می‌گیرد و با دستور «این ویدیو رو با Rafiei Reel Style ادیت کن» یک ریل عمودی آماده‌ی انتشار (MP4، 1080x1920) تحویل می‌دهد.

دامنه‌ی MVP فقط این ۷ کار است:
**Cut → حذف مکث → Zoom/Punch-in → Subtitle → Music → SFX → B-roll**
موشن پیچیده و After Effects فعلاً خارج از دامنه است.

## ۲. چرا این استک

| نیاز | ابزار | چرا |
|---|---|---|
| موتور تایم‌لاین و رندر | **MLT** (`melt`) | فرمت پروژه XML است، پس هر برنامه‌ای (پایتون) می‌تواند تایم‌لاین بسازد. بدون GUI و روی سرور هم رندر می‌گیرد. |
| ادیت دستی و اصلاح نهایی | **Kdenlive** | خودش روی MLT ساخته شده؛ یعنی همان پروژه‌ای که AI می‌سازد را می‌شود در Kdenlive باز کرد و دستی اصلاح کرد. رایگان و متن‌باز، روی مک/ویندوز/لینوکس. |
| تحلیل صدا، تشخیص مکث، لودنس، فریم‌گیری | **FFmpeg** | `silencedetect`، `loudnorm`، استخراج فریم برای QC. |
| متن و زمان دقیق هر کلمه | **Whisper** (`faster-whisper`) | ترنسکریپت با `word_timestamps` برای کات، کپشن و تشخیص جاهای مهم. فارسی و انگلیسی را پشتیبانی می‌کند. |
| مغز ادیت | **LLM** (GPT یا Claude) | ترنسکریپت + پروفایل استایل → JSON Edit Plan. در مرحله‌ی QC هم با دیدن فریم‌ها ایراد پیدا می‌کند. |

مزیت اصلی نسبت به Premiere/UXP: نیازی به باز بودن یک برنامه‌ی دسکتاپ و پلاگین نیست. کل مسیر «JSON → پروژه → MP4» یک اسکریپت است که می‌شود خودکار و پشت‌سرهم (برای حلقه‌ی QC) اجرایش کرد.

## ۳. نتیجه‌ی بررسی: آیا این استک برای هدف ما کار می‌کند؟

بله. یک نمونه‌ی واقعی در کانتینر ساخته و رندر شد (پوشه‌ی [`proof/`](proof/README.md)):
یک فایل `plan.json` با اسکریپت پایتون به MLT XML تبدیل شد و `melt` از آن MP4 گرفت. ۱۲.۷ ثانیه ویدیوی خام به ریل ۷.۳ ثانیه‌ای تبدیل شد.

| هدف | در MLT/FFmpeg با چه چیزی | وضعیت |
|---|---|---|
| Cut و حذف مکث | `ffmpeg silencedetect` + ورودی‌های `playlist` با `in/out` | ✅ تست شد |
| Zoom / Punch-in | فیلتر `affine` با keyframe روی `transition.rect` | ✅ تست شد |
| Subtitle | فایل ASS + فیلتر `avfilter.subtitles` (libass)، همان روشی که Kdenlive برای زیرنویس استفاده می‌کند | ✅ تست شد |
| B-roll | ترک ویدیوی دوم + ترنزیشن `affine` | ✅ تست شد |
| Music + ducking | ترک صدا + فیلتر `volume` با keyframe روی `level` (dB) | ✅ تست شد |
| SFX (whoosh و ...) | ترک صدای جدا + ترنزیشن `mix` | ✅ تست شد |
| خروجی MP4 | consumer `avformat` (H.264 + AAC) | ✅ تست شد |
| ترنسکریپت کلمه‌به‌کلمه | `faster-whisper` با `word_timestamps=True` | ⚠️ نصب شد ولی مدل در کانتینر دانلود نشد (محدودیت شبکه). روی سیستم خودت در مرحله ۱ تست می‌شود. |
| باز کردن پروژه در Kdenlive | خروجی MLT XML | ⚠️ در کانتینر GUI نبود. در مرحله ۱ روی سیستم خودت تست می‌شود. |
| حلقه‌ی QC و رندر دوباره | رندر → فریم‌گیری FFmpeg → بررسی LLM → اصلاح JSON → رندر دوباره | طراحی شد (مرحله ۴). همه‌ی اجزا اسکریپتی‌اند، پس مانعی ندارد. |
| یادگیری استایل از ریل‌های قبلی | تحلیل ریل‌ها با FFmpeg (scene detect، لودنس) + Whisper + LLM → پروفایل استایل | طراحی شد (مرحله ۵). |

نکته‌ی فنی که در تست پیدا شد: در MLT XML باید `<producer>`ها بیرون از `<playlist>` تعریف شوند، وگرنه جزو پلی‌لیست حساب می‌شوند.

منابع: [MLT XML](https://www.mltframework.org/docs/mltxml/)، [فیلترها و ترنزیشن‌های MLT](https://www.mltframework.org/plugins/PluginsFilters/)، [Kdenlive](https://docs.kdenlive.org/)، [faster-whisper](https://github.com/SYSTRAN/faster-whisper)، [FFmpeg filters](https://ffmpeg.org/ffmpeg-filters.html).

## ۴. معماری

```
 [UI وب محلی]  ←→  [Backend: FastAPI]
                        │
     ┌──────────────────┼────────────────────────────┐
     ▼                  ▼                            ▼
 brain/              engine/                       qc/
 Whisper +           plan.json → MLT XML           فریم‌گیری + LLM
 silencedetect +     (.mlt و .kdenlive)            → لیست ایراد
 LLM → plan.json     → melt → MP4                  → patch روی plan.json
     ▲                  │
     └──── styles/rafiei_reel.yaml  +  assets/ (music, sfx, broll با تگ)
```

قرارداد مرکزی کل سیستم **Edit Plan JSON** است. همه‌ی بخش‌ها فقط از طریق همین فایل با هم حرف می‌زنند. مغز AI آن را می‌سازد، UI آن را نمایش می‌دهد و ویرایش می‌کند، موتور آن را رندر می‌کند، QC آن را اصلاح می‌کند.

### نمونه‌ی Edit Plan (نسخه 0.1)

زمان‌های `segments` بر اساس ویدیوی خام است؛ بقیه‌ی زمان‌ها بر اساس تایم‌لاین خروجی.

```json
{
  "version": "0.1",
  "style": "rafiei_reel",
  "canvas": {"width": 1080, "height": 1920, "fps": 30},
  "source": "raw/video01.mp4",
  "segments": [
    {"id": "s1", "in": 1.05, "out": 3.65, "zoom": {"from": 1.0, "to": 1.0}},
    {"id": "s2", "in": 5.60, "out": 9.10, "zoom": {"from": 1.15, "to": 1.15}}
  ],
  "captions": [
    {"start": 0.0, "end": 2.6, "text": "Most people edit reels the HARD way", "style": "emphasis"}
  ],
  "broll": [{"at": 3.8, "duration": 1.8, "file": "broll/ai_dashboard.mp4", "in": 0.5}],
  "music": {"file": "music/upbeat01.mp3", "volume_db": -14,
            "duck": [{"start": 0.0, "end": 7.3, "volume_db": -24}]},
  "sfx": [{"at": 2.45, "file": "sfx/whoosh.wav", "volume_db": -3}],
  "export": {"file": "exports/video01_v1.mp4", "crf": 20}
}
```

### ساختار پوشه‌ی پروژه

```
rafiei-ai-editor/
  app/            backend (FastAPI) + job queue
  web/            UI
  engine/         schema.py, build_mlt.py, render.py, kdenlive_export.py
  brain/          transcribe.py, silence.py, planner.py (LLM)
  qc/             sample_frames.py, review.py, patch.py
  styles/         rafiei_reel.yaml
  assets/         music/ sfx/ broll/  + index.json (تگ‌ها)
  references/     ۱۰ تا ۲۰ ریل قبلی که دوست داری (مرجع استایل)
  jobs/<job_id>/  raw/, transcript.json, plan.json, project.mlt, captions.ass, exports/, qc/
```

## ۵. UI پروژه

یک وب‌اپ محلی ساده (در مرورگر، روی `localhost`) که روی همان سیستم تدوین اجرا می‌شود. هدفش این است که بدون ترمینال کار کنی.

### صفحه‌ها

1. **New Reel**
   - کشیدن و رها کردن ویدیوی خام (یا انتخاب از پوشه‌ی `raw/`)
   - انتخاب استایل: `Rafiei Reel Style` (بعدها استایل‌های دیگر)
   - یک خط دستور آزاد، مثلاً «CTA آخر ویدیو بیشتر باشد»
   - دکمه‌ی **Generate Edit Plan**
2. **Plan Review** (قلب UI)
   - پیش‌نمایش ویدیو (ویدیوی خام یا پیش‌نمایش سریع کم‌کیفیت)
   - تایم‌لاین ساده با لاین‌های رنگی: Segments (نگه‌داشته/حذف‌شده)، Zoom، Captions، B-roll، Music، SFX
   - ترنسکریپت کلمه‌به‌کلمه؛ کلیک روی کلمه → پرش به همان زمان؛ علامت‌گذاری بخش حذفی
   - ویرایش هر آیتم: متن کپشن، درصد زوم، جابه‌جایی B-roll، حجم موزیک
   - تب JSON برای ویرایش مستقیم (با اعتبارسنجی schema)
   - دکمه‌ها: **Render**، **Open in Kdenlive**، **Download plan.json**
3. **Render & QC**
   - نوار پیشرفت رندر
   - پخش‌کننده‌ی خروجی MP4
   - گزارش QC (از مرحله ۴): لیست ایرادها با زمان، مثل «کپشن روی صورت افتاده @0:07» با دکمه‌ی **Apply fix** برای هر کدام یا **Fix all & re-render**
   - مقایسه‌ی نسخه‌ها (v1، v2، ...)
4. **Library**
   - مدیریت music / sfx / broll و تگ‌هایشان
   - آپلود ریل‌های مرجع برای یادگیری استایل (مرحله ۵)
5. **Style**
   - نمایش و ویرایش `rafiei_reel.yaml`: فونت و رنگ کپشن، درصد زوم، فاصله‌ی کات‌ها، حجم موزیک، هدف لودنس

### تکنولوژی UI

- Backend: **Python + FastAPI** (همه‌ی ابزارها پایتونی‌اند)
- Frontend: **React + Vite** (یا در مرحله ۱ یک HTML ساده با JS)
- پیش‌نمایش: تگ `<video>` معمولی روی فایل رندرشده؛ برای پیش‌نمایش سریع، رندر با رزولوشن پایین (`melt` با پروفایل 540x960)
- ارتباط وضعیت رندر: polling ساده یا WebSocket

## ۶. تصمیم‌ها و پیش‌فرض‌ها

- **خروجی پیش‌فرض:** 1080x1920، 30fps، H.264 + AAC، لودنس نهایی حدود **-14 LUFS**.
- **رندر همیشه با `melt`** انجام می‌شود، نه Kdenlive GUI. Kdenlive فقط برای دیدن و اصلاح دستی است.
- **کپشن‌ها** به‌صورت فایل ASS ساخته می‌شوند (فونت، رنگ، هایلایت کلمه، موقعیت). برای کپشن فارسی باید فونت فارسی (مثل Vazirmatn) نصب باشد.
- **LLM** قابل تعویض است (GPT یا Claude)؛ فقط باید JSON معتبر مطابق schema برگرداند.
- **سیستم اجرا:** مک یا لینوکس. روی مک: `brew install ffmpeg mlt` و نصب Kdenlive از سایتش؛ `pip install faster-whisper`.

## ۷. ریسک‌ها

| ریسک | راه‌حل |
|---|---|
| فایل `.mlt` ساده ممکن است در Kdenlive کامل باز نشود (Kdenlive متادیتای خودش را دارد) | مرحله ۱: تست باز کردن. اگر لازم شد، یک پروژه‌ی خالی Kdenlive را به‌عنوان قالب می‌گیریم و خروجی `.kdenlive` می‌سازیم. |
| دقت Whisper برای فارسی/ترکیبی | مدل `medium` یا `large-v3`؛ امکان اصلاح دستی ترنسکریپت در UI. |
| سرعت رندر روی CPU | پیش‌نمایش با رزولوشن پایین؛ رندر نهایی فقط یک بار. |
| کپشن روی صورت | در مرحله ۴ تشخیص صورت (MediaPipe) و جابه‌جایی خودکار کپشن. |
| B-roll بی‌ربط | کتابخانه‌ی تگ‌دار + تأیید در UI؛ در مرحله ۴ بررسی ارتباط توسط LLM. |

جزئیات هر مرحله در [stages.md](stages.md) و مهارت‌های هر ماژول در [skills.md](skills.md) است.

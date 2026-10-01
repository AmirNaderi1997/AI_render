# V2 Real-Run Proof

Date: 2026-10-01. Pipeline: smarter brain V2 (commit after 3bcada6).

## b5c8530cb28f (Persian reel)
- Words: 107 | Pre-flagged: 15 | Decode disagree: 0
- Corrections proposed: 0 (0 auto, 0 suggestions)
- Segments: 10 | Captions: 21
- Distinct effect types: 9 | Distinct families: 7
- Families used: slow_push_bright, breathe, slow_push, punch, slow_pull, close_hold, flash
- Non-neutral lights used: lift_soft, pulse_start, dim_soft, fade_in, breath
- LLM cost: $0.0728 (16686 in / 1515 out tokens)
- Elapsed: 169.6s

### Auto-applied corrections (10 shown)
| idx | old | new | conf | reason |
|-----|-----|-----|------|--------|

### Suggestions
| idx | old | new | conf |
|-----|-----|-----|------|

### Effect timeline
| seg | type | family | intensity | reason |
|-----|------|--------|-----------|--------|
| s1 | punch__neutral | punch | 4 | زوم سریع روی «انتخاب کنید» پرسش آغازین را برجسته می‌کند. |
| s2 | slow_pull__dim_soft | slow_pull | 2 | عقب‌رفتن آرام، تقابل محصول و خدمات را با مکثی کنجکاوانه همرا |
| s3 | hold_close__neutral | close_hold | 2 | قاب نزدیک و ثابت، پرسش «کدومش» را مستقیم‌تر می‌کند. |
| s4 | punch__lift_soft | punch | 4 | زوم سریع روی «از صفر» ادعای اصلی را محکم بیان می‌کند. |
| s5 | slow_pull__neutral | slow_pull | 4 | [critic] A slow pull separates two consecutive punch effects |
| s6 | slow_push__breath | slow_push_bright | 3 | حرکت آرام رو به جلو با روشن‌ترشدن تصویر، مثال شخصی را امیدوا |
| s7 | steady__pulse_start | flash | 4 | فلاش کوتاه در آغاز، توجه را به دلیل فروش خدمات برمی‌گرداند. |
| s8 | slow_push__lift_soft | slow_push | 2 | حرکت آرام رو به جلو، توضیحِ نخواستن سرمایه اولیه را پیش می‌ب |
| s9 | hold_close__neutral | close_hold | 2 | قاب نزدیک، امکان فروختن مهارت را ملموس و تشویق‌کننده می‌کند. |
| s10 | steady__fade_in | breathe | 1 | تغییر ملایم نور، اطمینان‌بخشیِ «تبلیغات لازم نیست» را با مکث |

## raw/MYVIDEO.mp4 (Persian)
- Words: 89 | Pre-flagged: 15 | Decode disagree: 0
- Corrections proposed: 0 (0 auto, 0 suggestions)
- Segments: 9 | Captions: 14
- Distinct effect types: 7 | Distinct families: 6
- Families used: lift, punch_bright, breathe, slow_push, punch, close_hold
- Non-neutral lights used: lift_soft, fade_in, breath
- LLM cost: $0.0594 (13647 in / 1228 out tokens)
- Elapsed: 309.4s

### Auto-applied corrections (10 shown)
| idx | old | new | conf | reason |
|-----|-----|-----|------|--------|

### Suggestions
| idx | old | new | conf |
|-----|-----|-----|------|

### Effect timeline
| seg | type | family | intensity | reason |
|-----|------|--------|-----------|--------|
| s1 | punch__neutral | punch | 4 | زوم سریع روی «انتخاب» شروع کنجکاوی‌برانگیزی می‌سازد. |
| s2 | hold_close__lift_soft | close_hold | 2 | قاب نزدیک، پرسش درباره محصول و خدمات را مستقیم و شخصی می‌کند |
| s3 | steady__breath | breathe | 1 | تغییر ملایم نور برای فکر کردن به انتخاب فرصت می‌دهد. |
| s4 | punch__fade_in | punch_bright | 5 | زوم و روشن‌شدن هم‌زمان، ادعای اصلی درباره شروع با خدمات را ب |
| s5 | punch__neutral | punch | 4 | زوم سریع تضادِ پس از «ولی» را قاطعانه نشان می‌دهد. |
| s6 | slow_push__lift_soft | slow_push | 2 | حرکت آرام رو به جلو، توضیح فروش خدمات را پیوسته نگه می‌دارد. |
| s7 | hold_close__neutral | close_hold | 2 | قاب نزدیک، توصیه فروش مهارت را صمیمی و دلگرم‌کننده می‌کند. |
| s8 | slow_push__lift_soft | slow_push | 2 | حرکت آرام رو به جلو، مراحل عملی ایجاد پلتفرم را همراهی می‌کن |
| s9 | steady__lift_soft | lift | 2 | روشن‌شدن ملایم، نتیجه اطمینان‌بخشِ نداشتن هزینه اولیه را تقو |

## Before/After comparison (job b5c8530cb28f)

| metric | baseline (V1) | V2 result | target |
|--------|--------------|-----------|--------|
| Distinct effect types | 3 | 9 | ≥ 6 |
| Distinct families | 3 | 7 | ≥ 6 |
| Non-neutral lights | 0 | 5 | ≥ 3 |
| Corrections proposed | 8 (5 auto+3 sugg) | 0 | ≥ 8 |
| LLM cost | $0.060 | $0.0728 | ≤ $0.12 |

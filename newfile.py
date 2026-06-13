"""
بوت تيليجرام لتركيب فيديوهات قرآنية - النسخة المطورة
✅ كتابة الآيات على الصور
✅ دعم أكثر من صورة (سلايدشو)
✅ انتقال سلس بين الصور

المتطلبات:
pip install python-telegram-bot moviepy pillow arabic-reshaper python-bidi
sudo apt install ffmpeg fonts-hosny-amiri
"""

import os, logging, asyncio, textwrap, tempfile
from pathlib import Path

from telegram import Update
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    ConversationHandler, filters, ContextTypes
)

BOT_TOKEN    = "8390468250:AAHOLJ2zge4WKtnfk5CeUKzGWqtmHWCsjI0"
DOWNLOAD_DIR = Path("downloads")
OUTPUT_DIR   = Path("outputs")
DOWNLOAD_DIR.mkdir(exist_ok=True)
OUTPUT_DIR.mkdir(exist_ok=True)

ARABIC_FONT   = "Amiri-Regular.ttf"   # مسار الخط العربي
MAX_IMAGES    = 10
FADE_DURATION = 0.5

WAIT_AUDIO, WAIT_IMAGES, WAIT_TEXT = range(3)

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)


# ── إعداد النص العربي RTL ──────────────────────────────────
def prepare_arabic(text: str) -> str:
    try:
        import arabic_reshaper
        from bidi.algorithm import get_display
        return get_display(arabic_reshaper.reshape(text))
    except ImportError:
        return text


# ── رسم النص على الصورة ───────────────────────────────────
def add_text_to_image(img_path: str, text: str, out_path: str,
                      font_path: str = ARABIC_FONT,
                      font_size: int = 52) -> str:
    from PIL import Image, ImageDraw, ImageFont

    img = Image.open(img_path).convert("RGBA")
    W, H = img.size

    try:
        font = ImageFont.truetype(font_path, font_size)
    except (IOError, OSError):
        logger.warning("الخط العربي غير موجود، سيُستخدم الخط الافتراضي")
        font = ImageFont.load_default()

    display_text = prepare_arabic(text)
    max_chars = max(10, W // (font_size // 2))
    lines = []
    for para in display_text.splitlines():
        if para.strip():
            lines.extend(textwrap.wrap(para, width=max_chars) or [para])
        else:
            lines.append("")

    line_h      = font_size + 12
    block_h     = len(lines) * line_h + 50
    band_top    = H - block_h - 10

    overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
    draw_ov = ImageDraw.Draw(overlay)
    for y in range(band_top, H):
        alpha = int(190 * (y - band_top) / (H - band_top))
        draw_ov.line([(0, y), (W, y)], fill=(0, 0, 0, min(alpha, 210)))

    composite = Image.alpha_composite(img, overlay).convert("RGB")
    draw = ImageDraw.Draw(composite)

    y0 = band_top + 24
    for i, line in enumerate(lines):
        if not line:
            continue
        bbox = draw.textbbox((0, 0), line, font=font)
        tw = bbox[2] - bbox[0]
        x  = (W - tw) // 2
        y  = y0 + i * line_h
        draw.text((x + 2, y + 2), line, font=font, fill=(0, 0, 0, 160))
        draw.text((x, y),         line, font=font, fill=(255, 255, 240, 255))

    composite.save(out_path, "JPEG", quality=95)
    return out_path


# ── تركيب الفيديو ─────────────────────────────────────────
def create_video(audio_path: str, image_paths: list,
                 ayah_text: str, output_path: str) -> str:
    from moviepy.editor import AudioFileClip, ImageClip, concatenate_videoclips

    audio    = AudioFileClip(audio_path)
    duration = audio.duration
    n        = len(image_paths)
    per_img  = duration / n

    tmp_files = []
    processed = []

    for i, img_p in enumerate(image_paths):
        tf = tempfile.NamedTemporaryFile(
            suffix=".jpg", dir=str(DOWNLOAD_DIR), delete=False
        )
        tf.close()
        tmp_files.append(tf.name)
        add_text_to_image(img_p, ayah_text, tf.name)
        processed.append(tf.name)

    clips = []
    for img_p in processed:
        clip = (
            ImageClip(img_p)
            .set_duration(per_img)
            .resize(height=720)
            .crossfadein(FADE_DURATION)
        )
        clips.append(clip)

    if len(clips) == 1:
        video = clips[0].set_audio(audio)
    else:
        slideshow = concatenate_videoclips(
            clips, method="compose", padding=-FADE_DURATION
        )
        video = slideshow.set_audio(audio.set_duration(slideshow.duration))

    video.write_videofile(
        output_path,
        fps=24,
        codec="libx264",
        audio_codec="aac",
        temp_audiofile=str(DOWNLOAD_DIR / "tmp_audio.m4a"),
        remove_temp=True,
        logger=None
    )

    audio.close()
    video.close()
    for f in tmp_files:
        try: os.remove(f)
        except Exception: pass

    return output_path


# ── أوامر البوت ───────────────────────────────────────────
async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🕌 *أهلاً بك في بوت الفيديوهات القرآنية*\n\n"
        "أرسل /make لبدء إنشاء فيديو\n\n"
        "📌 *الخطوات:*\n"
        "1️⃣ أرسل صوت التلاوة\n"
        "2️⃣ أرسل صورة أو أكثر (حتى 10) ثم /done\n"
        "3️⃣ أرسل نص الآيات\n"
        "4️⃣ استلم الفيديو 🎬",
        parse_mode="Markdown"
    )

async def make_video_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data.clear()
    await update.message.reply_text(
        "🎙️ *الخطوة 1 من 3 — الصوت*\n\n"
        "أرسل ملف التلاوة القرآنية\n_(mp3 · ogg · m4a · wav)_",
        parse_mode="Markdown"
    )
    return WAIT_AUDIO

async def receive_audio(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user_id  = update.effective_user.id
    file_obj = (
        update.message.audio
        or update.message.voice
        or update.message.document
    )
    if not file_obj:
        await update.message.reply_text("❌ أرسل ملف صوتي من فضلك.")
        return WAIT_AUDIO

    msg     = await update.message.reply_text("⬇️ جارٍ تحميل الصوت...")
    tg_file = await file_obj.get_file()
    path    = str(DOWNLOAD_DIR / f"{user_id}_audio")
    await tg_file.download_to_drive(path)
    ctx.user_data["audio_path"] = path
    ctx.user_data["images"]     = []

    await msg.edit_text(
        "✅ تم استقبال الصوت!\n\n"
        "🖼️ *الخطوة 2 من 3 — الصور*\n\n"
        "أرسل صورة أو أكثر (حتى 10 صور)\n"
        "عند الانتهاء أرسل /done",
        parse_mode="Markdown"
    )
    return WAIT_IMAGES

async def receive_image(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    images  = ctx.user_data.setdefault("images", [])

    if len(images) >= MAX_IMAGES:
        await update.message.reply_text(
            f"⚠️ وصلت للحد الأقصى ({MAX_IMAGES} صور)، أرسل /done للمتابعة."
        )
        return WAIT_IMAGES

    file_obj = (
        update.message.photo[-1] if update.message.photo
        else update.message.document
    )
    if not file_obj:
        await update.message.reply_text("❌ أرسل صورة من فضلك.")
        return WAIT_IMAGES

    idx     = len(images) + 1
    path    = str(DOWNLOAD_DIR / f"{user_id}_img_{idx}.jpg")
    tg_file = await file_obj.get_file()
    await tg_file.download_to_drive(path)
    images.append(path)

    await update.message.reply_text(
        f"✅ صورة {idx} استُقبلت ✔️\n"
        f"أرسل المزيد أو /done للمتابعة"
    )
    return WAIT_IMAGES

async def images_done(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    images = ctx.user_data.get("images", [])
    if not images:
        await update.message.reply_text("❌ لم تُرسل أي صورة بعد.")
        return WAIT_IMAGES

    await update.message.reply_text(
        f"✅ تم استقبال {len(images)} صورة!\n\n"
        "📝 *الخطوة 3 من 3 — النص*\n\n"
        "أرسل نص الآيات القرآنية\n"
        "_(سيُكتب على الصور في الفيديو)_",
        parse_mode="Markdown"
    )
    return WAIT_TEXT

async def receive_text(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user_id    = update.effective_user.id
    ayah_text  = update.message.text.strip()
    if not ayah_text:
        await update.message.reply_text("❌ أرسل نص الآيات من فضلك.")
        return WAIT_TEXT

    audio_path  = ctx.user_data.get("audio_path")
    images      = ctx.user_data.get("images", [])
    output_path = str(OUTPUT_DIR / f"{user_id}_quran.mp4")

    msg = await update.message.reply_text(
        f"🎬 جارٍ تركيب الفيديو...\n"
        f"📸 {len(images)} صورة · 📝 النص مضاف\n⏳ لحظات..."
    )

    try:
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(
            None, create_video,
            audio_path, images, ayah_text, output_path
        )
        await msg.edit_text("✅ جاهز! جارٍ الإرسال... 📤")
        with open(output_path, "rb") as vf:
            await update.message.reply_video(
                video=vf,
                caption=(
                    "🕌 *الفيديو القرآني جاهز* ✨\n\n"
                    f"_{ayah_text[:80]}{'...' if len(ayah_text)>80 else ''}_\n\n"
                    "أرسل /make لفيديو جديد"
                ),
                parse_mode="Markdown",
                supports_streaming=True
            )
    except Exception as e:
        logger.error(f"خطأ: {e}", exc_info=True)
        await msg.edit_text(
            f"❌ حدث خطأ:\n`{e}`\n\nأرسل /make للمحاولة مجدداً.",
            parse_mode="Markdown"
        )
    finally:
        for f in ([audio_path, output_path] + images):
            try:
                if f and os.path.exists(f): os.remove(f)
            except Exception: pass
        ctx.user_data.clear()

    return ConversationHandler.END

async def cancel(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    for f in ctx.user_data.get("images", []):
        try: os.remove(f)
        except Exception: pass
    if ap := ctx.user_data.get("audio_path"):
        try: os.remove(ap)
        except Exception: pass
    ctx.user_data.clear()
    await update.message.reply_text("❌ تم الإلغاء. أرسل /make للبدء من جديد.")
    return ConversationHandler.END

async def help_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📖 *تعليمات الاستخدام:*\n\n"
        "/start  — بدء البوت\n"
        "/make   — إنشاء فيديو جديد\n"
        "/done   — انتهيت من إرسال الصور\n"
        "/cancel — إلغاء العملية الحالية\n\n"
        "💡 *نصائح:*\n"
        "• صور 16:9 (1920×1080) أفضل للفيديو\n"
        "• الصور توزّع بالتساوي على طول التلاوة\n"
        "• النص يظهر أسفل الصورة على خلفية شفافة\n"
        "• للخط العربي الجميل ثبّت:\n"
        "  `sudo apt install fonts-hosny-amiri`\n"
        "  وغيّر ARABIC_FONT في الكود",
        parse_mode="Markdown"
    )


# ── التشغيل ───────────────────────────────────────────────
def main():
    app = Application.builder().token(BOT_TOKEN).build()

    conv = ConversationHandler(
        entry_points=[CommandHandler("make", make_video_cmd)],
        states={
            WAIT_AUDIO: [
                MessageHandler(
                    filters.AUDIO | filters.VOICE | filters.Document.AUDIO,
                    receive_audio
                )
            ],
            WAIT_IMAGES: [
                MessageHandler(
                    filters.PHOTO | filters.Document.IMAGE,
                    receive_image
                ),
                CommandHandler("done", images_done),
            ],
            WAIT_TEXT: [
                MessageHandler(
                    filters.TEXT & ~filters.COMMAND,
                    receive_text
                )
            ],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
        allow_reentry=True,
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(conv)

    logger.info("🤖 البوت القرآني يعمل...")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()

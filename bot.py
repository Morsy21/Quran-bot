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

ARABIC_FONT = "Amiri-Regular.ttf"
MAX_IMAGES  = 10

WAIT_AUDIO, WAIT_IMAGES, WAIT_TEXT = range(3)

logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)


def prepare_arabic(text):
    try:
        import arabic_reshaper
        from bidi.algorithm import get_display
        return get_display(arabic_reshaper.reshape(text))
    except ImportError:
        return text


def add_text_to_image(img_path, text, out_path, font_size=52):
    from PIL import Image, ImageDraw, ImageFont

    img = Image.open(img_path).convert("RGBA")
    W, H = img.size

    try:
        font = ImageFont.truetype(ARABIC_FONT, font_size)
    except Exception:
        font = ImageFont.load_default()

    display_text = prepare_arabic(text)
    max_chars = max(10, W // (font_size // 2))
    lines = []
    for para in display_text.splitlines():
        if para.strip():
            lines.extend(textwrap.wrap(para, width=max_chars) or [para])
        else:
            lines.append("")

    line_h   = font_size + 12
    block_h  = len(lines) * line_h + 50
    band_top = H - block_h - 10

    overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
    drv = ImageDraw.Draw(overlay)
    for y in range(band_top, H):
        alpha = int(200 * (y - band_top) / (H - band_top))
        drv.line([(0, y), (W, y)], fill=(0, 0, 0, min(alpha, 210)))

    comp = Image.alpha_composite(img, overlay).convert("RGB")
    draw = ImageDraw.Draw(comp)

    y0 = band_top + 24
    for i, line in enumerate(lines):
        if not line:
            continue
        bbox = draw.textbbox((0, 0), line, font=font)
        tw = bbox[2] - bbox[0]
        x  = (W - tw) // 2
        y  = y0 + i * line_h
        draw.text((x+2, y+2), line, font=font, fill=(0, 0, 0, 160))
        draw.text((x,   y),   line, font=font, fill=(255, 255, 240, 255))

    comp.save(out_path, "JPEG", quality=95)
    return out_path


def get_islamic_image():
    """جيب صورة إسلامية من Pixabay"""
    import urllib.request, json, random
    PIXABAY_KEY = "56297265-fad28776753fed1f570d612cd"
    keywords = ["mosque", "islamic", "kaaba", "madinah", "quran", "mecca"]
    keyword  = random.choice(keywords)
    api_url  = f"https://pixabay.com/api/?key={PIXABAY_KEY}&q={keyword}&image_type=photo&per_page=20&safesearch=true"
    req = urllib.request.Request(api_url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req) as r:
        data = json.loads(r.read())
    hits = data.get("hits", [])
    if not hits:
        raise Exception("مفيش صور متاحة")
    img_url = random.choice(hits)["largeImageURL"]
    path = str(DOWNLOAD_DIR / f"auto_img_{random.randint(1000,9999)}.jpg")
    urllib.request.urlretrieve(img_url, path)
    return path


def create_video(audio_path, image_paths, ayah_text, output_path):
    import imageio_ffmpeg
    from moviepy.editor import AudioFileClip, ImageClip, concatenate_videoclips
    from moviepy.config import change_settings

    ffmpeg_path = imageio_ffmpeg.get_ffmpeg_exe()
    change_settings({"FFMPEG_BINARY": ffmpeg_path})

    audio    = AudioFileClip(audio_path)
    duration = audio.duration
    n        = len(image_paths)
    per_img  = duration / n

    tmp_imgs = []
    for img_p in image_paths:
        tf = tempfile.NamedTemporaryFile(suffix=".jpg", dir=str(DOWNLOAD_DIR), delete=False)
        tf.close()
        add_text_to_image(img_p, ayah_text, tf.name)
        tmp_imgs.append(tf.name)

    clips = [ImageClip(p).set_duration(per_img) for p in tmp_imgs]

    if len(clips) == 1:
        video = clips[0].set_audio(audio)
    else:
        slideshow = concatenate_videoclips(clips, method="compose")
        video = slideshow.set_audio(audio.set_duration(slideshow.duration))

    video.write_videofile(
        output_path, fps=24, codec="libx264", audio_codec="aac",
        temp_audiofile=str(DOWNLOAD_DIR / "tmp_audio.m4a"),
        remove_temp=True, logger=None
    )
    audio.close()
    video.close()

    for f in tmp_imgs:
        try: os.remove(f)
        except Exception: pass

    return output_path


# ── أوامر البوت ───────────────────────────────────────────
async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🕌 *أهلاً بك في بوت الفيديوهات القرآنية*\n\n"
        "اضغط /make لبدء إنشاء فيديو\n\n"
        "📌 *الخطوات:*\n"
        "1️⃣ أرسل صوت التلاوة\n"
        "2️⃣ أرسل صورة أو أكثر (حتى 10) ثم /done\n"
        "    _(أو اضغط /auto للصور التلقائية)_\n"
        "3️⃣ أرسل نص الآيات\n"
        "4️⃣ استلم الفيديو 🎬",
        parse_mode="Markdown"
    )

async def make_video_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data.clear()
    await update.message.reply_text(
        "🎙️ *الخطوة 1 من 3 — الصوت*\n\nأرسل ملف التلاوة القرآنية\n_(mp3 · ogg · m4a · wav)_",
        parse_mode="Markdown"
    )
    return WAIT_AUDIO

async def receive_audio(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user_id  = update.effective_user.id
    file_obj = update.message.audio or update.message.voice or update.message.document
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
        "أرسل صورة أو أكثر (حتى 10) ثم /done\n"
        "أو اضغط /auto وأنا هجيب صور إسلامية تلقائياً 🕌",
        parse_mode="Markdown"
    )
    return WAIT_IMAGES

async def receive_image(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    images  = ctx.user_data.setdefault("images", [])

    if len(images) >= MAX_IMAGES:
        await update.message.reply_text(f"⚠️ وصلت للحد الأقصى ({MAX_IMAGES})، أرسل /done")
        return WAIT_IMAGES

    file_obj = update.message.photo[-1] if update.message.photo else update.message.document
    if not file_obj:
        await update.message.reply_text("❌ أرسل صورة من فضلك.")
        return WAIT_IMAGES

    idx     = len(images) + 1
    path    = str(DOWNLOAD_DIR / f"{user_id}_img_{idx}.jpg")
    tg_file = await file_obj.get_file()
    await tg_file.download_to_drive(path)
    images.append(path)

    await update.message.reply_text(f"✅ صورة {idx} استُقبلت ✔️\nأرسل المزيد أو /done")
    return WAIT_IMAGES

async def auto_images(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """جيب صور إسلامية تلقائياً من Unsplash"""
    msg = await update.message.reply_text("🔍 جارٍ جلب صور إسلامية تلقائياً...")
    try:
        loop = asyncio.get_event_loop()
        path = await loop.run_in_executor(None, get_islamic_image)
        ctx.user_data.setdefault("images", []).append(path)
        await msg.edit_text(
            "✅ تم جلب صورة إسلامية تلقائياً!\n\n"
            "📝 *الخطوة 3 من 3 — النص*\n\nأرسل نص الآيات القرآنية",
            parse_mode="Markdown"
        )
        return WAIT_TEXT
    except Exception as e:
        await msg.edit_text(f"❌ فشل جلب الصورة، أرسل صورة يدوياً.\n`{e}`", parse_mode="Markdown")
        return WAIT_IMAGES

async def images_done(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    images = ctx.user_data.get("images", [])
    if not images:
        await update.message.reply_text("❌ لم تُرسل أي صورة. أرسل صورة أو /auto")
        return WAIT_IMAGES

    await update.message.reply_text(
        f"✅ تم استقبال {len(images)} صورة!\n\n"
        "📝 *الخطوة 3 من 3 — النص*\n\nأرسل نص الآيات القرآنية\n_(سيُكتب على الصور في الفيديو)_",
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
        f"🎬 جارٍ تركيب الفيديو...\n📸 {len(images)} صورة · 📝 النص مضاف\n⏳ لحظات..."
    )

    try:
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, create_video, audio_path, images, ayah_text, output_path)
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
        await msg.edit_text(f"❌ حدث خطأ:\n`{e}`\n\nأرسل /make للمحاولة مجدداً.", parse_mode="Markdown")
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
        "/auto   — جلب صورة إسلامية تلقائياً\n"
        "/done   — انتهيت من إرسال الصور\n"
        "/cancel — إلغاء العملية",
        parse_mode="Markdown"
    )

def main():
    app = Application.builder().token(BOT_TOKEN).build()
    conv = ConversationHandler(
        entry_points=[CommandHandler("make", make_video_cmd)],
        states={
            WAIT_AUDIO:  [MessageHandler(filters.AUDIO | filters.VOICE | filters.Document.AUDIO, receive_audio)],
            WAIT_IMAGES: [
                MessageHandler(filters.PHOTO | filters.Document.IMAGE, receive_image),
                CommandHandler("done", images_done),
                CommandHandler("auto", auto_images),
            ],
            WAIT_TEXT: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_text)],
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

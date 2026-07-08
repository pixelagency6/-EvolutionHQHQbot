import os
import io
import asyncio
import logging
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

from PIL import Image, ImageDraw, ImageFont
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, ContextTypes, filters

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
log = logging.getLogger("bot")

# ============================================================
# Health server
# ============================================================
class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200); self.send_header("Content-Type", "text/plain"); self.end_headers()
        self.wfile.write(b"Meme Bot alive.")
    def do_HEAD(self):
        self.send_response(200); self.send_header("Content-Type", "text/plain"); self.end_headers()
    def log_message(self, format, *args):
        return

def run_health_server():
    port = int(os.environ.get("PORT", 10000))
    HTTPServer(("0.0.0.0", port), HealthHandler).serve_forever()

# ============================================================
# Meme generation
# ============================================================
FONT_PATHS = [
    "impact.ttf",  # optional: drop an Impact/bold TTF in the repo for the classic look
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
]

def load_font(size):
    for p in FONT_PATHS:
        try:
            return ImageFont.truetype(p, size)
        except Exception:
            continue
    return ImageFont.load_default()

def wrap_lines(draw, text, font, max_w):
    words = text.split()
    lines, cur = [], ""
    for w in words:
        test = (cur + " " + w).strip()
        if draw.textlength(test, font=font) <= max_w or not cur:
            cur = test
        else:
            lines.append(cur); cur = w
    if cur:
        lines.append(cur)
    return lines

def draw_block(draw, text, font, W, H, pos):
    max_w = W * 0.92
    lines = wrap_lines(draw, text, font, max_w)
    try:
        ascent, descent = font.getmetrics()
        lh = ascent + descent + 6
    except Exception:
        lh = getattr(font, "size", 24) + 6
    total = lh * len(lines)
    y = 12 if pos == "top" else (H - total - 12)
    stroke = max(2, getattr(font, "size", 24) // 15)
    for line in lines:
        w = draw.textlength(line, font=font)
        x = (W - w) / 2
        draw.text((x, y), line, font=font, fill="white",
                  stroke_width=stroke, stroke_fill="black")
        y += lh

def make_meme(image_bytes, top, bottom):
    img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    if img.width > 1000:
        ratio = 1000 / img.width
        img = img.resize((1000, int(img.height * ratio)))
    W, H = img.size
    draw = ImageDraw.Draw(img)
    font = load_font(max(22, W // 10))
    if top:
        draw_block(draw, top.upper(), font, W, H, "top")
    if bottom:
        draw_block(draw, bottom.upper(), font, W, H, "bottom")
    out = io.BytesIO(); img.save(out, "JPEG", quality=90); return out.getvalue()

# ============================================================
# Handlers
# ============================================================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await update.message.reply_text(
        "😂 *Meme Generator*\n\n"
        "1️⃣ Send me a photo\n"
        "2️⃣ Send the text as `TOP | BOTTOM`\n\n"
        "_(use | to split top and bottom, or send one line for bottom text only)_\n\n"
        "Send a photo to start 👇",
        parse_mode="Markdown",
    )

async def gen_and_send(update, context, caption):
    file_id = context.user_data.get("meme_file_id")
    if not file_id:
        await update.message.reply_text("📷 Send me a photo first.")
        return
    if "|" in caption:
        top, bottom = caption.split("|", 1)
    else:
        top, bottom = "", caption
    top, bottom = top.strip(), bottom.strip()

    status = await update.message.reply_text("🎨 Making your meme…")
    try:
        f = await context.bot.get_file(file_id)
        buf = io.BytesIO()
        await f.download_to_memory(buf)
        img_bytes = buf.getvalue()
        out = await asyncio.get_event_loop().run_in_executor(None, make_meme, img_bytes, top, bottom)
        await status.delete()
        bio = io.BytesIO(out); bio.name = "meme.jpg"
        await update.message.reply_photo(photo=bio, caption="✅ Here's your meme! Send another photo for more.")
    except Exception as e:
        log.error(f"meme failed: {e}")
        try: await status.delete()
        except Exception: pass
        await update.message.reply_text("❌ Couldn't make the meme. Try a different image.")
    finally:
        context.user_data.pop("await_meme_text", None)
        context.user_data.pop("meme_file_id", None)

async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    photo = update.message.photo[-1]
    context.user_data["meme_file_id"] = photo.file_id
    caption = (update.message.caption or "").strip()
    if caption:
        await gen_and_send(update, context, caption)
        return
    context.user_data["await_meme_text"] = True
    await update.message.reply_text(
        "📝 Now send the meme text:\n\n`TOP | BOTTOM`\n\n"
        "_(or just one line for bottom text)_",
        parse_mode="Markdown",
    )

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.user_data.get("await_meme_text"):
        await update.message.reply_text("📷 Send me a photo first to make a meme.")
        return
    await gen_and_send(update, context, update.message.text or "")

# ============================================================
# Main
# ============================================================
def main():
    token = os.environ.get("BOT_TOKEN")
    if not token:
        log.critical("BOT_TOKEN env var missing!")
        return

    threading.Thread(target=run_health_server, daemon=True).start()

    app = Application.builder().token(token).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

    log.info("Meme Bot is running...")
    app.run_polling()

if __name__ == "__main__":
    main()

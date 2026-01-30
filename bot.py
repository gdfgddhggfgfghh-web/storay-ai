import os
import logging
import json
import requests
import urllib.parse
import random
import re
import io
from PIL import Image  # مكتبة معالجة الصور
from dotenv import load_dotenv
import google.generativeai as genai
from telegram import Update
from telegram.ext import ApplicationBuilder, ContextTypes, CommandHandler, MessageHandler, filters

# Load environment variables
load_dotenv()

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
GEMINI_API_KEYS = os.getenv("GEMINI_API_KEY", "").split(',')
DB_CHANNEL_ID = os.getenv("DB_CHANNEL_ID")

current_key_index = 0

def configure_genai():
    global current_key_index
    if not GEMINI_API_KEYS:
        logging.error("No GEMINI_API_KEYS found.")
        return None
    key = GEMINI_API_KEYS[current_key_index].strip()
    genai.configure(api_key=key)
    return key

def rotate_key():
    global current_key_index
    if len(GEMINI_API_KEYS) > 1:
        current_key_index = (current_key_index + 1) % len(GEMINI_API_KEYS)
        configure_genai()
        return True
    return False

# Configure Logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO,
    handlers=[logging.FileHandler("bot_log.txt", encoding='utf-8'), logging.StreamHandler()]
)

configure_genai()

def get_model():
    knowledge_path = os.path.join(os.path.dirname(__file__), 'knowledge_base.txt')
    try:
        with open(knowledge_path, 'r', encoding='utf-8') as f:
            knowledge = f.read()
    except FileNotFoundError:
        knowledge = "You are Dark AI."
    
    model = genai.GenerativeModel(
        model_name='gemini-2.5-flash',
        system_instruction=knowledge
    )
    return model

model = get_model()
chats = {}

# --- دالة توليد الصور (Pollinations) ---
async def generate_image_logic(prompt, chat_id, context, caption_text=""):
    enhanced_prompt = f"dark atmosphere, gloomy, hyperrealistic, 8k, cinematic lighting, {prompt}"
    pollinations_model = "flux" 
    
    encoded_prompt = urllib.parse.quote(enhanced_prompt)
    seed = random.randint(0, 999999)
    image_url = f"https://image.pollinations.ai/prompt/{encoded_prompt}?width=1024&height=1024&seed={seed}&model={pollinations_model}&nologo=true"

    try:
        await context.bot.send_photo(
            chat_id=chat_id,
            photo=image_url,
            caption=caption_text,
            parse_mode="Markdown"
        )
        return True
    except Exception as e:
        await context.bot.send_message(chat_id=chat_id, text=f"❌ حدث خطأ أثناء الرسم: {e}")
        return False

# --- Persistence Layer ---
async def save_history(context: ContextTypes.DEFAULT_TYPE):
    if not DB_CHANNEL_ID: return
    data = {}
    for user_id, chat_session in chats.items():
        history = []
        for msg in chat_session.history:
            # نتجاهل حفظ أجزاء الصور في ملف التاريخ لتجنب الأخطاء، نحفظ النصوص فقط
            parts_text = []
            for part in msg.parts:
                if part.text:
                    parts_text.append(part.text)
            if parts_text:
                history.append({"role": msg.role, "parts": parts_text})
        data[str(user_id)] = history
    try:
        try:
            chat = await context.bot.get_chat(chat_id=DB_CHANNEL_ID)
            if chat.pinned_message: await chat.pinned_message.delete()
        except: pass
        json_str = json.dumps(data, ensure_ascii=False, indent=2)
        document = json_str.encode('utf-8')
        message = await context.bot.send_document(
            chat_id=DB_CHANNEL_ID, document=document, filename=f"dark_backup.json", caption="Dark AI Memory"
        )
        await message.pin(disable_notification=True)
    except Exception as e:
        logging.error(f"Save error: {e}")

async def load_history(application):
    if not DB_CHANNEL_ID: return
    try:
        chat = await application.bot.get_chat(chat_id=DB_CHANNEL_ID)
        pinned = chat.pinned_message
        if not pinned or not pinned.document: return
        f = await pinned.document.get_file()
        byte_data = await f.download_as_bytearray()
        data = json.loads(byte_data.decode('utf-8'))
        for user_id, history_data in data.items():
            formatted = [{"role": m["role"], "parts": m["parts"]} for m in history_data]
            chats[int(user_id)] = model.start_chat(history=formatted)
        logging.info(f"Restored history.")
    except Exception as e:
        logging.error(f"Load error: {e}")

# --- Handlers ---

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text('أنا Dark AI.\nأسمعك، أراك، وأجسد أفكارك.')

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    global model
    user_id = update.effective_user.id
    
    # 1. التحقق: هل الرسالة نص أم صورة؟
    message_content = [] # القائمة التي سنرسلها لـ Gemini
    user_text = ""

    # إذا كانت صورة
    if update.message.photo:
        # تحميل الصورة بأعلى جودة
        photo_file = await update.message.photo[-1].get_file()
        image_bytes = await photo_file.download_as_bytearray()
        img = Image.open(io.BytesIO(image_bytes))
        
        message_content.append(img) # إضافة الصورة للمحتوى
        
        # لو فيه وصف مع الصورة (Caption)
        if update.message.caption:
            user_text = update.message.caption
            message_content.append(user_text)
        else:
            # لو مفيش وصف، نعتبره بيطلب تحليل الصورة
            user_text = "Analyze this image."
            message_content.append("ماذا ترى في هذه الصورة؟ حللها بأسلوبك المظلم.")

    # إذا كانت نص فقط
    elif update.message.text:
        user_text = update.message.text
        message_content.append(user_text)
    
    else:
        return # لو ملف صوتي أو فيديو (حالياً لا ندعمه)

    if not model: return
    if user_id not in chats: chats[user_id] = model.start_chat(history=[])
    chat_session = chats[user_id]
    
    # إرسال Action مناسب
    action = 'upload_photo' if update.message.photo else 'typing'
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action=action)
    
    max_retries = len(GEMINI_API_KEYS)
    attempts = 0
    while attempts < max_retries:
        try:
            # 2. إرسال المحتوى (نص + صورة) لـ Gemini
            response = chat_session.send_message(message_content)
            ai_reply = response.text
            
            # 3. الكشف عن الكود السري للرسم ///IMG: ... ///
            img_pattern = r"///IMG:(.*?)///"
            match = re.search(img_pattern, ai_reply, re.DOTALL)
            
            if match:
                prompt_to_draw = match.group(1).strip()
                clean_reply = re.sub(img_pattern, "", ai_reply).strip()
                
                if clean_reply:
                    await update.message.reply_text(clean_reply)
                
                wait_msg = await update.message.reply_text("👁️ جاري استدعاء الصورة من عقلي...")
                await generate_image_logic(prompt_to_draw, update.effective_chat.id, context)
                await context.bot.delete_message(chat_id=update.effective_chat.id, message_id=wait_msg.message_id)

            else:
                if len(ai_reply) > 4096:
                    for x in range(0, len(ai_reply), 4000):
                        await update.message.reply_text(ai_reply[x:x+4000])
                else:
                    await update.message.reply_text(ai_reply)

            # الحفظ والتدوير (Save History)
            # ملاحظة: Gemini يتذكر الصور في الجلسة الحالية، لكننا لا نحفظ بيانات الصورة في ملف JSON لتقليل الحجم
            await save_history(context)
            
            if len(GEMINI_API_KEYS) > 1: rotate_key(); model = get_model()
            return

        except Exception as e:
            if "429" in str(e) or "quota" in str(e).lower():
                attempts += 1
                if attempts < max_retries and rotate_key():
                    model = get_model(); chats[user_id] = model.start_chat(history=chat_session.history); chat_session = chats[user_id]; continue
                await update.message.reply_text("❌ Quota Exceeded.")
                return
            else: 
                logging.error(f"Error processing message: {e}")
                await update.message.reply_text(f"❌ Error: {str(e)[:100]}")
                return

if __name__ == '__main__':
    if not TELEGRAM_TOKEN: exit(1)
    async def post_init(app: ApplicationBuilder): await load_history(app)
    application = ApplicationBuilder().token(TELEGRAM_TOKEN).post_init(post_init).build()
    
    application.add_handler(CommandHandler("start", start))
    # تم تعديل الفلتر ليستقبل الصور والنصوص
    application.add_handler(MessageHandler((filters.TEXT | filters.PHOTO) & ~filters.COMMAND, handle_message))
    
    print("Dark AI (Vision & Creation) is online...")
    application.run_polling()
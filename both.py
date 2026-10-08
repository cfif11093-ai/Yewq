import os
import sys
import traceback
import json
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
import requests
import telebot
from telebot import types

# Берем ключи из настроек сервера Render
BOT_TOKEN = os.getenv("BOT_TOKEN")
AI_API_KEY = os.getenv("AI_API_KEY")

if not BOT_TOKEN or not AI_API_KEY:
    raise ValueError("Не найдены BOT_TOKEN или AI_API_KEY!")

bot = telebot.TeleBot(BOT_TOKEN)

# 1. Веб-сервер для прохождения проверки Render (Health Check)
class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-type", "text/plain; charset=utf-8")
        self.end_headers()
        self.wfile.write(b"Bot is alive!")

    def log_message(self, format, *args):
        return

def start_health_server():
    port = int(os.environ.get("PORT", 8080))
    server = HTTPServer(("0.0.0.0", port), HealthCheckHandler)
    server.serve_forever()

threading.Thread(target=start_health_server, daemon=True).start()

# 2. Запрос к бесплатному ИИ
def ask_free_ai(query: str):
    try:
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {AI_API_KEY}",
            "HTTP-Referer": "https://t.me/substitute_bot", 
            "X-Title": "Pharma Bot"
        }
        
        payload = {
            "model": "openrouter/free",
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "Ты профессиональный врач-фармацевт. Пользователь отправляет название лекарства, препарата или аптечного бренда. "
                        "ОБЯЗАТЕЛЬНО назови конкретные препараты-аналоги (дженерики и оригиналы) с дозировками и производителями. "
                        "Никаких общих фраз, воды и 'спросите в аптеке'. Только конкретные торговые названия. "
                        "Ответ верни СТРОГО в формате JSON без markdown (без ```json), содержащий поля: "
                        "name (точное название введенного препарата/средства и его МНН), "
                        "category (фармакологическая группа), "
                        "cheap (конкретные дешевые аналоги с названиями заводов/стран), "
                        "good (качественные оригиналы или премиум-аналоги с названиями), "
                        "tip (краткий медицинский совет по приему)."
                    )
                },
                {"role": "user", "content": query}
            ],
            "temperature": 0.1
        }

        response = requests.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers=headers,
            json=payload,
            timeout=25
        )
        
        if response.status_code == 200:
            res_json = response.json()
            content = res_json['choices'][0]['message']['content'].strip()
            
            if content.startswith("```"):
                content = content.split("```")[1]
                if content.startswith("json"):
                    content = content[4:]
            content = content.strip()

            return json.loads(content)
        return None
    except Exception as e:
        print(f"Ошибка: {e}")
        return None

# 3. Команды Telegram
@bot.message_handler(commands=['start'])
def send_welcome(message):
    markup = types.InlineKeyboardMarkup(row_width=2)
    btn1 = types.InlineKeyboardButton("💊 Найз", callback_data="search_найз")
    btn2 = types.InlineKeyboardButton("🧴 Фенистил", callback_data="search_фенистил")
    btn3 = types.InlineKeyboardButton("🛡 Омепразол", callback_data="search_омепразол")
    btn4 = types.InlineKeyboardButton("💧 Мирамистин", callback_data="search_мирамистин")
    markup.add(btn1, btn2, btn3, btn4)

    bot.send_message(
        message.chat.id,
        "🤖 <b>ИИ-фармацевт: Точный поиск аналогов</b>\n\n"
        "Напишите название любого лекарства в чат, и ИИ подберет точные дешевые и премиальные аналоги!\n\n"
        "Или выберите пример ниже 👇",
        parse_mode='HTML',
        reply_markup=markup
    )

@bot.callback_query_handler(func=lambda call: call.data.startswith('search_') or call.data == 'disclaimer')
def callback_inline(call):
    if call.data == 'disclaimer':
        bot.answer_callback_query(call.id, "⚠️ Имеются противопоказания. Проконсультируйтесь с врачом!", show_alert=True)
        return

    query = call.data.replace('search_', '')
    msg = bot.send_message(call.message.chat.id, f"🧠 <i>ИИ подбирает аналоги для «{query}»...</i>", parse_mode='HTML')
    item_data = ask_free_ai(query)
    bot.delete_message(call.message.chat.id, msg.message_id)

    if not item_data:
        bot.send_message(call.message.chat.id, "❌ Не удалось получить ответ. Попробуйте снова.", parse_mode='HTML')
        return

    response_text = (
        f"🎯 <b>{item_data.get('name', query)}</b>\n\n"
        f"🏷 <b>Группа:</b> {item_data.get('category', 'Медицинский препарат')}\n\n"
        f"💸 <b>Доступный аналог (дженерик):</b>\n{item_data.get('cheap', '—')}\n\n"
        f"⭐ <b>Качественный оригинал / премиум:</b>\n{item_data.get('good', '—')}\n\n"
        f"💡 <b>Совет фармацевта:</b>\n{item_data.get('tip', 'Сверяйте дозировку.')}"
    )

    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(
        types.InlineKeyboardButton("⚠️ Важная оговорка", callback_data="disclaimer"),
        types.InlineKeyboardButton("🔄 Новый поиск", callback_data="reset_search")
    )
    bot.send_message(call.message.chat.id, response_text, parse_mode='HTML', reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data == 'reset_search')
def reset_callback(call):
    bot.edit_message_text(
        chat_id=call.message.chat.id,
        message_id=call.message.message_id,
        text="🔄 <b>Введите название нужного лекарства</b> в чат:",
        parse_mode='HTML'
    )

@bot.message_handler(func=lambda m: True)
def handle_search(message):
    chat_id = message.chat.id
    query = message.text.strip()
    
    if len(query) < 2:
        bot.send_message(chat_id, "⚠️ Слишком короткое название. Введите лекарство полностью.", parse_mode='HTML')
        return
        
    msg = bot.send_message(chat_id, f"🧠 <i>ИИ ищет точные аналоги для «{query}»...</i>", parse_mode='HTML')
    item_data = ask_free_ai(query)
    bot.delete_message(chat_id, msg.message_id)
    
    if not item_data:
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("🔄 Попробовать снова", callback_data="reset_search"))
        bot.send_message(chat_id, "❌ Не удалось найти данные. Попробуйте еще раз.", parse_mode='HTML', reply_markup=markup)
        return

    response_text = (
        f"🎯 <b>{item_data.get('name', query)}</b>\n\n"
        f"🏷 <b>Группа:</b> {item_data.get('category', 'Медицинский препарат')}\n\n"
        f"💸 <b>Доступный аналог (дженерик):</b>\n{item_data.get('cheap', '—')}\n\n"
        f"⭐ <b>Качественный оригинал / премиум:</b>\n{item_data.get('good', '—')}\n\n"
        f"💡 <b>Совет фармацевта:</b>\n{item_data.get('tip', 'Сверяйте дозировку.')}"
    )

    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(
        types.InlineKeyboardButton("⚠️ Важная оговорка", callback_data="disclaimer"),
        types.InlineKeyboardButton("🔄 Новый поиск", callback_data="reset_search")
    )
    bot.send_message(chat_id, response_text, parse_mode='HTML', reply_markup=markup)

if __name__ == '__main__':
    print("✅ ИИ-бот запущен и слушает Telegram...")
    bot.infinity_polling()

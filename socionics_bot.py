import logging
import os



import asyncio
from datetime import datetime

# For systemd watchdog
try:
    from systemd.daemon import notify, Notification
except ImportError:
    def notify(state): pass
    class Notification:
        READY = "READY=1"
        WATCHDOG = "WATCHDOG=1"
        STOPPING = "STOPPING=1"
        STATUS = "STATUS="

import httpx
import telegram
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes, MessageHandler, filters
from telegram.request import HTTPXRequest

from socionics_data import DICHOTOMIES, TYPES, calculate_type
from relations_data import get_relation, TIMS_ORDER

# Enable logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

# State constants
CURRENT_DICHOTOMY = 'current_dichotomy'
CURRENT_PAIR_INDEX = 'current_pair_index'
SCORES = 'scores'
USER_TYPE = 'user_type'

REPLY_KEYBOARD = ReplyKeyboardMarkup(
    [[KeyboardButton("🏠 Главное меню")],
     [KeyboardButton("📝 Тест"), KeyboardButton("🤝 Совместимость")]],
    resize_keyboard=True
)


# ─── Heartbeat ───────────────────────────────────────────────────────────────




# ─── Helpers ────────────────────────────────────────────────────────────────-

def init_user_data(context):
    if SCORES not in context.user_data:
        context.user_data[SCORES] = {'E': 0, 'I': 0, 'S': 0, 'N': 0, 'T': 0, 'F': 0, 'J': 0, 'P': 0}
    if CURRENT_DICHOTOMY not in context.user_data:
        context.user_data[CURRENT_DICHOTOMY] = 0
    if CURRENT_PAIR_INDEX not in context.user_data:
        context.user_data[CURRENT_PAIR_INDEX] = 0


def _log_result(message, sociotype_info):
    user = message.chat
    log_entry = (
        f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} | "
        f"ID: {user.id} | "
        f"User: @{getattr(user, 'username', 'no_username') or 'no_username'} "
        f"({getattr(user, 'first_name', '')}) | "
        f"Result: {sociotype_info['name']}\n"
    )
    try:
        with open("results.txt", "a", encoding="utf-8") as f:
            f.write(log_entry)
    except Exception as e:
        logger.error(f"Failed to write result log: {e}")


# ─── Main menu ───────────────────────────────────────────────────────────────

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    await context.bot.set_my_commands([
        ("start", "Главное меню"),
        ("test", "Начать/Продолжить тест"),
        ("compat", "Проверить совместимость")
    ])

    text = (
        f"Привет, {user.first_name}! 👋\n\n"
        "Знаешь, почему с одними людьми ты на одной волне, "
        "а с другими — будто говоришь на разных языках?\n\n"
        "Соционика знает ответ. Это система, основанная на учении "
        "Карла Юнга о типах личности. Она выделяет 16 уникальных типов — "
        "и каждый из них воспринимает мир, принимает решения "
        "и строит отношения по-своему.\n\n"
        "Кто-то рождён вести за собой. Кто-то — видеть будущее раньше других. "
        "Кто-то создаёт вокруг себя тепло, а кто-то — безупречные системы.\n\n"
        "А к какому типу относишься ты?\n\n"
        "Пройди короткий тест — всего пара минут — и узнай свой социотип. "
        "Возможно, ты наконец поймёшь, почему ты именно такой. "
        "И это будет самое интересное открытие о себе за долгое время."
    )

    if context.user_data.get(CURRENT_DICHOTOMY, 0) > 0 or context.user_data.get(CURRENT_PAIR_INDEX, 0) > 0:
        text += "\n\n🔔 У тебя есть незавершенный тест! Нажми 'Тест', чтобы продолжить."

    inline_keyboard = [
        [InlineKeyboardButton("📝 Тест", callback_data='start_test')],
        [InlineKeyboardButton("🤝 Совместимость", callback_data='start_compat')]
    ]

    await update.message.reply_text(text, reply_markup=REPLY_KEYBOARD)
    await update.message.reply_text("Выберите действие:", reply_markup=InlineKeyboardMarkup(inline_keyboard))


# ─── Test handlers ───────────────────────────────────────────────────────────

async def start_test_msg(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if context.user_data.get(CURRENT_DICHOTOMY, 0) > 0 or context.user_data.get(CURRENT_PAIR_INDEX, 0) > 0:
        keyboard = [
            [InlineKeyboardButton("▶️ Продолжить", callback_data='continue_test')],
            [InlineKeyboardButton("🔄 Начать заново", callback_data='restart_test')]
        ]
        await update.message.reply_text("У вас есть незавершенный тест. Продолжить или начать заново?",
                                        reply_markup=InlineKeyboardMarkup(keyboard))
    else:
        context.user_data[CURRENT_DICHOTOMY] = 0
        context.user_data[CURRENT_PAIR_INDEX] = 0
        context.user_data[SCORES] = {'E': 0, 'I': 0, 'S': 0, 'N': 0, 'T': 0, 'F': 0, 'J': 0, 'P': 0}
        await send_next_pair_new(update.message, context)


async def start_compat_msg(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await show_type_selection_new(update.message, "Выберите ВАШ тип:", "my")


async def start_test_cb(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    if context.user_data.get(CURRENT_DICHOTOMY, 0) > 0 or context.user_data.get(CURRENT_PAIR_INDEX, 0) > 0:
        keyboard = [
            [InlineKeyboardButton("▶️ Продолжить", callback_data='continue_test')],
            [InlineKeyboardButton("🔄 Начать заново", callback_data='restart_test')]
        ]
        await query.message.edit_text("У вас есть незавершенный тест. Продолжить или начать заново?",
                                      reply_markup=InlineKeyboardMarkup(keyboard))
    else:
        context.user_data[CURRENT_DICHOTOMY] = 0
        context.user_data[CURRENT_PAIR_INDEX] = 0
        context.user_data[SCORES] = {'E': 0, 'I': 0, 'S': 0, 'N': 0, 'T': 0, 'F': 0, 'J': 0, 'P': 0}
        await send_next_pair_edit(query.message, context)


async def restart_test(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    context.user_data[CURRENT_DICHOTOMY] = 0
    context.user_data[CURRENT_PAIR_INDEX] = 0
    context.user_data[SCORES] = {'E': 0, 'I': 0, 'S': 0, 'N': 0, 'T': 0, 'F': 0, 'J': 0, 'P': 0}
    await send_next_pair_edit(query.message, context)


async def continue_test(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    await send_next_pair_edit(query.message, context)


# ─── Question flow ────────────────────────────────────────────────────────────

async def send_next_pair_new(message, context: ContextTypes.DEFAULT_TYPE) -> None:
    init_user_data(context)
    d_idx = context.user_data[CURRENT_DICHOTOMY]
    p_idx = context.user_data[CURRENT_PAIR_INDEX]
    dichotomy_keys = list(DICHOTOMIES.keys())

    if d_idx < len(dichotomy_keys):
        d_key = dichotomy_keys[d_idx]
        pairs = DICHOTOMIES[d_key]['options']
        if p_idx < len(pairs):
            w1_text, w1_val = pairs[p_idx]
            w2_text, w2_val = pairs[p_idx + 1]
            total_pairs = len(pairs) // 2
            current_pair = (p_idx // 2) + 1
            text = f"Блок {d_idx + 1}/4. Пара {current_pair}/{total_pairs}:\nЧто вам ближе?"
            keyboard = [
                [InlineKeyboardButton(w1_text, callback_data=f"ans_{w1_val}")],
                [InlineKeyboardButton(w2_text, callback_data=f"ans_{w2_val}")]
            ]
            await message.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard))
        else:
            context.user_data[CURRENT_DICHOTOMY] += 1
            context.user_data[CURRENT_PAIR_INDEX] = 0
            await send_next_pair_new(message, context)
    else:
        await calculate_and_send_result_new(message, context)


async def send_next_pair_edit(message, context: ContextTypes.DEFAULT_TYPE) -> None:
    init_user_data(context)
    d_idx = context.user_data[CURRENT_DICHOTOMY]
    p_idx = context.user_data[CURRENT_PAIR_INDEX]
    dichotomy_keys = list(DICHOTOMIES.keys())

    if d_idx < len(dichotomy_keys):
        d_key = dichotomy_keys[d_idx]
        pairs = DICHOTOMIES[d_key]['options']
        if p_idx < len(pairs):
            w1_text, w1_val = pairs[p_idx]
            w2_text, w2_val = pairs[p_idx + 1]
            total_pairs = len(pairs) // 2
            current_pair = (p_idx // 2) + 1
            text = f"Блок {d_idx + 1}/4. Пара {current_pair}/{total_pairs}:\nЧто вам ближе?"
            keyboard = [
                [InlineKeyboardButton(w1_text, callback_data=f"ans_{w1_val}")],
                [InlineKeyboardButton(w2_text, callback_data=f"ans_{w2_val}")]
            ]
            try:
                await message.edit_text(text, reply_markup=InlineKeyboardMarkup(keyboard))
            except Exception:
                await message.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard))
        else:
            context.user_data[CURRENT_DICHOTOMY] += 1
            context.user_data[CURRENT_PAIR_INDEX] = 0
            await send_next_pair_edit(message, context)
    else:
        await calculate_and_send_result_edit(message, context)


async def handle_answer(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    init_user_data(context)
    val = query.data.split('_')[1]
    context.user_data[SCORES][val] += 1
    context.user_data[CURRENT_PAIR_INDEX] += 2
    await send_next_pair_edit(query.message, context)


# ─── Results ──────────────────────────────────────────────────────────────────

def _build_result_text(context):
    scores = context.user_data[SCORES]
    sociotype_code = calculate_type(scores)
    sociotype_info = TYPES.get(sociotype_code, {
        "name": "Неизвестный тип", "alias": "???", "code": "???", "desc": "Описание отсутствует."
    })
    context.user_data[CURRENT_DICHOTOMY] = 0
    context.user_data[CURRENT_PAIR_INDEX] = 0

    prof_text = ""
    if sociotype_info.get('prof'):
        prof_lines = sociotype_info['prof'].split('\n')
        prof_text = "\n\n💼 Профессиональные ценности:\n" + "\n".join([f"• {line}" for line in prof_lines])

    result_text = (
        f"🎯 Ваш социотип: {sociotype_info['name']} ({sociotype_info['alias']})\n\n"
        f"📖 {sociotype_info['desc']}{prof_text}"
    )
    keyboard = [
        [InlineKeyboardButton("🤝 Совместимость", callback_data='start_compat')],
        [InlineKeyboardButton("🏠 В меню", callback_data='to_main')]
    ]
    return result_text, keyboard, sociotype_info


async def calculate_and_send_result_new(message, context: ContextTypes.DEFAULT_TYPE) -> None:
    result_text, keyboard, sociotype_info = _build_result_text(context)
    _log_result(message, sociotype_info)
    await message.reply_text(result_text, reply_markup=InlineKeyboardMarkup(keyboard))


async def calculate_and_send_result_edit(message, context: ContextTypes.DEFAULT_TYPE) -> None:
    result_text, keyboard, sociotype_info = _build_result_text(context)
    _log_result(message, sociotype_info)
    try:
        await message.edit_text(result_text, reply_markup=InlineKeyboardMarkup(keyboard))
    except Exception:
        await message.reply_text(result_text, reply_markup=InlineKeyboardMarkup(keyboard))


# ─── Compatibility ────────────────────────────────────────────────────────────

async def start_compat_cb(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    await show_type_selection_edit(query.message, "Выберите ВАШ тип:", "my")


async def show_type_selection_new(message, text, prefix):
    keyboard = []
    row = []
    for code in TIMS_ORDER:
        row.append(InlineKeyboardButton(TYPES[code]['alias'], callback_data=f"{prefix}_{code}"))
        if len(row) == 4:
            keyboard.append(row)
            row = []
    if row:
        keyboard.append(row)

    await message.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard))


async def show_type_selection_edit(message, text, prefix):
    keyboard = []
    row = []
    for code in TIMS_ORDER:
        row.append(InlineKeyboardButton(TYPES[code]['alias'], callback_data=f"{prefix}_{code}"))
        if len(row) == 4:
            keyboard.append(row)
            row = []
    if row:
        keyboard.append(row)

    try:
        await message.edit_text(text, reply_markup=InlineKeyboardMarkup(keyboard))
    except Exception:
        await message.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard))


async def type_selected_cb(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    prefix, selected_type_code = query.data.split('_')

    if prefix == "my":
        context.user_data['my_type'] = selected_type_code
        await show_type_selection_edit(query.message, "Выберите тип ПАРТНЕРА:", "partner")
    elif prefix == "partner":
        context.user_data['partner_type'] = selected_type_code
        await calculate_and_send_relation(query.message, context)


async def calculate_and_send_relation(message, context: ContextTypes.DEFAULT_TYPE) -> None:
    my_type = context.user_data.get('my_type')
    partner_type = context.user_data.get('partner_type')

    if my_type and partner_type:
        relation_info = get_relation(my_type, partner_type)
        my_type_alias = TYPES[my_type]['alias']
        partner_type_alias = TYPES[partner_type]['alias']

        text = (
            f"Ваш тип: {TYPES[my_type]['name']} ({my_type_alias})\n"
            f"Тип партнера: {TYPES[partner_type]['name']} ({partner_type_alias})\n\n"
            f"🤝 Отношения: {relation_info['name']}\n\n"
            f"📖 {relation_info['desc']}"
        )
        keyboard = [
            [InlineKeyboardButton("🔄 Проверить еще раз", callback_data='start_compat')],
            [InlineKeyboardButton("🏠 В меню", callback_data='to_main')]
        ]
        try:
            await message.edit_text(text, reply_markup=InlineKeyboardMarkup(keyboard))
        except Exception:
            await message.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard))
    else:
        await message.reply_text("Произошла ошибка при определении типов. Пожалуйста, попробуйте снова.")


# ─── Navigation ──────────────────────────────────────────────────────────────

async def to_main_cb(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    await start(query.message, context)


# ─── Error handler ───────────────────────────────────────────────────────────

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Log the error and send a telegram message to notify the developer."""
    logger.error("Exception while handling an update:", exc_info=context.error)

    # traceback.format_exception returns a list of strings, we want to join them together.
    tb_list = traceback.format_exception(None, context.error, context.error.__traceback__)
    tb_string = "".join(tb_list)

    # Build the message with some markup and send it to the developer via Telegram.
    message = (
        f"An exception was raised while handling an update\n"
        f"<pre>update = {html.escape(json.dumps(update.to_dict(), indent=2))}"
        f"</pre>\n\n"
        f"<pre>context.chat_data = {html.escape(str(context.chat_data))}</pre>\n\n"
        f"<pre>context.user_data = {html.escape(str(context.user_data))}</pre>\n\n"
        f"<pre>{html.escape(tb_string)}</pre>"
    )

    # In case of an error, send a message to the user
    if update.effective_message:
        await update.effective_message.reply_text(
            "Произошла ошибка при обработке вашего запроса. Пожалуйста, попробуйте позже."
        )


# ─── Main ────────────────────────────────────────────────────────────────────

def main() -> None:
    """Start the bot."""
    # Create the Application and pass it your bot's token.

    request = HTTPXRequest(connection_pool_size=5, read_timeout=10.0, write_timeout=10.0, pool_timeout=10.0)

    application = Application.builder().token(os.getenv("BOT_TOKEN")).build()

    # Get all handlers from the bot
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("test", start_test_msg))
    application.add_handler(MessageHandler(filters.Regex("🏠 Главное меню"), start))
    application.add_handler(MessageHandler(filters.Regex("📝 Тест"), start_test_msg))
    application.add_handler(MessageHandler(filters.Regex("🤝 Совместимость"), start_compat_msg))
    application.add_handler(CallbackQueryHandler(start_test_cb, pattern='^start_test$'))
    application.add_handler(CallbackQueryHandler(start_compat_cb, pattern='^start_compat$'))
    application.add_handler(CallbackQueryHandler(restart_test, pattern='^restart_test$'))
    application.add_handler(CallbackQueryHandler(continue_test, pattern='^continue_test$'))
    application.add_handler(CallbackQueryHandler(handle_answer, pattern='^ans_'))
    application.add_handler(CallbackQueryHandler(type_selected_cb, pattern='^(my|partner)_'))
    application.add_handler(CallbackQueryHandler(to_main_cb, pattern='^to_main$'))

    # Error handler
    application.add_error_handler(error_handler)

    logger.info("Bot starting...")
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()

import logging
import os
import asyncio
from datetime import datetime

try:
    from systemd.daemon import notify, Notification
except ImportError:
    def notify(state): pass
    class Notification:
        READY = "READY=1"
        WATCHDOG = "WATCHDOG=1"

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes, MessageHandler, filters
from socionics_data import DICHOTOMIES, TYPES, calculate_type
from relations_data import get_relation, TIMS_ORDER

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

CURRENT_DICHOTOMY = 'current_dichotomy'
CURRENT_PAIR_INDEX = 'current_pair_index'
SCORES = 'scores'
USER_TYPE = 'user_type'

REPLY_KEYBOARD = ReplyKeyboardMarkup(
    [[KeyboardButton("🏠 Главное меню")],
     [KeyboardButton("📝 Тест"), KeyboardButton("🤝 Совместимость")]],
    resize_keyboard=True
)

QUADRA_VALUES = (
    "*⚡️ 1-я Квадра Альфа* _(дети)_\n"
    "Ценности: открытость, новизна, радость познания, демократия, равенство\n\n"
    "*🔥 2-я Квадра Бета* _(подростки)_\n"
    "Ценности: иерархия, власть, героизм, жертвенность, идеология\n\n"
    "*💫 3-я Квадра Гамма* _(взрослые)_\n"
    "Ценности: эффективность, результат, конкуренция, справедливость, деньги\n\n"
    "*🌿 4-я Квадра Дельта* _(мудрецы)_\n"
    "Ценности: качество жизни, уют, мудрость, гармония, экология"
)

SELECT_TYPE_TEXT = "Выберите тип:

def init_user_data(context):
    if SCORES not in context.user_data:
        context.user_data[SCORES] = {'E': 0, 'I': 0, 'S': 0, 'N': 0, 'T': 0, 'F': 0, 'J': 0, 'P': 0}
    if CURRENT_DICHOTOMY not in context.user_data:
        context.user_data[CURRENT_DICHOTOMY] = 0
    if CURRENT_PAIR_INDEX not in context.user_data:
        context.user_data[CURRENT_PAIR_INDEX] = 0

def _log_result(message, sociotype_info):
    try:
        user = message.chat
        log_entry = (
            f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} | "
            f"ID: {user.id} | "
            f"User: @{getattr(user, 'username', 'no_username') or 'no_username'} "
            f"({getattr(user, 'first_name', '')}) | "
            f"Result: {sociotype_info['name']}\n"
        )
        with open("results.txt", "a", encoding="utf-8") as f:
            f.write(log_entry)
    except Exception as e:
        logger.error(f"Failed to write result log: {e}")

def _make_type_keyboard(prefix):
    quadras = [
        ("⚡️ 1-я Квадра Альфа — дети", ['ILE', 'SEI', 'ESE', 'LII']),
        ("🔥 2-я Квадра Бета — подростки", ['EIE', 'LSI', 'SLE', 'IEI']),
        ("💫 3-я Квадра Гамма — взрослые", ['SEE', 'ILI', 'LIE', 'ESI']),
        ("🌿 4-я Квадра Дельта — мудрецы", ['LSE', 'EII', 'IEE', 'SLI']),
    ]
    keyboard = []
    for quadra_name, codes in quadras:
        keyboard.append([InlineKeyboardButton(quadra_name, callback_data='ignore')])
        row = [InlineKeyboardButton(TYPES[code]['name'], callback_data=f"{prefix}_{code}") for code in codes]
        keyboard.append(row)
    return keyboard

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
    if context.user_data.get(USER_TYPE):
        code = context.user_data[USER_TYPE]
        name = TYPES.get(code, {}).get('name', '')
        inline_keyboard.insert(1, [InlineKeyboardButton(f"👤 Мой тип: {name}", callback_data='my_result')])
    await update.message.reply_text(text, reply_markup=REPLY_KEYBOARD)
    await update.message.reply_text("Выберите действие:", reply_markup=InlineKeyboardMarkup(inline_keyboard))

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
    keyboard = [[InlineKeyboardButton("📖 Ценности квадр", callback_data='show_values')]] + _make_type_keyboard("my")
    await update.message.reply_text("Выберите ВАШ тип:",
        reply_markup=InlineKeyboardMarkup(keyboard))

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

async def send_next_pair_new(message, context) -> None:
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

async def send_next_pair_edit(message, context) -> None:
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

def _build_result_text(context):
    scores = context.user_data[SCORES]
    sociotype_code = calculate_type(scores)
    sociotype_info = TYPES.get(sociotype_code, {
        "name": "Неизвестный тип", "alias": "???", "desc": "Описание отсутствует."
    })
    context.user_data[USER_TYPE] = sociotype_code
    context.user_data[CURRENT_DICHOTOMY] = 0
    context.user_data[CURRENT_PAIR_INDEX] = 0
    context.user_data[SCORES] = {'E': 0, 'I': 0, 'S': 0, 'N': 0, 'T': 0, 'F': 0, 'J': 0, 'P': 0}
    prof_text = ""
    if sociotype_info.get('prof'):
        prof_lines = sociotype_info['prof'].split('\n')
        prof_text = "\n\n💼 Профессиональные ценности:\n" + "\n".join([f"• {line}" for line in prof_lines])
    best_relations = {'Дуальные': '💚', 'Тождественные': '💛', 'Полудуальные': '🩵', 'Родственные': '🤝'}
    best_text = "\n\n✨ Лучшие сочетания:\n"
    type_relations = RELATIONS_DATA.get(sociotype_code, {})
    found = {name: [] for name in best_relations}
    for partner_code, rel in type_relations.items():
        rel_name = rel.get('name', '')
        if rel_name in best_relations:
            partner_name = TYPES.get(partner_code, {}).get('name', partner_code)
            found[rel_name].append(partner_name)
    for rel_name, emoji in best_relations.items():
        if found[rel_name]:
            best_text += f"{emoji} {rel_name}: {', '.join(found[rel_name])}\n"
    result_text = (
        f"🎯 Ваш социотип: {sociotype_info['name']} ({sociotype_info.get('alias', '')})\n\n"
        f"📖 {sociotype_info['desc']}{prof_text}{best_text}"
    )
    keyboard = [
        [InlineKeyboardButton("🤝 Совместимость", callback_data='start_compat')],
        [InlineKeyboardButton("🏠 В меню", callback_data='to_main')]
    ]
    return result_text, keyboard, sociotype_info

async def calculate_and_send_result_new(message, context) -> None:
    result_text, keyboard, sociotype_info = _build_result_text(context)
    _log_result(message, sociotype_info)
    await message.reply_text(result_text, reply_markup=InlineKeyboardMarkup(keyboard))

async def calculate_and_send_result_edit(message, context) -> None:
    result_text, keyboard, sociotype_info = _build_result_text(context)
    _log_result(message, sociotype_info)
    try:
        await message.edit_text(result_text, reply_markup=InlineKeyboardMarkup(keyboard))
    except Exception:
        await message.reply_text(result_text, reply_markup=InlineKeyboardMarkup(keyboard))

async def start_compat_cb(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    keyboard = [[InlineKeyboardButton("📖 Ценности квадр", callback_data='show_values')]] + _make_type_keyboard("my")
    try:
        await query.message.edit_text("Выберите ВАШ тип:",
            reply_markup=InlineKeyboardMarkup(keyboard))
    except Exception:
        await query.message.reply_text("Выберите ВАШ тип:",
            reply_markup=InlineKeyboardMarkup(keyboard))

async def show_values_cb(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    keyboard = [[InlineKeyboardButton("◀️ Назад", callback_data='start_compat')]]
    try:
        await query.message.edit_text(QUADRA_VALUES,
            reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')
    except Exception:
        await query.message.reply_text(QUADRA_VALUES,
            reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')

async def type_selected_cb(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    parts = query.data.split('_', 1)
    prefix = parts[0]
    selected_type_code = parts[1]
    if prefix == "my":
        context.user_data['my_type'] = selected_type_code
        keyboard = [[InlineKeyboardButton("📖 Ценности квадр", callback_data='show_values')]] + _make_type_keyboard("partner")
        try:
            await query.message.edit_text("Выберите тип ПАРТНЕРА:",
                reply_markup=InlineKeyboardMarkup(keyboard))
        except Exception:
            await query.message.reply_text("Выберите тип ПАРТНЕРА:",
                reply_markup=InlineKeyboardMarkup(keyboard))
    elif prefix == "partner":
        context.user_data['partner_type'] = selected_type_code
        await calculate_and_send_relation(query.message, context)

async def calculate_and_send_relation(message, context) -> None:
    my_type = context.user_data.get('my_type')
    partner_type = context.user_data.get('partner_type')
    if my_type and partner_type:
        relation_info = get_relation(my_type, partner_type)
        text = (
            f"👤 Вы: {TYPES[my_type]['name']}\n"
            f"👤 Партнер: {TYPES[partner_type]['name']}\n\n"
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
        await message.reply_text("Произошла ошибка. Попробуйте снова.")

async def my_result_cb(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    code = context.user_data.get(USER_TYPE)
    if not code:
        await query.message.edit_text("У вас ещё нет результата. Пройдите тест!",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("📝 Тест", callback_data='start_test')]]))
        return
    sociotype_info = TYPES.get(code, {})
    prof_text = ""
    if sociotype_info.get('prof'):
        prof_lines = sociotype_info['prof'].split('\n')
        prof_text = "\n\n💼 Профессиональные ценности:\n" + "\n".join([f"• {line}" for line in prof_lines])
    text = (
        f"👤 Ваш социотип: {sociotype_info.get('name', '')} ({sociotype_info.get('alias', '')})\n\n"
        f"📖 {sociotype_info.get('desc', '')}{prof_text}"
    )
    keyboard = [
        [InlineKeyboardButton("🤝 Совместимость", callback_data='start_compat')],
        [InlineKeyboardButton("🔄 Пройти заново", callback_data='reset_type')],
        [InlineKeyboardButton("🏠 В меню", callback_data='to_main')]
    ]
    try:
        await query.message.edit_text(text, reply_markup=InlineKeyboardMarkup(keyboard))
    except Exception:
        await query.message.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard))

async def reset_type(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    context.user_data[USER_TYPE] = None
    context.user_data[CURRENT_DICHOTOMY] = 0
    context.user_data[CURRENT_PAIR_INDEX] = 0
    context.user_data[SCORES] = {'E': 0, 'I': 0, 'S': 0, 'N': 0, 'T': 0, 'F': 0, 'J': 0, 'P': 0}
    await send_next_pair_edit(query.message, context)

async def to_main_cb(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    user = update.effective_user
    text = f"Привет, {user.first_name}! Я бот по соционике.\n\nИспользуй кнопки ниже 👇"
    inline_keyboard = [
        [InlineKeyboardButton("📝 Тест", callback_data='start_test')],
        [InlineKeyboardButton("🤝 Совместимость", callback_data='start_compat')]
    ]
    if context.user_data.get(USER_TYPE):
        code = context.user_data[USER_TYPE]
        name = TYPES.get(code, {}).get('name', '')
        inline_keyboard.insert(1, [InlineKeyboardButton(f"👤 Мой тип: {name}", callback_data='my_result')])
    try:
        await query.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard))
    except Exception:
        await query.message.reply_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard))

async def admin_get_results(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_user.id != 121787264:
        return
    try:
        with open("results.txt", "r", encoding="utf-8") as f:
            lines = f.readlines()
        if not lines:
            await update.message.reply_text("📭 Результатов пока нет.")
            return
        from collections import Counter
        types_count = Counter()
        for line in lines:
            if "Result:" in line:
                result = line.split("Result:")[-1].strip()
                types_count[result] += 1
        total = len(lines)
        stats = f"📊 Всего пройдено тестов: {total}\n\n🏆 Топ социотипов:\n"
        for t, count in types_count.most_common(5):
            stats += f"  • {t}: {count}\n"
        await update.message.reply_text(stats)
        with open("results.txt", "rb") as f:
            await update.message.reply_document(document=f, filename="results.txt",
                caption=f"📋 Полный список ({total} чел.)")
    except FileNotFoundError:
        await update.message.reply_text("📭 Результатов пока нет.")
    except Exception as e:
        await update.message.reply_text(f"❌ Ошибка: {e}")

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.error("Exception while handling an update:", exc_info=context.error)

def main() -> None:
    from relations_data import RELATIONS
    global RELATIONS_DATA
    RELATIONS_DATA = RELATIONS

    application = Application.builder().token(os.getenv("BOT_TOKEN")).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("test", start_test_msg))
    application.add_handler(CommandHandler("compat", start_compat_msg))
    application.add_handler(CommandHandler("admin", admin_get_results))
    application.add_handler(MessageHandler(filters.Regex("🏠 Главное меню"), start))
    application.add_handler(MessageHandler(filters.Regex("📝 Тест"), start_test_msg))
    application.add_handler(MessageHandler(filters.Regex("🤝 Совместимость"), start_compat_msg))
    application.add_handler(CallbackQueryHandler(start_test_cb, pattern='^start_test$'))
    application.add_handler(CallbackQueryHandler(start_compat_cb, pattern='^start_compat$'))
    application.add_handler(CallbackQueryHandler(restart_test, pattern='^restart_test$'))
    application.add_handler(CallbackQueryHandler(continue_test, pattern='^continue_test$'))
    application.add_handler(CallbackQueryHandler(handle_answer, pattern='^ans_'))
    application.add_handler(CallbackQueryHandler(show_values_cb, pattern='^show_values$'))
    application.add_handler(CallbackQueryHandler(lambda u, c: u.callback_query.answer(), pattern='^ignore$'))
    application.add_handler(CallbackQueryHandler(type_selected_cb, pattern='^(my|partner)_'))
    application.add_handler(CallbackQueryHandler(my_result_cb, pattern='^my_result$'))
    application.add_handler(CallbackQueryHandler(reset_type, pattern='^reset_type$'))
    application.add_handler(CallbackQueryHandler(to_main_cb, pattern='^to_main$'))
    application.add_error_handler(error_handler)

    logger.info("Bot starting...")
    application.run_polling(
        drop_pending_updates=True,
        allowed_updates=Update.ALL_TYPES,
        timeout=30,
        read_timeout=30,
        write_timeout=30,
        connect_timeout=30,
        pool_timeout=30,
    )

if __name__ == "__main__":
    main()

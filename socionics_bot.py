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
    [[KeyboardButton("рџЏ  Р“Р»Р°РІРЅРѕРµ РјРµРЅСЋ")],
     [KeyboardButton("рџ“ќ РўРµСЃС‚"), KeyboardButton("рџ¤ќ РЎРѕРІРјРµСЃС‚РёРјРѕСЃС‚СЊ")]],
    resize_keyboard=True
)

QUADRA_TEXT = (
    "*1-СЏ РљРІР°РґСЂР° вЂ” РђР»СЊС„Р°* _(РґРµС‚Рё)_\n"
    "Р”РѕРЅ РљРёС…РѕС‚, Р”СЋРјР°, Р“СЋРіРѕ, Р РѕР±РµСЃРїСЊРµСЂ\n"
    "Р¦РµРЅРЅРѕСЃС‚Рё: РѕС‚РєСЂС‹С‚РѕСЃС‚СЊ, РЅРѕРІРёР·РЅР°, СЂР°РґРѕСЃС‚СЊ РїРѕР·РЅР°РЅРёСЏ, РґРµРјРѕРєСЂР°С‚РёСЏ, СЂР°РІРµРЅСЃС‚РІРѕ\n\n"
    "*2-СЏ РљРІР°РґСЂР° вЂ” Р‘РµС‚Р°* _(РїРѕРґСЂРѕСЃС‚РєРё)_\n"
    "Р“Р°РјР»РµС‚, РњР°РєСЃРёРј Р“РѕСЂСЊРєРёР№, Р–СѓРєРѕРІ, Р•СЃРµРЅРёРЅ\n"
    "Р¦РµРЅРЅРѕСЃС‚Рё: РёРµСЂР°СЂС…РёСЏ, РІР»Р°СЃС‚СЊ, РіРµСЂРѕРёР·Рј, Р¶РµСЂС‚РІРµРЅРЅРѕСЃС‚СЊ, РёРґРµРѕР»РѕРіРёСЏ\n\n"
    "*3-СЏ РљРІР°РґСЂР° вЂ” Р“Р°РјРјР°* _(РІР·СЂРѕСЃР»С‹Рµ)_\n"
    "РќР°РїРѕР»РµРѕРЅ, Р‘Р°Р»СЊР·Р°Рє, Р”Р¶РµРє Р›РѕРЅРґРѕРЅ, Р”СЂР°Р№Р·РµСЂ\n"
    "Р¦РµРЅРЅРѕСЃС‚Рё: СЌС„С„РµРєС‚РёРІРЅРѕСЃС‚СЊ, СЂРµР·СѓР»СЊС‚Р°С‚, РєРѕРЅРєСѓСЂРµРЅС†РёСЏ, СЃРїСЂР°РІРµРґР»РёРІРѕСЃС‚СЊ, РґРµРЅСЊРіРё\n\n"
    "*4-СЏ РљРІР°РґСЂР° вЂ” Р”РµР»СЊС‚Р°* _(РјСѓРґСЂРµС†С‹)_\n"
    "РЁС‚РёСЂР»РёС†, Р”РѕСЃС‚РѕРµРІСЃРєРёР№, Р“РµРєСЃР»Рё, Р“Р°Р±РµРЅ\n"
    "Р¦РµРЅРЅРѕСЃС‚Рё: РєР°С‡РµСЃС‚РІРѕ Р¶РёР·РЅРё, СѓСЋС‚, РјСѓРґСЂРѕСЃС‚СЊ, РіР°СЂРјРѕРЅРёСЏ, СЌРєРѕР»РѕРіРёСЏ"
)

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
    keyboard = []
    row = []
    for code in TIMS_ORDER:
        row.append(InlineKeyboardButton(TYPES[code]['name'], callback_data=f"{prefix}_{code}"))
        if len(row) == 4:
            keyboard.append(row)
            row = []
    if row:
        keyboard.append(row)
    return keyboard

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    await context.bot.set_my_commands([
        ("start", "Р“Р»Р°РІРЅРѕРµ РјРµРЅСЋ"),
        ("test", "РќР°С‡Р°С‚СЊ/РџСЂРѕРґРѕР»Р¶РёС‚СЊ С‚РµСЃС‚"),
        ("compat", "РџСЂРѕРІРµСЂРёС‚СЊ СЃРѕРІРјРµСЃС‚РёРјРѕСЃС‚СЊ")
    ])
    text = (
        f"РџСЂРёРІРµС‚, {user.first_name}! рџ‘‹\n\n"
        "Р—РЅР°РµС€СЊ, РїРѕС‡РµРјСѓ СЃ РѕРґРЅРёРјРё Р»СЋРґСЊРјРё С‚С‹ РЅР° РѕРґРЅРѕР№ РІРѕР»РЅРµ, "
        "Р° СЃ РґСЂСѓРіРёРјРё вЂ” Р±СѓРґС‚Рѕ РіРѕРІРѕСЂРёС€СЊ РЅР° СЂР°Р·РЅС‹С… СЏР·С‹РєР°С…?\n\n"
        "РЎРѕС†РёРѕРЅРёРєР° Р·РЅР°РµС‚ РѕС‚РІРµС‚. Р­С‚Рѕ СЃРёСЃС‚РµРјР°, РѕСЃРЅРѕРІР°РЅРЅР°СЏ РЅР° СѓС‡РµРЅРёРё "
        "РљР°СЂР»Р° Р®РЅРіР° Рѕ С‚РёРїР°С… Р»РёС‡РЅРѕСЃС‚Рё. РћРЅР° РІС‹РґРµР»СЏРµС‚ 16 СѓРЅРёРєР°Р»СЊРЅС‹С… С‚РёРїРѕРІ вЂ” "
        "Рё РєР°Р¶РґС‹Р№ РёР· РЅРёС… РІРѕСЃРїСЂРёРЅРёРјР°РµС‚ РјРёСЂ, РїСЂРёРЅРёРјР°РµС‚ СЂРµС€РµРЅРёСЏ "
        "Рё СЃС‚СЂРѕРёС‚ РѕС‚РЅРѕС€РµРЅРёСЏ РїРѕ-СЃРІРѕРµРјСѓ.\n\n"
        "РљС‚Рѕ-С‚Рѕ СЂРѕР¶РґС‘РЅ РІРµСЃС‚Рё Р·Р° СЃРѕР±РѕР№. РљС‚Рѕ-С‚Рѕ вЂ” РІРёРґРµС‚СЊ Р±СѓРґСѓС‰РµРµ СЂР°РЅСЊС€Рµ РґСЂСѓРіРёС…. "
        "РљС‚Рѕ-С‚Рѕ СЃРѕР·РґР°С‘С‚ РІРѕРєСЂСѓРі СЃРµР±СЏ С‚РµРїР»Рѕ, Р° РєС‚Рѕ-С‚Рѕ вЂ” Р±РµР·СѓРїСЂРµС‡РЅС‹Рµ СЃРёСЃС‚РµРјС‹.\n\n"
        "Рђ Рє РєР°РєРѕРјСѓ С‚РёРїСѓ РѕС‚РЅРѕСЃРёС€СЊСЃСЏ С‚С‹?\n\n"
        "РџСЂРѕР№РґРё РєРѕСЂРѕС‚РєРёР№ С‚РµСЃС‚ вЂ” РІСЃРµРіРѕ РїР°СЂР° РјРёРЅСѓС‚ вЂ” Рё СѓР·РЅР°Р№ СЃРІРѕР№ СЃРѕС†РёРѕС‚РёРї. "
        "Р’РѕР·РјРѕР¶РЅРѕ, С‚С‹ РЅР°РєРѕРЅРµС† РїРѕР№РјС‘С€СЊ, РїРѕС‡РµРјСѓ С‚С‹ РёРјРµРЅРЅРѕ С‚Р°РєРѕР№. "
        "Р СЌС‚Рѕ Р±СѓРґРµС‚ СЃР°РјРѕРµ РёРЅС‚РµСЂРµСЃРЅРѕРµ РѕС‚РєСЂС‹С‚РёРµ Рѕ СЃРµР±Рµ Р·Р° РґРѕР»РіРѕРµ РІСЂРµРјСЏ."
    )
    if context.user_data.get(CURRENT_DICHOTOMY, 0) > 0 or context.user_data.get(CURRENT_PAIR_INDEX, 0) > 0:
        text += "\n\nрџ”” РЈ С‚РµР±СЏ РµСЃС‚СЊ РЅРµР·Р°РІРµСЂС€РµРЅРЅС‹Р№ С‚РµСЃС‚! РќР°Р¶РјРё 'РўРµСЃС‚', С‡С‚РѕР±С‹ РїСЂРѕРґРѕР»Р¶РёС‚СЊ."
    inline_keyboard = [
        [InlineKeyboardButton("рџ“ќ РўРµСЃС‚", callback_data='start_test')],
        [InlineKeyboardButton("рџ¤ќ РЎРѕРІРјРµСЃС‚РёРјРѕСЃС‚СЊ", callback_data='start_compat')]
    ]
    if context.user_data.get(USER_TYPE):
        code = context.user_data[USER_TYPE]
        name = TYPES.get(code, {}).get('name', '')
        inline_keyboard.insert(1, [InlineKeyboardButton(f"рџ‘¤ РњРѕР№ С‚РёРї: {name}", callback_data='my_result')])
    await update.message.reply_text(text, reply_markup=REPLY_KEYBOARD)
    await update.message.reply_text("Р’С‹Р±РµСЂРёС‚Рµ РґРµР№СЃС‚РІРёРµ:", reply_markup=InlineKeyboardMarkup(inline_keyboard))

async def start_test_msg(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if context.user_data.get(CURRENT_DICHOTOMY, 0) > 0 or context.user_data.get(CURRENT_PAIR_INDEX, 0) > 0:
        keyboard = [
            [InlineKeyboardButton("в–¶пёЏ РџСЂРѕРґРѕР»Р¶РёС‚СЊ", callback_data='continue_test')],
            [InlineKeyboardButton("рџ”„ РќР°С‡Р°С‚СЊ Р·Р°РЅРѕРІРѕ", callback_data='restart_test')]
        ]
        await update.message.reply_text("РЈ РІР°СЃ РµСЃС‚СЊ РЅРµР·Р°РІРµСЂС€РµРЅРЅС‹Р№ С‚РµСЃС‚. РџСЂРѕРґРѕР»Р¶РёС‚СЊ РёР»Рё РЅР°С‡Р°С‚СЊ Р·Р°РЅРѕРІРѕ?",
                                        reply_markup=InlineKeyboardMarkup(keyboard))
    else:
        context.user_data[CURRENT_DICHOTOMY] = 0
        context.user_data[CURRENT_PAIR_INDEX] = 0
        context.user_data[SCORES] = {'E': 0, 'I': 0, 'S': 0, 'N': 0, 'T': 0, 'F': 0, 'J': 0, 'P': 0}
        await send_next_pair_new(update.message, context)

async def start_compat_msg(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(QUADRA_TEXT,
        reply_markup=InlineKeyboardMarkup(_make_type_keyboard("my")), parse_mode='Markdown')

async def start_test_cb(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    if context.user_data.get(CURRENT_DICHOTOMY, 0) > 0 or context.user_data.get(CURRENT_PAIR_INDEX, 0) > 0:
        keyboard = [
            [InlineKeyboardButton("в–¶пёЏ РџСЂРѕРґРѕР»Р¶РёС‚СЊ", callback_data='continue_test')],
            [InlineKeyboardButton("рџ”„ РќР°С‡Р°С‚СЊ Р·Р°РЅРѕРІРѕ", callback_data='restart_test')]
        ]
        await query.message.edit_text("РЈ РІР°СЃ РµСЃС‚СЊ РЅРµР·Р°РІРµСЂС€РµРЅРЅС‹Р№ С‚РµСЃС‚. РџСЂРѕРґРѕР»Р¶РёС‚СЊ РёР»Рё РЅР°С‡Р°С‚СЊ Р·Р°РЅРѕРІРѕ?",
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
            text = f"Р‘Р»РѕРє {d_idx + 1}/4. РџР°СЂР° {current_pair}/{total_pairs}:\nР§С‚Рѕ РІР°Рј Р±Р»РёР¶Рµ?"
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
            text = f"Р‘Р»РѕРє {d_idx + 1}/4. РџР°СЂР° {current_pair}/{total_pairs}:\nР§С‚Рѕ РІР°Рј Р±Р»РёР¶Рµ?"
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
        "name": "РќРµРёР·РІРµСЃС‚РЅС‹Р№ С‚РёРї", "alias": "???", "desc": "РћРїРёСЃР°РЅРёРµ РѕС‚СЃСѓС‚СЃС‚РІСѓРµС‚."
    })
    context.user_data[USER_TYPE] = sociotype_code
    context.user_data[CURRENT_DICHOTOMY] = 0
    context.user_data[CURRENT_PAIR_INDEX] = 0
    context.user_data[SCORES] = {'E': 0, 'I': 0, 'S': 0, 'N': 0, 'T': 0, 'F': 0, 'J': 0, 'P': 0}
    prof_text = ""
    if sociotype_info.get('prof'):
        prof_lines = sociotype_info['prof'].split('\n')
        prof_text = "\n\nрџ’ј РџСЂРѕС„РµСЃСЃРёРѕРЅР°Р»СЊРЅС‹Рµ С†РµРЅРЅРѕСЃС‚Рё:\n" + "\n".join([f"вЂў {line}" for line in prof_lines])
    best_relations = {'Р”СѓР°Р»СЊРЅС‹Рµ': 'рџ’љ', 'РўРѕР¶РґРµСЃС‚РІРµРЅРЅС‹Рµ': 'рџ’›', 'РџРѕР»СѓРґСѓР°Р»СЊРЅС‹Рµ': 'рџ©µ', 'Р РѕРґСЃС‚РІРµРЅРЅС‹Рµ': 'рџ¤ќ'}
    best_text = "\n\nвњЁ Р›СѓС‡С€РёРµ СЃРѕС‡РµС‚Р°РЅРёСЏ:\n"
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
        f"рџЋЇ Р’Р°С€ СЃРѕС†РёРѕС‚РёРї: {sociotype_info['name']} ({sociotype_info.get('alias', '')})\n\n"
        f"рџ“– {sociotype_info['desc']}{prof_text}{best_text}"
    )
    keyboard = [
        [InlineKeyboardButton("рџ¤ќ РЎРѕРІРјРµСЃС‚РёРјРѕСЃС‚СЊ", callback_data='start_compat')],
        [InlineKeyboardButton("рџЏ  Р’ РјРµРЅСЋ", callback_data='to_main')]
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
    try:
        await query.message.edit_text(QUADRA_TEXT,
            reply_markup=InlineKeyboardMarkup(_make_type_keyboard("my")), parse_mode='Markdown')
    except Exception:
        await query.message.reply_text(QUADRA_TEXT,
            reply_markup=InlineKeyboardMarkup(_make_type_keyboard("my")), parse_mode='Markdown')

async def type_selected_cb(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    parts = query.data.split('_', 1)
    prefix = parts[0]
    selected_type_code = parts[1]
    if prefix == "my":
        context.user_data['my_type'] = selected_type_code
        try:
            await query.message.edit_text(QUADRA_TEXT,
                reply_markup=InlineKeyboardMarkup(_make_type_keyboard("partner")), parse_mode='Markdown')
        except Exception:
            await query.message.reply_text(QUADRA_TEXT,
                reply_markup=InlineKeyboardMarkup(_make_type_keyboard("partner")), parse_mode='Markdown')
    elif prefix == "partner":
        context.user_data['partner_type'] = selected_type_code
        await calculate_and_send_relation(query.message, context)

async def calculate_and_send_relation(message, context) -> None:
    my_type = context.user_data.get('my_type')
    partner_type = context.user_data.get('partner_type')
    if my_type and partner_type:
        relation_info = get_relation(my_type, partner_type)
        text = (
            f"рџ‘¤ Р’С‹: {TYPES[my_type]['name']}\n"
            f"рџ‘¤ РџР°СЂС‚РЅРµСЂ: {TYPES[partner_type]['name']}\n\n"
            f"рџ¤ќ РћС‚РЅРѕС€РµРЅРёСЏ: {relation_info['name']}\n\n"
            f"рџ“– {relation_info['desc']}"
        )
        keyboard = [
            [InlineKeyboardButton("рџ”„ РџСЂРѕРІРµСЂРёС‚СЊ РµС‰Рµ СЂР°Р·", callback_data='start_compat')],
            [InlineKeyboardButton("рџЏ  Р’ РјРµРЅСЋ", callback_data='to_main')]
        ]
        try:
            await message.edit_text(text, reply_markup=InlineKeyboardMarkup(keyboard))
        except Exception:
            await message.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard))
    else:
        await message.reply_text("РџСЂРѕРёР·РѕС€Р»Р° РѕС€РёР±РєР°. РџРѕРїСЂРѕР±СѓР№С‚Рµ СЃРЅРѕРІР°.")

async def my_result_cb(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    code = context.user_data.get(USER_TYPE)
    if not code:
        await query.message.edit_text("РЈ РІР°СЃ РµС‰С‘ РЅРµС‚ СЂРµР·СѓР»СЊС‚Р°С‚Р°. РџСЂРѕР№РґРёС‚Рµ С‚РµСЃС‚!",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("рџ“ќ РўРµСЃС‚", callback_data='start_test')]]))
        return
    sociotype_info = TYPES.get(code, {})
    prof_text = ""
    if sociotype_info.get('prof'):
        prof_lines = sociotype_info['prof'].split('\n')
        prof_text = "\n\nрџ’ј РџСЂРѕС„РµСЃСЃРёРѕРЅР°Р»СЊРЅС‹Рµ С†РµРЅРЅРѕСЃС‚Рё:\n" + "\n".join([f"вЂў {line}" for line in prof_lines])
    text = (
        f"рџ‘¤ Р’Р°С€ СЃРѕС†РёРѕС‚РёРї: {sociotype_info.get('name', '')} ({sociotype_info.get('alias', '')})\n\n"
        f"рџ“– {sociotype_info.get('desc', '')}{prof_text}"
    )
    keyboard = [
        [InlineKeyboardButton("рџ¤ќ РЎРѕРІРјРµСЃС‚РёРјРѕСЃС‚СЊ", callback_data='start_compat')],
        [InlineKeyboardButton("рџ”„ РџСЂРѕР№С‚Рё Р·Р°РЅРѕРІРѕ", callback_data='reset_type')],
        [InlineKeyboardButton("рџЏ  Р’ РјРµРЅСЋ", callback_data='to_main')]
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
    text = f"РџСЂРёРІРµС‚, {user.first_name}! РЇ Р±РѕС‚ РїРѕ СЃРѕС†РёРѕРЅРёРєРµ.\n\nРСЃРїРѕР»СЊР·СѓР№ РєРЅРѕРїРєРё РЅРёР¶Рµ рџ‘‡"
    inline_keyboard = [
        [InlineKeyboardButton("рџ“ќ РўРµСЃС‚", callback_data='start_test')],
        [InlineKeyboardButton("рџ¤ќ РЎРѕРІРјРµСЃС‚РёРјРѕСЃС‚СЊ", callback_data='start_compat')]
    ]
    if context.user_data.get(USER_TYPE):
        code = context.user_data[USER_TYPE]
        name = TYPES.get(code, {}).get('name', '')
        inline_keyboard.insert(1, [InlineKeyboardButton(f"рџ‘¤ РњРѕР№ С‚РёРї: {name}", callback_data='my_result')])
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
            await update.message.reply_text("рџ“­ Р РµР·СѓР»СЊС‚Р°С‚РѕРІ РїРѕРєР° РЅРµС‚.")
            return
        from collections import Counter
        types_count = Counter()
        for line in lines:
            if "Result:" in line:
                result = line.split("Result:")[-1].strip()
                types_count[result] += 1
        total = len(lines)
        stats = f"рџ“Љ Р’СЃРµРіРѕ РїСЂРѕР№РґРµРЅРѕ С‚РµСЃС‚РѕРІ: {total}\n\nрџЏ† РўРѕРї СЃРѕС†РёРѕС‚РёРїРѕРІ:\n"
        for t, count in types_count.most_common(5):
            stats += f"  вЂў {t}: {count}\n"
        await update.message.reply_text(stats)
        with open("results.txt", "rb") as f:
            await update.message.reply_document(document=f, filename="results.txt",
                caption=f"рџ“‹ РџРѕР»РЅС‹Р№ СЃРїРёСЃРѕРє ({total} С‡РµР».)")
    except FileNotFoundError:
        await update.message.reply_text("рџ“­ Р РµР·СѓР»СЊС‚Р°С‚РѕРІ РїРѕРєР° РЅРµС‚.")
    except Exception as e:
        await update.message.reply_text(f"вќЊ РћС€РёР±РєР°: {e}")

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
    application.add_handler(MessageHandler(filters.Regex("рџЏ  Р“Р»Р°РІРЅРѕРµ РјРµРЅСЋ"), start))
    application.add_handler(MessageHandler(filters.Regex("рџ“ќ РўРµСЃС‚"), start_test_msg))
    application.add_handler(MessageHandler(filters.Regex("рџ¤ќ РЎРѕРІРјРµСЃС‚РёРјРѕСЃС‚СЊ"), start_compat_msg))
    application.add_handler(CallbackQueryHandler(start_test_cb, pattern='^start_test$'))
    application.add_handler(CallbackQueryHandler(start_compat_cb, pattern='^start_compat$'))
    application.add_handler(CallbackQueryHandler(restart_test, pattern='^restart_test$'))
    application.add_handler(CallbackQueryHandler(continue_test, pattern='^continue_test$'))
    application.add_handler(CallbackQueryHandler(handle_answer, pattern='^ans_'))
    application.add_handler(CallbackQueryHandler(type_selected_cb, pattern='^(my|partner)_'))
    application.add_handler(CallbackQueryHandler(my_result_cb, pattern='^my_result$'))
    application.add_handler(CallbackQueryHandler(reset_type, pattern='^reset_type$'))
    application.add_handler(CallbackQueryHandler(to_main_cb, pattern='^to_main$'))
    application.add_error_handler(error_handler)

    logger.info("Bot starting...")
    application.run_polling(drop_pending_updates=True, allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()

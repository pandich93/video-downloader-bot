"""Кнопки и тексты меню обработки."""
from __future__ import annotations

from aiogram.filters.callback_data import CallbackData
from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from bot.editor.ffmpeg import RenderResult
from bot.editor.options import (AUDIOS, FRAMES, HOOK_SECONDS, LEVELS, PLATFORMS, STYLES, VARIATIONS,
                                EditOptions, fmt_duration)
from bot.editor.sessions import EditSession
from bot.keyboards import VideoAction

MENU_TEXT = (
    "✂️ Обработка видео\n\n"
    "1️⃣ Уровень оформления:\n"
    "🟢 Чистый — формат 9:16, метаданные, громкость, лёгкая вариация.\n"
    "🟡 Оформленный — + цветовой стиль, логотип, мягкое появление.\n"
    "🟣 Авторский — + текст-хук на первые секунды, ник и полоса прогресса.\n\n"
    "2️⃣ Платформа — запуск. 📦 Все 3 — три файла с разными вариациями.\n"
    "⚙️ Настройки — всё по отдельности."
)
FILE_HINT = (
    "\n\n💡 Видео пришло как «медиа» — Telegram уже сжал его на телефоне. "
    "Для лучшего качества отправляйте файлом: iPhone — 📎 → Файл → Фото или видео; "
    "ПК — перетащите файл и выключите «Сжать»."
)
SETTINGS_TEXT = (
    "⚙️ Настройки обработки\n"
    "Нажимайте на кнопку, чтобы изменить значение, затем «✅ Обработать».\n\n"
    "• Кадр «авто»: вертикальное видео обрезается до 9:16, горизонтальное — на размытом фоне.\n"
    f"• Хук — крупный текст на первые {HOOK_SECONDS} секунды, *слово* в звёздочках — жёлтым.\n"
    "• Ник — NICK из .env, сверху слева. Прогресс — полоса цвета BRAND_COLOR внизу.\n"
    "• Логотип — файл assets/logo.png в папке бота, правый верхний угол.\n"
    "• Вариация: лёгкий случайный зум и цвет — каждый экспорт немного отличается; "
    "«слабая» — вдвое мягче, файлы пакета «Все 3» всегда разные.\n"
    "• ✍️ Тексты ИИ (если подключён OpenRouter): своё название, описание и хэштеги "
    "для каждой платформы по тексту оригинала."
)
FRAGMENT_PROMPT = (
    "✂️ Пришлите фрагмент сообщением:\n"
    "• 0:05-0:40 — с 5-й по 40-ю секунду\n"
    "• 1:10- — с 1:10 до конца\n"
    "• -0:30 — первые 30 секунд\n"
    "• - — всё видео"
)
AUTHORED_HOOK_PROMPT = (
    f"🟣 Для авторского уровня пришлите текст-хук на первые {HOOK_SECONDS} секунды "
    "(до 80 символов) — сразу после этого начну обработку.\n"
    "• Слово в *звёздочках* выделю жёлтым: Как я *заработал* миллион\n"
    "• - — без текста"
)
HOOK_PROMPT = (
    f"💬 Пришлите текст для первых {HOOK_SECONDS} секунд — до 80 символов, перенос строк автоматически.\n"
    "• Слово в *звёздочках* выделю жёлтым: Как я *заработал* миллион\n"
    "• - — убрать текст"
)
EXPIRED_TEXT = "⌛ Сессия устарела — пришлите ссылку или видео заново."


class EditCb(CallbackData, prefix="e"):
    op: str        # preset | batch | settings | toggle | ask | run | menu | close
    key: str       # ключ сессии
    val: str = ""


def menu_kb(s: EditSession) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for lid, name in LEVELS.items():
        mark = "✓ " if s.level == lid else ""
        kb.button(text=mark + name, callback_data=EditCb(op="level", key=s.key, val=lid))
    for pid, (name, _) in PLATFORMS.items():
        kb.button(text=f"📱 {name}", callback_data=EditCb(op="preset", key=s.key, val=pid))
    kb.button(text="📦 Все 3 платформы", callback_data=EditCb(op="batch", key=s.key))
    kb.button(text="⚙️ Настройки", callback_data=EditCb(op="settings", key=s.key))
    if s.link_key:
        kb.button(text="← Назад", callback_data=VideoAction(action="back", key=s.link_key))
    else:
        kb.button(text="✖️ Закрыть", callback_data=EditCb(op="close", key=s.key))
    kb.adjust(3, 3, 1, 1, 1)
    return kb.as_markup()


def settings_kb(s: EditSession, ai_available: bool = False) -> InlineKeyboardMarkup:
    o = s.options
    h = o.hook.replace("*", "")
    hook = f"«{h[:18]}…»" if len(h) > 18 else (f"«{h}»" if h else "нет")
    rows = [
        ("toggle", "platform", f"Платформа: {o.platform_name} (до {fmt_duration(o.max_duration)})"),
        ("toggle", "frame", f"Кадр: {FRAMES[o.frame]}"),
        ("ask", "fragment", f"✂️ Фрагмент: {o.fragment_label}"),
        ("ask", "hook", f"💬 Хук: {hook}"),
        ("toggle", "logo", f"🖼 Логотип: {'вкл' if o.logo else 'выкл'}"),
        ("toggle", "style", f"🎨 Стиль: {STYLES[o.style]}"),
        ("toggle", "fade", f"Появление из чёрного: {'вкл' if o.fade_in else 'выкл'}"),
        ("toggle", "nick", f"Ник: {'вкл' if o.nick else 'выкл'}"),
        ("toggle", "progress", f"Полоса прогресса: {'вкл' if o.progress else 'выкл'}"),
        ("toggle", "speed", f"Скорость: {o.speed:g}×"),
        ("toggle", "var", f"Вариация: {VARIATIONS[o.variation]}"),
        ("toggle", "audio", f"Звук: {AUDIOS[o.audio]}"),
    ]
    if ai_available:
        rows.append(("toggle", "ai", f"✍️ Тексты ИИ: {'вкл' if o.ai_text else 'выкл'}"))
    kb = InlineKeyboardBuilder()
    for op, field, text in rows:
        kb.button(text=text, callback_data=EditCb(op=op, key=s.key, val=field))
    kb.button(text="✅ Обработать", callback_data=EditCb(op="run", key=s.key))
    kb.button(text="← Назад", callback_data=EditCb(op="menu", key=s.key))
    kb.adjust(1)
    return kb.as_markup()


def cancel_kb(s: EditSession) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="✖️ Отмена", callback_data=EditCb(op="settings", key=s.key))
    return kb.as_markup()


def _pct(value: float) -> str:
    return f"{value:+.1f}%".replace("-", "−")


def changes_summary(r: RenderResult, o: EditOptions) -> str:
    """Что бот изменил в видео — простым списком для подписи."""
    items: list[str] = []
    plan, var = r.plan, r.variation
    if plan:
        items.append({"crop": "кадр 9:16 (обрезка)", "blur": "кадр 9:16 (размытый фон)",
                      "original": "формат исходника"}[plan.frame])
    if o.start or o.end is not None:
        items.append(f"фрагмент {o.fragment_label}")
    if plan and plan.cut_to_limit:
        items.append(f"обрезано до {fmt_duration(o.max_duration)} (лимит {o.platform_name})")
    if o.speed != 1:
        items.append(f"скорость {o.speed:g}×")
    if o.style != "none":
        items.append(f"стиль «{STYLES[o.style]}»")
    if o.hook:
        items.append("текст-хук")
    if o.logo:
        items.append("логотип")
    if o.nick:
        items.append("ник")
    if o.progress:
        items.append("полоса прогресса")
    if o.fade_in:
        items.append("мягкое появление")
    if var:
        items.append(f"вариация ({VARIATIONS[var.level]}): зум {_pct((var.zoom - 1) * 100)}, "
                     f"яркость {_pct(var.brightness * 100)}, "
                     f"контраст {_pct((var.contrast - 1) * 100)}, "
                     f"насыщенность {_pct((var.saturation - 1) * 100)}")
    if plan and not plan.audio:
        items.append("без звука")
    elif o.audio == "norm":
        items.append("громкость выровнена")
    items.append("метаданные удалены")
    return "Изменено: " + " · ".join(items)


def result_caption(r: RenderResult, o: EditOptions, details: bool = True) -> str:
    head = (f"{o.platform_name} · {r.width}×{r.height} · {fmt_duration(r.duration)} · "
            f"{r.size / 2**20:.1f} МБ")
    return f"{head}\n{changes_summary(r, o)}" if details else head


def done_text(results: list[tuple[RenderResult, EditOptions]]) -> str:
    if len(results) == 1:
        head = f"✅ Готово: {result_caption(*results[0], details=False)}"
    else:
        head = f"✅ Готово: {len(results)} файла — " + ", ".join(o.platform_name for _, o in results)
    return head + "\n\nМожно сделать ещё вариант — с вариацией каждый файл немного отличается."

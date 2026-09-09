import asyncio
import json
import os
from server import start_server
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Set

from dotenv import load_dotenv

from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
)

from hyperliquid.info import Info
from hyperliquid.utils import constants

from config import WALLETS


# ============================================================
# SETTINGS
# ============================================================

load_dotenv()

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

if not TELEGRAM_BOT_TOKEN:
    raise RuntimeError(
        "TELEGRAM_BOT_TOKEN در فایل .env پیدا نشد."
    )


CHAT_FILE = Path("telegram_chat_id.json")


# ============================================================
# GLOBAL EVENT LOOP
# ============================================================

MAIN_LOOP = None


# ============================================================
# WALLETS
# ============================================================

@dataclass
class Wallet:
    name: str
    address: str


wallets = [
    Wallet(
        name=name,
        address=address.lower().strip()
    )
    for name, address in WALLETS.items()
]


if not wallets:
    raise RuntimeError(
        "هیچ کیف پولی در config.py تعریف نشده."
    )


# ============================================================
# CHAT ID
# ============================================================

def load_chat_id():

    if not CHAT_FILE.exists():
        return None

    try:

        data = json.loads(
            CHAT_FILE.read_text(
                encoding="utf-8"
            )
        )

        return data.get("chat_id")

    except Exception:

        return None


def save_chat_id(chat_id):

    CHAT_FILE.write_text(
        json.dumps(
            {
                "chat_id": chat_id
            },
            indent=2
        ),
        encoding="utf-8"
    )


CHAT_ID = load_chat_id()


# ============================================================
# TELEGRAM
# ============================================================

telegram_app = (
    Application.builder()
    .token(TELEGRAM_BOT_TOKEN)
    .build()
)


# ============================================================
# HYPERLIQUID
# ============================================================

info = Info(
    base_url=constants.MAINNET_API_URL,
    skip_ws=False
)


# ============================================================
# STATE
# ============================================================

positions: Dict[str, float] = {}

seen_fills: Set[str] = set()


# ============================================================
# HELPERS
# ============================================================

def fmt(value, decimals=4):

    try:

        return f"{float(value):,.{decimals}f}"

    except Exception:

        return str(value)


def clean_size(value):

    try:

        value = float(value)

        if abs(value) < 0.000000001:
            return 0.0

        return value

    except Exception:

        return 0.0


def position_key(wallet, coin):

    return (
        f"{wallet.address}:{coin}"
    )


def fill_id(fill):

    return str(
        fill.get("tid")
        or fill.get("hash")
        or fill.get("oid")
        or (
            f"{fill.get('coin')}_"
            f"{fill.get('time')}_"
            f"{fill.get('sz')}_"
            f"{fill.get('px')}_"
            f"{fill.get('side')}"
        )
    )


# ============================================================
# TELEGRAM COMMANDS
# ============================================================

async def start_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    global CHAT_ID

    if not update.effective_chat:
        return

    CHAT_ID = update.effective_chat.id

    save_chat_id(CHAT_ID)

    username = ""

    if update.effective_user:

        if update.effective_user.username:

            username = (
                "@"
                + update.effective_user.username
            )

    wallet_list = "\n".join(
        f"• {wallet.name}"
        for wallet in wallets
    )

    await update.message.reply_text(

        "🟢 <b>Wallet Tracker فعال شد</b>\n\n"

        f"👤 Telegram: "
        f"<b>{username or 'User'}</b>\n"

        f"🆔 Chat ID: "
        f"<code>{CHAT_ID}</code>\n\n"

        f"👛 Wallets:\n"
        f"{wallet_list}\n\n"

        "⚡ آماده دریافت Fill ها هستم.",

        parse_mode="HTML"
    )

    print(
        f"[TELEGRAM] Chat ID saved: {CHAT_ID}"
    )


async def status_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    wallet_list = "\n".join(

        f"• <b>{wallet.name}</b>\n"
        f"  <code>{wallet.address}</code>"

        for wallet in wallets
    )

    await update.message.reply_text(

        "🟢 <b>TRACKER STATUS</b>\n\n"

        f"Chat ID: "
        f"<code>{CHAT_ID or 'Not registered'}</code>\n\n"

        f"{wallet_list}",

        parse_mode="HTML"
    )


telegram_app.add_handler(
    CommandHandler(
        "start",
        start_command
    )
)

telegram_app.add_handler(
    CommandHandler(
        "status",
        status_command
    )
)


# ============================================================
# SEND TELEGRAM
# ============================================================

async def send_telegram(message):

    if CHAT_ID is None:

        print(
            "[TELEGRAM] Chat ID ثبت نشده."
        )

        return

    try:

        await telegram_app.bot.send_message(

            chat_id=CHAT_ID,

            text=message,

            parse_mode="HTML",

            disable_web_page_preview=True
        )

        print(
            "[TELEGRAM] Message sent."
        )

    except Exception as e:

        print(
            "[TELEGRAM ERROR]",
            repr(e)
        )


# ============================================================
# SEND FROM WEBSOCKET THREAD
# ============================================================

def send_from_callback(message):

    """
    Hyperliquid callback ممکن است در Thread دیگری اجرا شود.
    بنابراین ارسال coroutine را به Event Loop اصلی می‌فرستیم.
    """

    global MAIN_LOOP

    if MAIN_LOOP is None:

        print(
            "[ERROR] Main event loop not available."
        )

        return

    try:

        asyncio.run_coroutine_threadsafe(
            send_telegram(message),
            MAIN_LOOP
        )

    except Exception as e:

        print(
            "[SEND ERROR]",
            repr(e)
        )


# ============================================================
# INITIAL POSITIONS
# ============================================================

def load_positions(wallet):

    print(
        f"[INIT] Loading {wallet.name}..."
    )

    try:

        state = info.user_state(
            wallet.address
        )

        for asset in state.get(
            "assetPositions",
            []
        ):

            position = asset.get(
                "position",
                {}
            )

            coin = position.get(
                "coin"
            )

            if not coin:
                continue

            size = clean_size(
                position.get(
                    "szi",
                    0
                )
            )

            positions[
                position_key(
                    wallet,
                    coin
                )
            ] = size

            print(
                f"       {coin}: {size}"
            )

        print(
            f"[INIT] {wallet.name} OK"
        )

    except Exception as e:

        print(
            f"[INIT ERROR] "
            f"{wallet.name}: {e}"
        )


# ============================================================
# BUILD FILL MESSAGE
# ============================================================

def build_message(
    wallet,
    fill,
    before_size,
    after_size
):

    coin = fill.get(
        "coin",
        "UNKNOWN"
    )

    direction = fill.get(
        "dir",
        "UNKNOWN"
    )

    side = fill.get(
        "side",
        "?"
    )

    size = clean_size(
        fill.get(
            "sz",
            0
        )
    )

    price = float(
        fill.get(
            "px",
            0
        )
    )

    closed_pnl = float(
        fill.get(
            "closedPnl",
            0
        )
    )

    # ========================================================
    # CLOSE
    # ========================================================

    if direction in (
        "Close Long",
        "Close Short"
    ):

        if abs(before_size) > 0:

            percent_closed = (
                size /
                abs(before_size)
            ) * 100

        else:

            percent_closed = 0


        if abs(after_size) < 0.000000001:

            title = (
                "🔴 <b>FULL CLOSE</b>"
            )

        else:

            title = (
                "🟠 <b>PARTIAL CLOSE</b>"
            )


        if closed_pnl >= 0:

            pnl_icon = "🟢"

        else:

            pnl_icon = "🔴"


        return (

            f"{title}\n\n"

            f"👤 Wallet: "
            f"<b>{wallet.name}</b>\n"

            f"🪙 Coin: "
            f"<b>{coin}</b>\n\n"

            f"📤 Fill Size: "
            f"<b>{fmt(size)}</b>\n"

            f"📊 Before: "
            f"<b>{fmt(abs(before_size))}</b>\n"

            f"📊 Remaining: "
            f"<b>{fmt(abs(after_size))}</b>\n"

            f"📉 Closed: "
            f"<b>{percent_closed:.2f}%</b>\n\n"

            f"💵 Fill Price: "
            f"<b>${fmt(price, 2)}</b>\n"

            f"{pnl_icon} PnL: "
            f"<b>${fmt(closed_pnl, 2)}</b>\n\n"

            f"⚡ <b>NEW FILL</b>"
        )


    # ========================================================
    # OPEN LONG
    # ========================================================

    if direction == "Open Long":

        return (

            "🟢 <b>OPEN LONG</b>\n\n"

            f"👤 Wallet: "
            f"<b>{wallet.name}</b>\n"

            f"🪙 Coin: "
            f"<b>{coin}</b>\n\n"

            f"📥 Fill Size: "
            f"<b>{fmt(size)}</b>\n"

            f"💵 Fill Price: "
            f"<b>${fmt(price, 2)}</b>\n\n"

            f"📊 Position: "
            f"<b>{fmt(abs(after_size))}</b>\n\n"

            "⚡ <b>NEW FILL</b>"
        )


    # ========================================================
    # OPEN SHORT
    # ========================================================

    if direction == "Open Short":

        return (

            "🔴 <b>OPEN SHORT</b>\n\n"

            f"👤 Wallet: "
            f"<b>{wallet.name}</b>\n"

            f"🪙 Coin: "
            f"<b>{coin}</b>\n\n"

            f"📥 Fill Size: "
            f"<b>{fmt(size)}</b>\n"

            f"💵 Fill Price: "
            f"<b>${fmt(price, 2)}</b>\n\n"

            f"📊 Position: "
            f"<b>{fmt(abs(after_size))}</b>\n\n"

            "⚡ <b>NEW FILL</b>"
        )


    # ========================================================
    # UNKNOWN
    # ========================================================

    return (

        "⚡ <b>NEW FILL</b>\n\n"

        f"👤 Wallet: "
        f"<b>{wallet.name}</b>\n"

        f"🪙 Coin: "
        f"<b>{coin}</b>\n"

        f"📌 Side: "
        f"<b>{side}</b>\n"

        f"📌 Direction: "
        f"<b>{direction}</b>\n\n"

        f"📦 Size: "
        f"<b>{fmt(size)}</b>\n"

        f"💵 Price: "
        f"<b>${fmt(price, 2)}</b>"
    )


# ============================================================
# PROCESS FILL
# ============================================================

def process_fill(
    wallet,
    fill
):

    try:

        current_id = fill_id(
            fill
        )

        # جلوگیری از duplicate
        if current_id in seen_fills:

            return

        seen_fills.add(
            current_id
        )


        coin = fill.get(
            "coin"
        )

        if not coin:

            return


        key = position_key(
            wallet,
            coin
        )


        # ====================================================
        # BEFORE
        # ====================================================

        try:

            before_size = float(
                fill.get(
                    "startPosition",
                    positions.get(
                        key,
                        0
                    )
                )
            )

        except Exception:

            before_size = positions.get(
                key,
                0
            )


        size = clean_size(
            fill.get(
                "sz",
                0
            )
        )


        direction = fill.get(
            "dir",
            ""
        )


        # ====================================================
        # AFTER
        # ====================================================

        if direction == "Open Long":

            after_size = (
                abs(before_size)
                + size
            )


        elif direction == "Open Short":

            after_size = -(
                abs(before_size)
                + size
            )


        elif direction == "Close Long":

            after_size = max(
                0,
                abs(before_size)
                - size
            )


        elif direction == "Close Short":

            after_size = -max(
                0,
                abs(before_size)
                - size
            )


        else:

            if fill.get("side") == "B":

                after_size = (
                    before_size
                    + size
                )

            else:

                after_size = (
                    before_size
                    - size
                )


        # ====================================================
        # SAVE
        # ====================================================

        positions[key] = (
            after_size
        )


        # ====================================================
        # MESSAGE
        # ====================================================

        message = build_message(

            wallet,

            fill,

            before_size,

            after_size
        )


        # ====================================================
        # FAST SEND
        # ====================================================

        send_from_callback(
            message
        )


        print(
            f"[FILL] "
            f"{wallet.name} | "
            f"{coin} | "
            f"{direction} | "
            f"{size} @ "
            f"{fill.get('px')}"
        )

    except Exception as e:

        print(
            "[PROCESS FILL ERROR]",
            repr(e)
        )


# ============================================================
# WEBSOCKET CALLBACK
# ============================================================

def create_callback(wallet):

    def callback(message):

        try:

            data = message.get(
                "data",
                {}
            )

            fills = data.get(
                "fills",
                []
            )

            if not fills:

                return


            for fill in fills:

                process_fill(
                    wallet,
                    fill
                )

        except Exception as e:

            print(
                f"[CALLBACK ERROR] "
                f"{wallet.name}: "
                f"{repr(e)}"
            )

    return callback


# ============================================================
# SUBSCRIBE
# ============================================================

def subscribe_wallet(wallet):

    print()

    print(
        f"[WS] Connecting:"
    )

    print(
        f"     Name: "
        f"{wallet.name}"
    )

    print(
        f"     Address: "
        f"{wallet.address}"
    )


    info.subscribe(

        {
            "type": "userFills",

            "user": wallet.address
        },

        create_callback(
            wallet
        )
    )


    print(
        f"[WS] {wallet.name} subscribed."
    )


# ============================================================
# TELEGRAM START
# ============================================================

async def initialize_telegram():

    await telegram_app.initialize()

    await telegram_app.start()

    await telegram_app.updater.start_polling(
        drop_pending_updates=True
    )

    print(
        "[TELEGRAM] Bot polling started."
    )


# ============================================================
# TELEGRAM STOP
# ============================================================

async def shutdown_telegram():

    try:

        await telegram_app.updater.stop()

    except Exception:
        pass


    try:

        await telegram_app.stop()

    except Exception:
        pass


    try:

        await telegram_app.shutdown()

    except Exception:
        pass


# ============================================================
# MAIN
# ============================================================

async def main():

    global MAIN_LOOP

    # مهم:
    # Event Loop اصلی را ذخیره می‌کنیم
    MAIN_LOOP = asyncio.get_running_loop()


    print()
    print(
        "=" * 70
    )

    print(
        "HYPERLIQUID MULTI WALLET"
    )

    print(
        "LOW-LATENCY FILL TRACKER"
    )

    print(
        "=" * 70
    )

    print()

    print(
        f"Wallet count: "
        f"{len(wallets)}"
    )

    print()


    # ========================================================
    # TELEGRAM
    # ========================================================

    await initialize_telegram()


    # ========================================================
    # INITIAL POSITIONS
    # ========================================================

    for wallet in wallets:

        load_positions(
            wallet
        )


    # ========================================================
    # WEBSOCKET
    # ========================================================

    for wallet in wallets:

        subscribe_wallet(
            wallet
        )


    # ========================================================
    # STARTUP
    # ========================================================

    if CHAT_ID:

        wallet_list = "\n".join(

            f"• <b>{wallet.name}</b>"

            for wallet in wallets
        )


        await send_telegram(

            "🟢 <b>TRACKER ONLINE</b>\n\n"

            "⚡ Low-Latency Fill Monitoring\n\n"

            f"👛 Wallets:\n"
            f"{wallet_list}\n\n"

            "📡 منتظر Fill جدید هستم..."
        )

    else:

        print()

        print(
            "⚠️ Chat ID هنوز ثبت نشده."
        )

        print(
            "در تلگرام وارد بات شو و /start بزن."
        )

        print()


    # ========================================================
    # KEEP ALIVE
    # ========================================================
    await start_server()
    try:

        while True:

            await asyncio.sleep(
                3600
            )

    finally:

        await shutdown_telegram()


# ============================================================
# RUN
# ============================================================

if __name__ == "__main__":

    try:

        asyncio.run(
            main()
        )

    except KeyboardInterrupt:

        print()
        print(
            "Tracker stopped."
        )

    except Exception as e:

        print()
        print(
            "FATAL ERROR:"
        )

        print(
            repr(e)
        )
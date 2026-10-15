import os
import logging
import time
import httpx

from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
)

from strategy import analyze_second_wave

# ---------------- CONFIGURATION ----------------

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
GROUP_ID = os.getenv("TELEGRAM_GROUP_ID", "-1002656806095")

SCAN_INTERVAL = 600
MIN_LIQUIDITY_USD = 5000
MIN_VOLUME_24H_USD = 10000

DEXSCREENER_SEARCH_URL = (
    "https://api.dexscreener.com/latest/dex/search"
)

logging.basicConfig(
    format="%(asctime)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)

logger = logging.getLogger(__name__)

# Temporary in-memory history; resets if the bot restarts.
price_history = {}
alerted_tokens = set()
last_scan_time = None


# ---------------- MARKET DATA ----------------

async def fetch_solana_tokens():
    """Fetch candidate Solana token pairs from DexScreener."""
    query = "solana"
    async with httpx.AsyncClient(timeout=20) as client:
        response = await client.get(
            DEXSCREENER_SEARCH_URL,
            params={"q": query},
        )
        response.raise_for_status()
        data = response.json()

    pairs = data.get("pairs") or []
    candidates = []

    for pair in pairs:
        if pair.get("chainId") != "solana":
            continue

        base = pair.get("baseToken") or {}
        address = base.get("address")
        symbol = base.get("symbol", "UNKNOWN")

        liquidity = (pair.get("liquidity") or {}).get("usd", 0)
        volume = (pair.get("volume") or {}).get("h24", 0)
        price = pair.get("priceUsd")

        try:
            liquidity = float(liquidity or 0)
            volume = float(volume or 0)
            price = float(price or 0)
        except (TypeError, ValueError):
            continue

        if not address or price <= 0:
            continue

        if liquidity < MIN_LIQUIDITY_USD:
            continue

        if volume < MIN_VOLUME_24H_USD:
            continue

        candidates.append({
            "address": address,
            "symbol": symbol,
            "price": price,
            "liquidity": liquidity,
            "volume": volume,
            "url": pair.get("url", ""),
        })

    # Remove duplicate token addresses.
    unique = {}
    for token in candidates:
        unique[token["address"]] = token

    return list(unique.values())


# ---------------- SECOND-WAVE ANALYSIS ----------------

async def scan_market():
    global last_scan_time

    tokens = await fetch_solana_tokens()
    now = time.time()
    alerts = []

    for token in tokens:
        address = token["address"]
        history = price_history.setdefault(address, [])

        history.append({
            "timestamp": now,
            "price": token["price"],
            "volume": token["volume"],
            "buys": 0,
            "sells": 0,
        })

        # Keep the most recent 100 observations.
        price_history[address] = history[-100:]

        analysis = analyze_second_wave(price_history[address])

        if analysis["qualified"] and address not in alerted_tokens:
            alerted_tokens.add(address)

            alerts.append({
                **token,
                "analysis": analysis,
            })

    last_scan_time = time.time()
    return alerts, len(tokens)


def format_alert(token):
    analysis = token["analysis"]

    return (
        "🌊 SECOND-WAVE SETUP DETECTED\n\n"
        f"Token: ${token['symbol']}\n"
        f"Price: ${token['price']:.10f}\n"
        f"Liquidity: ${token['liquidity']:,.0f}\n"
        f"24h Volume: ${token['volume']:,.0f}\n\n"
        f"Initial pump: {analysis['initial_pump_pct']}%\n"
        f"Drawdown: {analysis['drawdown_pct']}%\n"
        f"Recovery: {analysis['recovery_pct']}%\n"
        f"Consolidation: {analysis['consolidation_minutes']} minutes\n"
        f"Opportunity score: {analysis['score']}/100\n\n"
        f"Contract:\n`{token['address']}`\n\n"
        f"Chart: {token['url']}\n\n"
        "⚠️ Research signal only. Not a buy instruction. "
        "Verify liquidity, holders, contract risks, and price action "
        "before making any decision."
    )


# ---------------- TELEGRAM COMMANDS ----------------

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🌊 Second-Wave Strategy Bot\n\n"
        "/scan - Scan the market\n"
        "/status - Check bot status\n"
        "/pnl - View recorded signal information\n"
        "/al <contract> - Analyze a Solana token\n\n"
        "Alerts are research signals, not financial advice."
    )


async def scan_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    await update.message.reply_text("🔎 Scanning Solana token pairs...")

    try:
        alerts, count = await scan_market()

        if not alerts:
            await update.message.reply_text(
                f"Scan complete. Checked {count} candidate tokens. "
                "No qualifying second-wave setup was detected."
            )
            return

        for token in alerts:
            await update.message.reply_text(
                format_alert(token),
                parse_mode="Markdown",
                disable_web_page_preview=True,
            )

    except Exception:
        logger.exception("Manual scan failed")
        await update.message.reply_text(
            "The scan failed. Check the Railway deployment logs."
        )


async def status_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    last_scan = (
        time.strftime(
            "%Y-%m-%d %H:%M:%S UTC",
            time.gmtime(last_scan_time),
        )
        if last_scan_time else "No successful scan yet"
    )

    await update.message.reply_text(
        "🤖 Second-Wave Bot Status\n\n"
        "Process: Running\n"
        f"Tracked tokens this session: {len(price_history)}\n"
        f"Alerts this session: {len(alerted_tokens)}\n"
        f"Last scan: {last_scan}\n"
        f"Scan interval: {SCAN_INTERVAL // 60} minutes"
    )


async def pnl_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    await update.message.reply_text(
        "📊 Signal performance tracking is not implemented yet.\n\n"
        "We need persistent signal records and follow-up price checks "
        "before reporting meaningful PnL."
    )


async def analyze_token_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    if not context.args:
        await update.message.reply_text(
            "Usage: /al <Solana contract address>"
        )
        return

    address = context.args[0].strip()

    try:
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.get(
                f"https://api.dexscreener.com/latest/dex/tokens/{address}"
            )
            response.raise_for_status()
            data = response.json()

        pairs = [
            p for p in (data.get("pairs") or [])
            if p.get("chainId") == "solana"
        ]

        if not pairs:
            await update.message.reply_text(
                "No Solana trading pair was found for that address."
            )
            return

        pair = max(
            pairs,
            key=lambda p: float(
                (p.get("liquidity") or {}).get("usd") or 0
            ),
        )

        base = pair.get("baseToken") or {}
        price = float(pair.get("priceUsd") or 0)
        liquidity = float(
            (pair.get("liquidity") or {}).get("usd") or 0
        )
        volume = float((pair.get("volume") or {}).get("h24") or 0)

        await update.message.reply_text(
            "🔍 TOKEN CHECK\n\n"
            f"Token: ${base.get('symbol', 'UNKNOWN')}\n"
            f"Price: ${price:.10f}\n"
            f"Liquidity: ${liquidity:,.0f}\n"
            f"24h Volume: ${volume:,.0f}\n"
            f"Contract:\n`{address}`\n\n"
            "This is a market-data snapshot, not a full second-wave "
            "qualification. Historical observations are still required.",
            parse_mode="Markdown",
        )

    except Exception:
        logger.exception("Token analysis failed")
        await update.message.reply_text(
            "Unable to retrieve token data. Verify the address and try again."
        )


# ---------------- AUTOMATIC SCANNING ----------------

async def scheduled_scan(context: ContextTypes.DEFAULT_TYPE):
    try:
        alerts, count = await scan_market()

        logger.info("Scheduled scan completed; candidates=%s", count)

        for token in alerts:
            await context.bot.send_message(
                chat_id=GROUP_ID,
                text=format_alert(token),
                parse_mode="Markdown",
                disable_web_page_preview=True,
            )

    except Exception:
        logger.exception("Scheduled scan failed")


async def post_init(application: Application):
    application.job_queue.run_repeating(
        scheduled_scan,
        interval=SCAN_INTERVAL,
        first=15,
        name="second_wave_scan",
    )


def main():
    if not BOT_TOKEN:
        raise RuntimeError(
            "TELEGRAM_BOT_TOKEN is missing from Railway variables."
        )

    application = (
        Application.builder()
        .token(BOT_TOKEN)
        .post_init(post_init)
        .build()
    )

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("scan", scan_command))
    application.add_handler(CommandHandler("status", status_command))
    application.add_handler(CommandHandler("pnl", pnl_command))
    application.add_handler(CommandHandler("al", analyze_token_command))

    logger.info("Starting Second-Wave Strategy Bot")
    application.run_polling()


if __name__ == "__main__":
    main()

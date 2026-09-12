import html
from telethon import Button

from src import db
from src.core.config import *
from src.bot.handlers.context import BotContext
from src.services.queue.manager import queue_manager


class TemplateHelper:
    def __init__(self, ctx: BotContext):
        self.ctx = ctx

    async def get_premium_text_and_buttons(self, user_id: int) -> tuple[str, list[list[Button]]]:
        """Generates the dynamic premium status message for a user."""
        # Base message with premium benefits
        benefits_message = (
            f"<b>Premium Benefits Include:</b>\n\n"
            f"<blockquote><tg-emoji emoji-id='5188481279963715781'>🚀</tg-emoji> <b>Priority Queue:</b> Your requests jump to the front of the line.</blockquote>\n"
            f"<blockquote><tg-emoji emoji-id='5370951118698339120'>✍️</tg-emoji> <b>Custom Pack Details:</b> Set your own custom title and author name for your packs.</blockquote>\n"
            f"<blockquote><tg-emoji emoji-id='5451882707875276247'>⚙️</tg-emoji> <b>Concurrent Conversions:</b> Convert up to {MAX_CONCURRENT_PREMIUM_REQUESTS} packs at once.</blockquote>\n"
            f"<blockquote><tg-emoji emoji-id='6298790803414189709'>♐</tg-emoji> <b>Convert Large Packs:</b> Convert large packs containing more stickers/emojis than usual.</blockquote>\n"
            f"<blockquote><tg-emoji emoji-id='5449683594425410231'>📈</tg-emoji> <b>Higher Daily Limit:</b> Convert up to <b>{DAILY_LIMIT_PREMIUM}</b> packs per day (vs. {DAILY_LIMIT_REGULAR} for regular users).</blockquote>\n"
            f"<blockquote><tg-emoji emoji-id='5443038326535759644'>💬</tg-emoji> <b>Priority Support:</b> Get faster help in the support group.</blockquote>\n"
        )

        duration_left = await db.get_premium_duration_left(user_id)
        
        if duration_left is not None:
            days = duration_left.days
            hours = duration_left.seconds // 3600
            status_message = (
                f"<tg-emoji emoji-id='5967522716062847679'>⭐</tg-emoji> <b>You have an active Premium subscription!</b>\n"
                f"<i>Expires in: {days} days and {hours} hours.</i>\n\n"
            )
            buttons = [
                [Button.inline(f"Extend for 1 Month ({PREMIUM_STARS_MONTHLY} ⭐)", b"extend_premium_30", style="success", icon=5366238787955347845)], 
                [Button.inline(f"Extend for 1 Year ({PREMIUM_STARS_YEARLY} ⭐)", b"extend_premium_365", style="success", icon=5339520934573255920)],
                [Button.inline("Back to Start", b"start", style = None, icon=5258236805890710909), Button.url("Contact Admin", SUPPORT_GROUP_LINK, style=None, icon=5895457880710058528)]
            ]
        else:
            status_message = (
                f"<tg-emoji emoji-id='5472125180799098428'>😕</tg-emoji> <b>You are not a Premium user.</b>\n\n"
                f"<b>Upgrade to unlock great features!</b>\n\n"
                f"<b>Pricing:</b>\n"
                f"  <tg-emoji emoji-id='5954135079662916434'>⭐</tg-emoji><b>{PREMIUM_STARS_MONTHLY}</b> or <b>${PREMIUM_PRICE_MONTHLY}</b> / month\n"
                f"  <tg-emoji emoji-id='5954135079662916434'>⭐</tg-emoji><b>{PREMIUM_STARS_YEARLY}</b> or <b>${PREMIUM_PRICE_YEARLY}</b> / year (<i>Save over {PREMIUM_SAVINGS_PERCENT}%</i>)\n\n"
                f"<tg-emoji emoji-id='5337239271851960809'>✉️</tg-emoji> If you need to pay with other payment methods, contact us using <b>/contact</b> command or at <b>{SUPPORT_GROUP}</b>.\n\n"
            )
            buttons = [
                [Button.inline(f"Buy 1 Month ({PREMIUM_STARS_MONTHLY} ⭐)", b"buy_premium_30", style="success", icon=5366238787955347845)], 
                [Button.inline(f"Buy 1 Year ({PREMIUM_STARS_YEARLY} ⭐)", b"buy_premium_365", style="success", icon=5339520934573255920)],
                [Button.inline("Back to Start", b"start", style = None, icon=5258236805890710909), Button.url("Contact Admin", SUPPORT_GROUP_LINK, style=None, icon=5895457880710058528)]
        ]

        
        return status_message + benefits_message, buttons

    def format_suggestion_message(self, list_type: str) -> tuple[str, list]:
        """Helper to generate the message text and buttons for suggestions."""
        packs = self.ctx.daily_popular_packs if list_type == 'daily' else self.ctx.all_time_popular_packs
        
        if list_type == 'daily':
            title = "<tg-emoji emoji-id='5251537301154062376'>📅</tg-emoji> <b>Top 10 Popular Packs (Daily)</b>"
            button = [Button.inline("View All-Time Top 50", b"suggest_all_time", style="primary", icon=5244590801438138696)]
        else: # all_time
            title = "<tg-emoji emoji-id='5244590801438138696'>🏆</tg-emoji> <b>Top 50 Popular Packs (All-Time)</b>"
            button = [Button.inline("View Daily Top 10", b"suggest_daily", style="primary", icon=5251537301154062376)]
        
        if not packs:
            message = f"{title}\n\n" \
                      "Hmm, I don't have any data for this yet.\n " \
                      "Check back tomorrow after more packs have been converted! <tg-emoji emoji-id='5240426590126490125'>😊</tg-emoji>"
        else:
            pack_list = []
            for i, pack in enumerate(packs, 1):
                safe_title = html.escape(pack['pack_title'])
                pack_list.append(f"{i}. <a href='{pack['pack_url']}'>{safe_title}</a>")
            
            message = f"{title}\n\n<b>{"\n".join(pack_list)}</b>"
        
        return message, [button]

    async def get_gstats_message_and_buttons(self) -> tuple[str, list]:
        """Helper to generate the main /gstats message and buttons."""
        stats = await db.get_gstats()
        q_stats = await queue_manager.get_queue_stats()

        processing_user = q_stats['processing_user'] or "None"

        message = (
            f"<tg-emoji emoji-id='5431577498364158238'>📊</tg-emoji> <b>Global Bot Statistics                            </b>\n\n"
            f"<tg-emoji emoji-id='5879770735999717115'>👤</tg-emoji> <b>Users</b>\n"
            f"<blockquote>"
            f"  • Total Users: <code>{stats['total_users']}</code>\n"
            f"  • Admins: <code>{stats['total_admins']}</code>\n"
            f"  • Active Premium: <code>{stats['active_premium']}</code>\n"
            f"  • Banned Users: <code>{stats['total_banned']}</code>\n"
            f"</blockquote>\n"
            f"<tg-emoji emoji-id='6030537810509828330'>⚙️</tg-emoji> <b>Overall Stats</b>\n"
            f"<blockquote>"
            f"    <tg-emoji emoji-id='5260416304224936047'>✅</tg-emoji> Succeeded: <code>{stats['total_succeeded']}</code>\n"
            f"    <tg-emoji emoji-id='5260342697075416641'>❌</tg-emoji> Failed: <code>{stats['total_failed']}</code>\n"
            f"    <tg-emoji emoji-id='5258318620722733379'>🚫</tg-emoji> Cancelled: <code>{stats['total_cancelled']}</code>\n"
            f"</blockquote>\n"
            f"<tg-emoji emoji-id='5890937706803894250'>📅</tg-emoji> <b>Today's Stats</b>\n"
            f"<blockquote>"
            f"    <tg-emoji emoji-id='5260416304224936047'>✅</tg-emoji> Succeeded: <code>{stats['today_succeeded']}</code>\n"
            f"    <tg-emoji emoji-id='5260342697075416641'>❌</tg-emoji> Failed: <code>{stats['today_failed']}</code>\n"
            f"    <tg-emoji emoji-id='5258318620722733379'>🚫</tg-emoji> Cancelled: <code>{stats['today_cancelled']}</code>\n"
            f"</blockquote>\n"
            f"<tg-emoji emoji-id='5208429100951159058'>🔴</tg-emoji> <b>Live Queue Status</b>\n"
            f"<blockquote>"
            f"  • Waiting: <code>{q_stats['total_waiting']}</code>\n"
            f"  • Currently Processing: <b>{processing_user}</b>"
            f"</blockquote>"
        )

        buttons = [
            [Button.inline("Premium Users", b"gstats_premium", icon=5807868868886009920), Button.inline("Top 50 Users", b"gstats_top_users", icon=6030861234432121355)],
            [Button.inline("Admins List", b"gstats_admins", icon=5778423822940114949), Button.inline("Banned List", b"gstats_banned", icon=5872829476143894491)],
            [Button.inline("Refresh", b"gstats_refresh", icon=5877410604225924969)]
        ]
        return message, buttons

    def create_channel_join_buttons(self) -> list:
        """Dynamically creates buttons for channels and groups."""
        keyboard = []
        # iterate through the list of tuples from config.py
        for i in range(0, len(REQUIRED_CHANNELS_FORMATTED), 2):
            row = []

            # First Button in Row
            name1, link1 = REQUIRED_CHANNELS_FORMATTED[i][1:3]
            row.append(Button.url(f"{name1}", url=link1, style="primary", icon=None))

            # Second Button in Row (if it exists)
            if i + 1 < len(REQUIRED_CHANNELS_FORMATTED):
                name2, link2 = REQUIRED_CHANNELS_FORMATTED[i+1][1:3]
                row.append(Button.url(f"{name2}", url=link2, style="primary", icon=None))
            
            keyboard.append(row)
        
        keyboard.append([Button.inline("Check Again", b"check_membership", style="success", icon=5258200019495821936)])
        return keyboard

    def create_post_conversion_buttons(self) -> list:
        """Creates buttons for contacting support."""
        return [
            [Button.inline("How to Import?", b"help_import", style = None, icon=5818947586702184246)], 
            [Button.inline("Report an Issue", b"contact", style = None, icon=5895457880710058528)]
        ]
import logging
from telethon import events, Button
from telethon.events import StopPropagation
from telethon.tl.types import MessageEntityCustomEmoji

from src import db
from src.core.config import *
from src.bot.handlers.helper import check_banned, update_user_info, send_rich_message
from src.bot.handlers.context import BotContext
from src.services.queue.manager import queue_manager
from src.services.sessions.manager import Flow, session_manager

logger = logging.getLogger(__name__)

class UserCommands:
    def __init__(self, ctx: BotContext):
        self.ctx = ctx


    @check_banned
    @update_user_info
    async def start_command(self, event: events.NewMessage.Event):
        """Handle /start command."""
        user = await event.get_sender()
        # Check for deep linking arguments
        args = event.raw_text.split()
        if len(args) > 1:
            parameter = args[1].lower().strip()
            
            # Dispatch to appropriate handlers based on the parameter
            if parameter == 'queue':
                return await self.queue_command(event)
            elif parameter == 'mystats':
                return await self.mystats_command(event)
            elif parameter == 'premium':
                return await self.premium_command(event)
            elif parameter == 'commands':
                return await self.commands_command(event)
            elif parameter == 'contact':
                return await self.contact_command(event)
            elif parameter == 'suggest':
                return await self.suggest_command(event)
            elif parameter == 'help':
                return await self.help_command(event)
            elif parameter in ('src', 'source'):
                return await self.src_command(event)
        
        await event.reply(self.ctx.START_MESSAGE, buttons=self.ctx.START_BUTTONS, link_preview=False, parse_mode='html')
        raise StopPropagation

    @check_banned
    @update_user_info
    async def help_command(self, event: events.NewMessage.Event):
        """Handle /help command."""
        if event.is_private:
            buttons = [
                [Button.inline("Back to Start", b"start", style = None, icon=5258236805890710909), Button.inline("Commands", b"commands", style = None, icon=5787544344906959608)]
            ]
        else:
            deep_link = f"https://t.me/{self.ctx.bot_info.username}?start=start"
            buttons = [
                [Button.url("Get Started", deep_link, style="primary", icon=5793933761594789855)]
            ]

        await send_rich_message(self.ctx.client, event.chat_id, HELP_MESSAGE_RICH, HELP_MESSAGE_FALLBACK, buttons=buttons, reply_to=event.id, link_preview=False)
        raise StopPropagation

    @check_banned
    @update_user_info
    async def mystats_command(self, event: events.NewMessage.Event):
        """Displays the user's current status and conversion stats."""
        user = await event.get_sender()
        is_premium = await db.is_premium(user.id)
        
        # user role
        role = "Regular User <tg-emoji emoji-id='5316727448644103237'>👤</tg-emoji>"
        if db.is_owner(user.id):
            role = "Owner <tg-emoji emoji-id='5433758796289685818'>👑</tg-emoji>"
        elif await db.is_admin(user.id):
            role = "Admin <tg-emoji emoji-id='5854973145315806460'>👮</tg-emoji>"
        elif is_premium:
            role = "Premium User <tg-emoji emoji-id='5967522716062847679'>⭐</tg-emoji>"
            duration_left = await db.get_premium_duration_left(user.id)
            if duration_left:
                days = duration_left.days
                hours = duration_left.seconds // 3600
                minutes = (duration_left.seconds % 3600) // 60
                role += f"\n<b>Expires in</b>: {days}d {hours}h {minutes}m <tg-emoji emoji-id='5258258882022612173'>⏳</tg-emoji>"
            
        # get conversion stats
        stats = await db.get_user_stats(user.id)
        daily_usage = await db.get_daily_usage(user.id)
        daily_limit = DAILY_LIMIT_PREMIUM if is_premium else DAILY_LIMIT_REGULAR
        limit_str = f"{daily_usage}/{daily_limit}" if daily_limit > 0 else "Unlimited"
        
        message = (
            f"<tg-emoji emoji-id='5431577498364158238'>📊</tg-emoji> <b>Your Stats</b>\n\n"
            f"<b>Status:</b> {role}\n"
            f"<b>Today's Usage:</b> {limit_str}\n\n"
            f"<b>Conversion Stats:</b>\n"
            f"<blockquote>"
            f"<tg-emoji emoji-id='5260416304224936047'>✅</tg-emoji> Succeeded: {stats['succeeded']}       \n"
            f"<tg-emoji emoji-id='5260342697075416641'>❌</tg-emoji> Failed: {stats['failed']}       \n"
            f"<tg-emoji emoji-id='5258318620722733379'>🚫</tg-emoji> Cancelled: {stats['cancelled']}       "
            f"</blockquote>"
        )
        
        await event.reply(message, parse_mode='html')
        logger.info(f"User {user.id} has fetched their stats.")
        raise StopPropagation

    @check_banned
    @update_user_info
    async def premium_command(self, event: events.NewMessage.Event):
        """Displays the user's premium status and benefits."""
        user = await event.get_sender()
        message_text, buttons = await self.ctx.templates.get_premium_text_and_buttons(user.id)

        await event.reply(message_text, buttons=buttons, parse_mode='html', link_preview=False)
        raise StopPropagation

    async def show_queue_status(self, event: events.CallbackQuery.Event | events.NewMessage.Event, user_id: int, mode: str):
        """Shows the queue status to the user."""
        position = await queue_manager.get_queue_position(user_id)
        stats = await queue_manager.get_queue_stats()
        total = stats["total_waiting"] + (1 if stats["currently_processing"] else 0)

        if position == -1: # user is processing
            message = "<tg-emoji emoji-id='5188481279963715781'>🚀</tg-emoji> Your pack is currently being processed! It should be ready soon."
            buttons = [[Button.inline("Refresh", b"check_queue", style = None, icon=5260687119092817530)]]
        elif position > 0: # in queue
            message = QUEUE_CHECK_MESSAGE.format(
                position=position,
                total=total
            )
            buttons = [[Button.inline("Refresh", b"check_queue", style = None, icon=5260687119092817530)]]
        else: # not in the queue
            message = f"<tg-emoji emoji-id='5305381957524272531'>📊</tg-emoji> You're not in the queue.\nTotal in queue: {total}."
            buttons = [
                [Button.inline("Refresh", b"check_queue", style = None, icon=5260687119092817530)],
                [Button.inline("Back to Start", b"start", style = None, icon=5258236805890710909)]
            ]
        
        if mode == "callback":
            await event.edit(message, buttons=buttons, parse_mode='html')
        else:
            await event.reply(message, buttons=buttons, parse_mode='html')

    @check_banned
    @update_user_info
    async def queue_command(self, event: events.NewMessage.Event):
        """Command to check user's position."""
        user = await event.get_sender()
        await self.show_queue_status(event, user.id, mode="message")
        raise StopPropagation
    
    @check_banned
    @update_user_info
    async def commands_command(self, event: events.NewMessage.Event):
        """Handles the /commands command."""
        buttons = [
            [Button.inline("Back to Start", b"start", style = None, icon=5258236805890710909), Button.inline("Help", b"help", style = None, icon=5818947586702184246)]
        ]
        await event.reply(COMMANDS_MESSAGE, buttons=buttons, parse_mode='html')
        raise StopPropagation

    @check_banned
    @update_user_info
    async def suggest_command(self, event: events.NewMessage.Event):
        """Handles the /suggest command."""
        message, buttons = self.ctx.templates.format_suggestion_message('daily')
        await event.reply(message, buttons=buttons, parse_mode='html', link_preview=False)
        raise StopPropagation

    async def show_contact_prompt(self, event: events.CallbackQuery.Event | events.NewMessage.Event, user_id: int, mode: str):
        """Shows the contact prompt to the user."""
        session = await session_manager.create(
            user_id=user_id,
            flow=Flow.CONTACT,
            state="awaiting_confirmation",
            ttl_seconds=3600, # Session expires in 1 hour
            single_active=True
        )

        buttons = [
            [Button.inline("Send Message", f"contact_send_{session.session_id}", style="success", icon=5253742260054409879), 
            Button.inline("Cancel", f"contact_cancel_{session.session_id}", style="danger", icon=5465665476971471368)],
            [Button.url("Support Group", SUPPORT_GROUP_LINK, style=None, icon=5443038326535759644)]
        ]
        if mode == "callback":
            await event.edit(CONTACT_PROMPT_MESSAGE, buttons=buttons, link_preview=False, parse_mode='html')
        else:
            await event.reply(CONTACT_PROMPT_MESSAGE, buttons=buttons, link_preview=False, parse_mode='html')

    @check_banned
    @update_user_info
    async def contact_command(self, event: events.NewMessage.Event):
        """Handles the /contact command, prompting the user to send a message."""
        user = await event.get_sender()

        await self.show_contact_prompt(event, user.id, mode="message")
        raise StopPropagation

    @check_banned
    @update_user_info
    async def id_command(self, event: events.NewMessage.Event):
        """User command to get IDs of custom emojis sent in the message."""
        if not getattr(event.message, 'entities', None):
            await event.reply("No custom emojis found in the message.")
            raise StopPropagation

        emoji_list = []
        
        for entity, item_text in event.message.get_entities_text():
            if isinstance(entity, MessageEntityCustomEmoji):
                emoji_list.append(f"<tg-emoji emoji-id='{entity.document_id}'>{item_text}</tg-emoji>  :  <code>{entity.document_id}</code>")
        
        if not emoji_list:
            await event.reply("<tg-emoji emoji-id='5852812849780362931'>❌️</tg-emoji> No custom emojis found in the message.", parse_mode='html')
            raise StopPropagation
            
        await event.reply("\n".join(emoji_list), parse_mode='html')
        raise StopPropagation

    @check_banned
    @update_user_info
    async def src_command(self, event: events.NewMessage.Event):
        """Shows the github link for the source code of the bot and its modules."""
        message = (
            "Yes, the bot is open source for the community!\n\n"
            "<tg-emoji emoji-id='5933540612694347912'>🔗</tg-emoji> If you are a developer and want to contribute or host your own bot, you can find the source code here:\n"
            f"<blockquote>{SOURCE_CODE_LINK}</blockquote>\n\n"
            "And if you are only looking for the core conversion modules for your own project:\n"
            f"• <b><a href='{TGS_TO_WEBP_MODULE_LINK}'>Tgs-to-Webp</a></b>: Converts <code>.tgs</code> files to Webp with various tweakable settings.\n"
            f"• <b><a href='{VIDEO_TO_WEBP_MODULE_LINK}'>Video-to-Webp</a></b>: Converts video files (like <code>.webm/.mp4/.mkv/.mov/.gif</code>, etc.) to Webp with various tweakable settings."
            "\n\n"
            "Liked the bot? Mind dropping us a quick star on GitHub? <tg-emoji emoji-id='5238181859828974653'>🙏</tg-emoji>"
        )
        buttons = [
            [Button.url("Bot Source Code", SOURCE_CODE_LINK, style='primary')],
            [Button.url("Tgs-to-Webp", TGS_TO_WEBP_MODULE_LINK, style=None), Button.url("Video-to-Webp", VIDEO_TO_WEBP_MODULE_LINK, style=None)]
        ]
        await event.reply(message, buttons=buttons, parse_mode='html', link_preview=False)
        raise StopPropagation
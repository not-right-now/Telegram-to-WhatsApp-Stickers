"""
Module containing various handlers for interaction with the bot.
"""

import os 
import time
import json
import asyncio
import logging
import re
import html
import math
from datetime import datetime, timezone
from telethon import TelegramClient, events, Button
from telethon.errors import UserIsBlockedError
from telethon.events import StopPropagation
from telethon.tl.types import DocumentAttributeSticker, Message
from telethon.extensions import html as telethon_html
from typing import Optional, TYPE_CHECKING

from src import db
from src.core.config import *
from src.core.exceptions import *
from src.utils.parsers import *
from src.utils.formatters import *
from src.utils.file_helpers import *
from src.utils.network_tasks import NetworkTask
from src.bot.handlers.bg_task import BackGroundTask
from src.bot.handlers.helper import HelperMethods, check_banned, estimate_wait_time, update_user_info, send_rich_message, edit_rich_message
from src.bot.handlers.template import TemplateHelper
from src.bot.handlers.session import SessionHandler
from src.bot.handlers.user import UserCommands
from src.bot.handlers.owner import OwnerCommands
from src.bot.handlers.admin import AdminCommands
from src.bot.handlers.context import BotContext
from src.services.queue.manager import queue_manager, SYSTEM_PRIORITY, REGULAR_USER_PRIORITY, PREMIUM_USER_PRIORITY
from src.services.converters.manager import StickerConverter
from src.services.sessions.manager import session_manager, Flow, Session
from src.services.payments.manager import PaymentManager
from src.services.backups.manager import BackupManager
from src.services.lifecycle.manager import LifecycleManager

if TYPE_CHECKING:
    from src.services.ha.manager import HighAvailabilityManager
    from src.services.notifications.manager import NotificationManager
    
logger = logging.getLogger(__name__)



class BotHandlers:
    def __init__(self, client: TelegramClient, bot_info, notification_manager: 'NotificationManager', ha_manager: 'HighAvailabilityManager'):
        """
        Initializes the bot handlers with the Telethon client and other necessary components.
        """
        ensure_directories()
        
        self.ctx = BotContext(
            client=client,
            notification_manager=notification_manager,
            ha_manager=ha_manager,
            payment_manager=PaymentManager(client, notification_manager),
            converter=StickerConverter(client),
            network_task=NetworkTask(client),
            backup_manager=BackupManager(client),
            bot_info=bot_info,
            bot_username=f"@{bot_info.username}",
            cache_enabled=CACHE_ENABLED,
            START_MESSAGE=START_MESSAGE_FORMAT.format(bot_username=bot_info.username, bot_name=bot_info.first_name),
            START_BUTTONS = [
            [Button.inline("Premium", b"premium", style="danger", icon=5967522716062847679), Button.inline("Help", b"help", style="success", icon=5818947586702184246)],
            [Button.url("Support Group", SUPPORT_GROUP_LINK, style="primary", icon=5895457880710058528), Button.inline("Commands", b"commands", style="primary", icon=5787544344906959608)]
        ]
        )
        # module instances they share same ctx
        self.lc_manager = LifecycleManager(self.ctx)
        self.admin = AdminCommands(self.ctx)
        self.owner = OwnerCommands(self.ctx)
        self.user = UserCommands(self.ctx)
        self.sessions = SessionHandler(self.ctx)
        self.templates = TemplateHelper(self.ctx)
        self.helpers = HelperMethods(self.ctx)

        # set references in ctx
        self.ctx.lc_manager = self.lc_manager
        self.ctx.core = self
        self.ctx.admin = self.admin
        self.ctx.owner = self.owner
        self.ctx.user = self.user
        self.ctx.sessions = self.sessions
        self.ctx.templates = self.templates
        self.ctx.helpers = self.helpers

        #background tasks for cleanup
        self.bg_task = BackGroundTask(self.ctx)
        self.bg_task.start()
        

    def register_handlers(self):
        """
        Registers all event handlers with the Telethon client.
        """
        username_regex = self.ctx.bot_username.lstrip('@')

        # register payment handlers
        self.ctx.payment_manager.register_handlers()
        
        # user commands (Private)
        self.ctx.client.add_event_handler(self.user.start_command, events.NewMessage(pattern='/start', func=lambda e: e.is_private))
        self.ctx.client.add_event_handler(self.user.help_command, events.NewMessage(pattern='/help', func=lambda e: e.is_private))
        self.ctx.client.add_event_handler(self.user.queue_command, events.NewMessage(pattern='/queue', func=lambda e: e.is_private))
        self.ctx.client.add_event_handler(self.user.mystats_command, events.NewMessage(pattern='/mystats', func=lambda e: e.is_private))
        self.ctx.client.add_event_handler(self.user.premium_command, events.NewMessage(pattern='/premium', func=lambda e: e.is_private))
        self.ctx.client.add_event_handler(self.user.commands_command, events.NewMessage(pattern='/commands', func=lambda e: e.is_private))
        self.ctx.client.add_event_handler(self.user.contact_command, events.NewMessage(pattern='/contact', func=lambda e: e.is_private))
        self.ctx.client.add_event_handler(self.user.suggest_command, events.NewMessage(pattern='/suggest', func=lambda e: e.is_private))
        self.ctx.client.add_event_handler(self.user.id_command, events.NewMessage(pattern=r'/id(?:$|\s.*)', func=lambda e: e.is_private))
        self.ctx.client.add_event_handler(self.user.src_command, events.NewMessage(pattern=r'/(?:src|source)(?:$|\s.*)', func=lambda e: e.is_private))

        # Group Handlers
        # self.ctx.client.add_event_handler(self.user.suggest_command, events.NewMessage(pattern='/suggest@'+ username_regex + r'(?:$|\s.*)', func=lambda e: not e.is_private))
        self.ctx.client.add_event_handler(self.user.help_command, events.NewMessage(pattern='/help@'+ username_regex + r'(?:$|\s.*)', func=lambda e: not e.is_private))

        # Restricted commands in groups (Redirect to DM)
        restricted_cmds = ['start', 'queue', 'mystats', 'premium', 'commands', 'suggest', 'contact']
        for cmd in restricted_cmds:
            self.ctx.client.add_event_handler(self.restricted_command_handler, events.NewMessage(pattern=rf"/{cmd}@{username_regex}(?:$|\s.*)", func=lambda e: not e.is_private))

        # owner commands
        self.ctx.client.add_event_handler(self.owner.promote_command, events.NewMessage(pattern=r'/promote(?:@\w+)?(?:\s+([@\w\d]+))?', func=lambda e: e.is_private and db.is_owner(e.sender_id)))
        self.ctx.client.add_event_handler(self.owner.demote_command, events.NewMessage(pattern=r'/demote(?:@\w+)?(?:\s+([@\w\d]+))?', func=lambda e: e.is_private and db.is_owner(e.sender_id)))
        self.ctx.client.add_event_handler(self.owner.broadcast_command, events.NewMessage(pattern=r'/broadcast(?:$|\s.*)', func=lambda e: e.is_private and db.is_owner(e.sender_id)))
        self.ctx.client.add_event_handler(self.owner.broadcast_command, events.NewMessage(pattern=r'/broadcast@' + username_regex + r'(?:$|\s.*)', func=lambda e: not e.is_private and db.is_owner(e.sender_id)))
        self.ctx.client.add_event_handler(self.owner.send_command, events.NewMessage(pattern=r'/send(?:$|\s.*)', func=lambda e: e.is_private and db.is_owner(e.sender_id)))
        self.ctx.client.add_event_handler(self.owner.gstats_command, events.NewMessage(pattern=r'/gstats', func=lambda e: db.is_owner(e.sender_id)))
        self.ctx.client.add_event_handler(self.owner.getdb_command, events.NewMessage(pattern='/getdb', func=lambda e: e.is_private and db.is_owner(e.sender_id)))
        self.ctx.client.add_event_handler(self.owner.getlogs_command, events.NewMessage(pattern='/getlogs', func=lambda e: e.is_private and db.is_owner(e.sender_id)))
        self.ctx.client.add_event_handler(self.owner.toggle_cache_command, events.NewMessage(pattern='/togglecache', func=lambda e: e.is_private and db.is_owner(e.sender_id)))
        self.ctx.client.add_event_handler(self.owner.clearcache_command, events.NewMessage(pattern=r'/clearcache', func=lambda e: e.is_private and db.is_owner(e.sender_id)))
        self.ctx.client.add_event_handler(self.owner.refreshcache_command, events.NewMessage(pattern=r'/refreshcache', func=lambda e: e.is_private and db.is_owner(e.sender_id)))
        self.ctx.client.add_event_handler(self.owner.cancelrefresh_command, events.NewMessage(pattern=r'/cancelrefresh', func=lambda e: e.is_private and db.is_owner(e.sender_id)))
        self.ctx.client.add_event_handler(self.owner.addcache_command, events.NewMessage(pattern=r'/addcache', func=lambda e: e.is_private and db.is_owner(e.sender_id)))
        self.ctx.client.add_event_handler(self.owner.canceladdcache_command, events.NewMessage(pattern=r'/canceladdcache', func=lambda e: e.is_private and db.is_owner(e.sender_id)))
        self.ctx.client.add_event_handler(self.owner.done_command, events.NewMessage(pattern=r'/done', func=lambda e: e.is_private and db.is_owner(e.sender_id)))
        self.ctx.client.add_event_handler(self.owner.getjunk_command, events.NewMessage(pattern='/getjunk', func=lambda e: e.is_private and db.is_owner(e.sender_id)))
        self.ctx.client.add_event_handler(self.owner.clearjunk_command, events.NewMessage(pattern='/clearjunk', func=lambda e: e.is_private and db.is_owner(e.sender_id)))
        self.ctx.client.add_event_handler(self.owner.refund_command, events.NewMessage(pattern=r'/refund(?:@\w+)?(?:\s+([@\w\d]+))?', func=lambda e: e.is_private and db.is_owner(e.sender_id)))
        self.ctx.client.add_event_handler(self.owner.shutdown_command, events.NewMessage(pattern=r'/shutdown(?:$|\s.*)', func=lambda e: e.is_private and db.is_owner(e.sender_id)))
        self.ctx.client.add_event_handler(self.owner.restart_command, events.NewMessage(pattern=r'/restart(?:$|\s.*)', func=lambda e: e.is_private and db.is_owner(e.sender_id)))

        # Premium commands (admin use)
        self.ctx.client.add_event_handler(self.admin.add_premium_command, events.NewMessage(pattern=r'/addpremium(?:@\w+)?(?:\s+([@\w\d]+))?(?:\s+(\d+))?', func=lambda e: e.is_private))
        self.ctx.client.add_event_handler(self.admin.remove_premium_command, events.NewMessage(pattern=r'/removepremium(?:@\w+)?(?:\s+([@\w\d]+))?', func=lambda e: e.is_private))
        self.ctx.client.add_event_handler(self.admin.extend_premium_command, events.NewMessage(pattern=r'/extendpremium(?:@\w+)?(?:\s+([@\w\d]+))?(?:\s+(\d+))?', func=lambda e: e.is_private))
        self.ctx.client.add_event_handler(self.admin.deduct_premium_command, events.NewMessage(pattern=r'/deductpremium(?:@\w+)?(?:\s+([@\w\d]+))?(?:\s+(\d+))?', func=lambda e: e.is_private))
        self.ctx.client.add_event_handler(self.admin.getstats_command, events.NewMessage(pattern=r'/getstats(?:@\w+)?(?:\s+([@\w\d]+))?', func=lambda e: e.is_private))
        # ban/unban (admin use)
        self.ctx.client.add_event_handler(self.admin.ban_command, events.NewMessage(pattern=r'/ban', func=lambda e: e.is_private))
        self.ctx.client.add_event_handler(self.admin.sban_command, events.NewMessage(pattern=r'/sban', func=lambda e: e.is_private))
        self.ctx.client.add_event_handler(self.admin.unban_command, events.NewMessage(pattern=r'/unban', func=lambda e: e.is_private))

        # Handle all other private messages
        self.ctx.client.add_event_handler(self.handle_message, events.NewMessage(func=lambda e: e.is_private and (not e.text.startswith('/') )))
        self.ctx.client.add_event_handler(self.handle_callback_query, events.CallbackQuery())

    async def restricted_command_handler(self, event: events.NewMessage.Event):
        """
        Handles commands in groups by directing the user to DM.
        """
        # Extract the command, e.g., '/queue'
        text = event.raw_text.split()[0].split('@')[0]
        command = text.lstrip('/')
        
        bot_username_simple = self.ctx.bot_username.lstrip('@')
        deep_link = f"https://t.me/{bot_username_simple}?start={command}"
        message = ""
        match command:
            case 'start':
                message = "<tg-emoji emoji-id='5413694143601842851'>👋</tg-emoji> Hey there, I'm here to help you convert Telegram stickers and emoji packs to WhatsApp stickers!\n\nClick the button below to get started."
                buttons = [
                    [Button.url("Get Started", deep_link, style="primary", icon=5793933761594789855)]
                ]
            case 'queue':
                message = "<tg-emoji emoji-id='5255772095958229697'>❌</tg-emoji> This command is not available in groups.\n\nPlease click the button below to see your queue position in private chat."
                buttons = [
                    [Button.url("Get Queue Position", deep_link, style="primary", icon=5258513401784573443)]
                ]
            case 'mystats':
                message = "<tg-emoji emoji-id='5255772095958229697'>❌</tg-emoji> This command is not available in groups.\n\nPlease click the button below to see your stats in private chat."
                buttons = [
                    [Button.url("Get My Stats", deep_link, style="primary", icon=5431577498364158238)]
                ]
            case 'premium':
                message = "<tg-emoji emoji-id='5255772095958229697'>❌</tg-emoji> This command is not available in groups.\n\nPlease click the button below to see premium info in private chat."
                buttons = [
                    [Button.url("Premium Info", deep_link, style="primary", icon=5967522716062847679)]
                ]
            case 'commands':
                message = "<tg-emoji emoji-id='5255772095958229697'>❌</tg-emoji> This command is not available in groups.\n\nPlease click the button below to see available commands in private chat."
                buttons = [
                    [Button.url("Available Commands", deep_link, style="primary", icon=5787544344906959608)]
                ]
            case 'contact':
                message = "<tg-emoji emoji-id='5255772095958229697'>❌</tg-emoji> This command is not available in groups.\n\nPlease click the button below to use it in private chat."
                buttons = [
                    [Button.url("Contact", deep_link, style="primary", icon=5895457880710058528)]
                ]
            case 'suggest':
                message = "<tg-emoji emoji-id='5255772095958229697'>❌</tg-emoji> This command is not available in groups.\n\nPlease click the button below to see the most popular sticker packs in private chat."
                buttons = [
                    [Button.url("Most Popular Sticker Packs", deep_link, style="primary", icon=6284845886417669247)]
                ]
            case _:
                message = "<tg-emoji emoji-id='5255772095958229697'>❌</tg-emoji> This command is not available in groups.\n\nPlease click the button below to use it in private chat."
                buttons = [
                    [Button.url("Continue in DM", deep_link, style="primary", icon=5793933761594789855)]
                ]
        
        await event.reply(message, buttons=buttons, parse_mode="html")

        raise StopPropagation

    async def _start_customization_flow(self, event_info: dict, sticker_set_info: dict):
        """Sends the initial customization prompt to premium users."""
        user_id = event_info['user_id']
        payload = {
            "sticker_set_info": sticker_set_info,
            "original_event_info": event_info,
            "prompt_message_id": None,
            "custom_title": None,
            "custom_author": None,
            "failed_inputs": []
        }
        session = await session_manager.create(
            user_id=user_id,
            flow=Flow.CUSTOMIZE,
            state="awaiting_customization_choice",
            payload=payload,
            ttl_seconds=3600 # 1 hour to decide
        )
        await self.helpers.update_customization_prompt(user_id, session)

    async def _queue_sticker_pack(self, event_info, sticker_set_info, is_premium, custom_title: Optional[str] = None, custom_author: Optional[str] = None):
        """Helper method for adding a pack to the queue and sending confirmation message for users"""
        user = await self.ctx.client.get_entity(event_info['user_id'])

        # find estimated time and user priority
        estimated_seconds = estimate_wait_time(sticker_set_info['doc_info'])
        priority = PREMIUM_USER_PRIORITY if is_premium else REGULAR_USER_PRIORITY
        # max conversion duration cap
        if not is_premium:
            if estimated_seconds > MAX_CONVERSION_SECONDS_REGULAR:
                await self.ctx.client.send_message(
                    entity=event_info['chat_id'],
                    message = (
                        "<tg-emoji emoji-id='5228947933545635555'>😟</tg-emoji> <b>Pack Too Large for Regular Users!</b>\n\n"
                        f"This pack is estimated to take more than <b>{MAX_CONVERSION_SECONDS_REGULAR // 60} minutes</b> to convert, "
                        "which exceeds the time limit for regular users.\n\n"
                        "Upgrade to <b>Premium</b> to convert larger packs instantly!\n"
                    ),
                    buttons=[[Button.inline("Learn about Premium", b"premium", style="primary", icon=5967522716062847679)]],
                    reply_to=event_info['message_id'],
                    parse_mode='html'
                )
                return
        set_id = sticker_set_info['set_id']
        is_emoji_pack = sticker_set_info['is_emoji']
        pack_display_name = sticker_set_info['title']

        # get the user's name pack url
        user_display_name = get_user_display_name(user)
        pack_type_url = "addemoji" if is_emoji_pack else "addstickers"
        pack_url = f"https://t.me/{pack_type_url}/{sticker_set_info['short_name']}"

        # Log the request to the database
        log_id = await db.log_conversion_request(user.id, set_id, pack_url, is_emoji_pack)

        # NEW: Increment daily usage counter before adding to queue
        await db.increment_daily_requests(user.id)

        # send adding to queue message
        placeholder_message = await self.ctx.client.send_message(entity=event_info['chat_id'], message="<tg-emoji emoji-id='5220046725493828505'>⌛</tg-emoji> Adding to the queue...", reply_to=event_info['message_id'], parse_mode='html')

        # Determine if this pack is "cache suspicious"
        is_suspicious = not custom_title and not custom_author and self.ctx.cache_enabled and await queue_manager.is_set_id_queued(set_id)
        if is_suspicious:
            logger.info(f"Queueing pack {set_id} as 'cache suspicious'.")


        # add to queue and get position for this item
        position = await queue_manager.add_to_queue(
                user_id=user.id,
                chat_id=event_info['chat_id'],
                message_id=event_info['message_id'],
                username=user_display_name,
                bot_reply_message_id=placeholder_message.id,
                sticker_set_info=sticker_set_info,
                estimated_seconds=estimated_seconds,
                log_id=log_id,
                priority=priority,
                is_cache_suspicious=is_suspicious,
                custom_title=custom_title,
                custom_author=custom_author
        )
        # detailed added to queue successful message string
        if position != 1:
            safe_pack_name = html.escape(pack_display_name)
            if is_premium:
                current_queue_count = await queue_manager.get_user_queue_count(user.id)
                slots_left = MAX_CONCURRENT_PREMIUM_REQUESTS - current_queue_count
                final_message_text = (f"<b><tg-emoji emoji-id='6080171114007367607'>⭐</tg-emoji> VIP Status Confirmed!</b>\n\n"
            f"Your pack: <b><a href=\"{pack_url}\">{safe_pack_name}</a></b> has been fast-tracked to position <b>{position}</b>.<tg-emoji emoji-id='5188481279963715781'>🚀</tg-emoji>\n")

                if slots_left > 0:
                    final_message_text += f"<blockquote>As a premium user, you can still add <b>{slots_left}</b> more pack(s) to the queue. Keep 'em coming!</blockquote>\n"

                final_message_text += "\n<b>I'll notify you when the conversion starts!</b>"
            else:
                final_message_text = (f"<b><tg-emoji emoji-id='5336985409220001678'>✅</tg-emoji> Added to conversion queue!</b>\n\n"
                f"<tg-emoji emoji-id='5785045099142450328'>📦</tg-emoji> Pack: <a href=\"{pack_url}\">{safe_pack_name}</a>\n"
                f"<tg-emoji emoji-id='5821128296217185461'>📍</tg-emoji> Position: {position}\n\n"
                f"<blockquote>I'll notify you when the conversion starts!</blockquote>")

            # finally edit the message with detailed one
            await self.ctx.client.edit_message(
                entity=placeholder_message.chat_id,
                message=placeholder_message.id,
                text=final_message_text,
                buttons=[[Button.inline("Check Queue", b"check_queue", style="primary", icon=5258513401784573443)],[Button.inline("Cancel", data=f"cancel_item_{log_id}".encode(), style="danger", icon=5260342697075416641)]],
                link_preview=False, parse_mode='html'
            )

        if not self.ctx.processing_lock.locked():
            # Check if anyone is processing before starting a new process_queue task
            queue_stats = await queue_manager.get_queue_stats()
            is_processing = queue_stats["currently_processing"]
            if not is_processing:
                asyncio.create_task(self.process_queue())

    async def check_cache(self, chat_id, sender_id, msg_to_reply_id, sticker_set_info, log_id: Optional[int] = None) -> bool:
        """Checks if the sticker set is cached or not if cached it will diresticker_setctly send those files and return True,
        else it will handle cache inconsistencies if any and return False"""
        user_id = sender_id
        set_id = sticker_set_info['set_id']
        current_title = sticker_set_info['title']

        # Check if the pack is cached and up-to-date
        cache_status, channel_id, message_ids = await db.is_pack_cached(set_id, current_title, sticker_set_info['doc_info'])
        
        # --- hehe cache hit ---
        if cache_status == 'hit':
            # Verify the cached files actually exist
            if None not in await self.ctx.client.get_messages(channel_id, ids=message_ids):
                await db.record_cache_hit(set_id, user_id=user_id)
                logger.info(f"✅ Cache hit for pack {set_id} in channel {channel_id}. Forwarding to user {user_id}.")
                num_packs = len(message_ids)
                
                # We need to log this as a successful conversion even though its from cache
                is_emoji_pack = sticker_set_info['is_emoji']
                pack_type_url = "addemoji" if is_emoji_pack else "addstickers"
                pack_url = f"https://t.me/{pack_type_url}/{sticker_set_info['short_name']}"
                is_direct_cache_hit = (log_id is None)
                if is_direct_cache_hit:
                    log_id = await db.log_conversion_request(user_id, set_id, pack_url, is_emoji_pack)
                
                await self.ctx.client.send_message(chat_id, f"<tg-emoji emoji-id='5456140674028019486'>⚡️</tg-emoji> Found this pack in the cache! Sending <b>{num_packs}</b> {'file' if num_packs == 1 else 'files'} instantly...", reply_to=msg_to_reply_id, parse_mode="html")

                try:
                    messages = await self.ctx.client.get_messages(channel_id, ids=message_ids)
                    for message in messages:
                        await self.ctx.client.send_message(entity=chat_id, message=message, link_preview=False)

                    logger.info(f"✅ Successfully forwarded pack {set_id} from cache to user {user_id}.")
                    await self.ctx.client.send_message(chat_id, AFTER_SUCCESSFUL_CONVERSION_MESSAGE,
                                                        buttons= self.templates.create_post_conversion_buttons(),
                                                        link_preview=False, parse_mode="html")
                    await db.update_conversion_log(log_id, "completed_from_cache", datetime.now(timezone.utc), 0.0)
                    if COUNT_CACHE_HITS_AS_REQUESTS and is_direct_cache_hit:
                        await db.increment_daily_requests(user_id)
                    return True
                except UserIsBlockedError:
                    # some dumbass block the bot even when it is sending files
                    logger.error(f"User has blocked the bot! Failed to forward cached messages for pack {set_id} to user {user_id}.")
                    await db.update_conversion_log(log_id, "completed_from_cache_but_blocked", datetime.now(timezone.utc), 0.0)
                    if COUNT_CACHE_HITS_AS_REQUESTS and is_direct_cache_hit:
                        await db.increment_daily_requests(user_id)
                    return True
                # if all successful upload
                except Exception as e:
                    logger.error(f"Failed to forward cached messages for pack {set_id} to user {user_id}: {e}")
                    # If forwarding fails, it's a critical error. Let's treat it as a cache miss and re-convert.
                    await self.ctx.client.send_message(chat_id, "Oops! I found this in the cache, but couldn't send it. I'll try re-converting it for you now. <tg-emoji emoji-id='5384307092599348179'>🫡</tg-emoji>", reply_to=msg_to_reply_id, parse_mode="html")
                    await db.update_conversion_log(log_id, "failed_forward_from_cache", datetime.now(timezone.utc), 0.0)
                    # clear the broken cache
                    asyncio.create_task(self.helpers.delete_cache(set_id))
            else:
                # The DB has an entry, but the messaages are missing or deletd!
                logger.error(f"Cache inconsistency! Files for pack {set_id} not found in cahnnel {channel_id}. Removing DB entry.")
                # clear the broken cache
                asyncio.create_task(self.helpers.delete_cache(set_id))
        # --- stale cache T~T ---
        elif cache_status == 'stale':
            logger.warning(f"Stale cache found for pack {set_id}. Deleting old cache before re-converting.")
            asyncio.create_task(self.helpers.delete_cache(set_id))

        return False # for cache miss or stale cache or inconsistent cache files 

    @check_banned
    @update_user_info
    async def handle_message(self, event: events.NewMessage.Event):
        """
        Handle incoming messages. This is the main router for non-command messages.
        It prioritizes session-based inputs before treating a message as a new conversion request.
        """
        user = await event.get_sender()

        # ------ handle admin replies -------
        if event.is_reply and await db.is_admin(user.id):
            if await self.handle_admin_reply(event): # if it was handled
                raise StopPropagation 

        # ---------- handle session based iput -------
        session_from_reply = None
        flow_from_reply = None
        if event.is_reply:
            session_from_reply_tuple = await session_manager.from_reply(event.chat_id, event.reply_to_msg_id)
            session_from_reply = None
            if session_from_reply_tuple:
                user_id, flow_val, session_id = session_from_reply_tuple
                flow_from_reply = Flow(flow_val)
                session_from_reply = await session_manager.get(user_id, flow_from_reply, session_id)

        if session_from_reply and session_from_reply.active:
            # User replied to a session message, process it directly
            await self.sessions.process_session_input(event, session_from_reply, flow_from_reply)
            return
        
        # if it wasnt a reply to a session message, check for any active input sessions
        active_sessions_with_flow = await self.sessions.get_active_input_sessions(user.id)

        if event.is_reply and len(active_sessions_with_flow) >= 1:
            # user replied to a wrong message or expired session
            await event.reply("<tg-emoji emoji-id='5255772095958229697'>❌</tg-emoji> The messsage you replied to is not a valid input action or has expired.", parse_mode='html')
            return
        
        if len(active_sessions_with_flow) == 1: # single input session
            session, flow = active_sessions_with_flow[0]
            await self.sessions.process_session_input(event, session, flow)
            return
        elif len(active_sessions_with_flow) > 1: # multiple input sessions for non replied msg aint allowed bro
            await self.sessions.prompt_for_ambiguous_input(event, active_sessions_with_flow)
            return
        
        # ----- fine its a normal conversion request lets procced --------------

        # update the database
        await db.add_or_update_user(user.id, user.username, get_user_display_name(user))
        # membership check
        if not await self.helpers.check_user_membership(user.id):
            await event.reply(CHANNEL_JOIN_MESSAGE, buttons=self.templates.create_channel_join_buttons(), link_preview=False, parse_mode='html')
            return

        is_premium = await db.is_premium(user.id)

        # Daily conversion limit check
        daily_limit = DAILY_LIMIT_PREMIUM if is_premium else DAILY_LIMIT_REGULAR
        if daily_limit > 0: # A limit of 0 or less means unlimited.
            current_daily_usage = await db.get_daily_usage(user.id)
            if current_daily_usage >= daily_limit:
                message = (
                    f"<tg-emoji emoji-id='5418159410646099061'>🚫</tg-emoji> <b>Daily Limit Reached!</b>\n\n"
                    f"You have used your quota of <b>{current_daily_usage}/{daily_limit}</b> conversions for today. "
                    "Your limit will reset at midnight (UTC)."
                )
                buttons = None
                if not is_premium:
                    message += f"\n\nConsider upgrading to <b>Premium</b> for higher limits! Plans start from just <b>${PREMIUM_PRICE_MONTHLY}</b>/month."
                    buttons = [[Button.inline("Learn about Premium", b"premium", style="primary", icon=5967522716062847679)]]
                
                await event.reply(message, buttons=buttons, parse_mode='html')
                return
        
        limit = MAX_CONCURRENT_PREMIUM_REQUESTS if is_premium else MAX_CONCURRENT_REGULAR_REQUESTS

        # max queue limit
        async with self.ctx.user_processing_lock:
        # This is for some mfs who spam the bot for no reason,we better ban those shits after a few warning but let's see this in future
            current_queue_count = await queue_manager.get_user_queue_count(user.id)
            realistic_position = current_queue_count + (1 if user.id in self.ctx.users_adding_to_queue else 0)
            if realistic_position >= limit:
                buttons = None
                if is_premium:
                    message = (f"<tg-emoji emoji-id='5255772095958229697'>🚫</tg-emoji> <b>You've reached your limit!</b>\n\n"
                            f"You currently have <b>{realistic_position}/{limit}</b> items in the queue. "
                            f"Please wait for one to complete before adding more.")
                    buttons = [[Button.inline("Check Queue", b"check_queue", style="primary", icon=5258513401784573443)]]
                else:
                    message = (f"<tg-emoji emoji-id='5255772095958229697'>🚫</tg-emoji> You're already in the queue! Please wait for your current request to complete."
                            f"\n\nUpgrade to <b>Premium</b> to convert multiple packs <b>at the same time</b>!")
                    buttons = [[Button.inline("Check Queue", b"check_queue", style="primary", icon=5258513401784573443), 
                                Button.inline("Learn about Premium", b"premium", style="success", icon=5967522716062847679)]]

                asyncio.create_task(self.helpers.safe_reply(event, message, buttons=buttons, parse_mode='html'))
                return
            
            # if check passes mark user as adding to queue
            self.ctx.users_adding_to_queue.add(user.id)
        
        try:        
            # now time to extract pack details based on the type of message sent
            pack_input = await self.helpers.get_pack_input_from_event(event)
            if not pack_input:
                return
            # Fetch the sticker/emoji set to get its actual name and type
            try:
                sticker_set = await self.ctx.network_task.get_sticker_set(pack_input)

                if not sticker_set or not sticker_set.documents:
                    logger.error(f"Could not fetch a valid sticker set for input: {pack_input}")
                    await event.reply("<tg-emoji emoji-id='5019523782004441717'>❌</tg-emoji> I couldn't find that sticker pack. It might be private, invalid, or empty. Please try another one!", parse_mode='html')
                    return

            except Exception as e:
                    logger.error(f"Error fetching set name for user {user.id}: {e}")
                    await event.reply("<tg-emoji emoji-id='5019523782004441717'>❌</tg-emoji> An error occured while fetching the sticker pack. Please try again later!", parse_mode='html')
                    return
                    
            doc_info = [[doc.id, doc.mime_type] for doc in sticker_set.documents]
            sticker_set_info = {"set_id": sticker_set.set.id, "access_hash": sticker_set.set.access_hash, "short_name": sticker_set.set.short_name, "is_emoji": sticker_set.set.emojis, "doc_info": doc_info, "title": sticker_set.set.title, }
            if is_premium:
                # For premium users we use special customizayion flow
                event_info = {'user_id': event.sender_id, 'chat_id': event.chat_id, 'message_id': event.message.id}
                await self._start_customization_flow(event_info, sticker_set_info)
            else:
                # For regular users check cache and queue directly
                if self.ctx.cache_enabled and await self.check_cache(event.chat_id, event.sender_id, event.message.id, sticker_set_info): # cache hit
                    return
                # cache miss we got to queue it 
                event_info = {'user_id': event.sender_id, 'chat_id': event.chat_id, 'message_id': event.message.id}
                await self._queue_sticker_pack(event_info, sticker_set_info, is_premium=False)

        finally:
            # remove user from adding queue set
            self.ctx.users_adding_to_queue.discard(user.id)

    async def handle_admin_reply(self, event: events.NewMessage.Event) -> bool:
        """Handles an admin's reply, checking for duplicates before sending."""
        admin_id = event.sender_id
        reply_msg = await event.get_reply_message()
        
        me = await self.ctx.client.get_me()
        if not reply_msg or not reply_msg.sender_id == me.id:
            return False# not a reply to one of the bot's messages so let handle_message handle it

        # Extract Contact ID from the message
        contact_id_match = re.search(r"Contact ID:[^\d]*(\d+)", reply_msg.text)
        if not contact_id_match:
            return False# not a contact notification message again let handle_message handle this

        contact_id = int(contact_id_match.group(1))
        
        # Get or create a lock for this specific contact_id
        async with self.ctx.reply_locks_lock:
            entry = self.ctx.reply_locks.get(contact_id)
            if not entry:
                entry = {"lock": asyncio.Lock(), "last_used": datetime.now(timezone.utc)}
                self.ctx.reply_locks[contact_id] = entry

        contact_lock = entry["lock"]

        # update last_used immediately before we wait so cleanup won't remove it mid-wait
        entry["last_used"] = datetime.now(timezone.utc)

        async with contact_lock:
            # Check if this message has been replied already
            previous_replies = await db.get_previous_replies(contact_id)

            if not previous_replies:
                # ------- First reply, no one has replied yet----------
                user_id_match = re.search(r"User ID:[^\d]*(\d+)", reply_msg.text)
                if not user_id_match:
                    await event.reply("❌ Couldn't find the original user's ID in the header.")
                    return False

                original_user_id = int(user_id_match.group(1))
                try:
                    # Get the reply content for logging
                    reply_content = get_message_content_for_db(event.message)
                    
                    # Send reply and logging shits
                    await self.ctx.client.send_message(original_user_id, CONTACT_ADMIN_REPLY_HEADER, parse_mode='html')
                    sent_msg = await self.ctx.client.send_message(original_user_id, event.message)
                    await db.log_admin_reply(contact_id, admin_id, sent_msg.id, reply_content)
                    logger.info(f"Admin {admin_id} replied to user {original_user_id}")
                    await event.reply("✅ Reply sent to the user!")
                except Exception as e:
                    logger.error(f"Failed to send admin reply from {admin_id} to {original_user_id}: {e}")
                    await event.reply(f"❌ Failed to send reply: `{e}`")

            else:
                # ------------ Duplicate reply,some admin has/have already replied -------------
                admin_reply_msg_id = event.message.id
                buttons = [
                    [Button.inline("✔️ Yes, reply again", f"contact_force_reply_{contact_id}_{admin_reply_msg_id}")],
                    [Button.inline("❌ Cancel", "contact_cancel_reply")]
                ]
                
                prompt_text = f"⚠️ **This query has already been handled {len(previous_replies)} time(s).**\n\nAre you sure you want to send another reply?"

                # a special "details" button for owner only
                if db.is_owner(admin_id):
                    buttons.insert(1, [Button.inline("🔍 Show Reply Details", f"contact_details_{contact_id}_{admin_reply_msg_id}")])

                await event.reply(prompt_text, buttons=buttons)

            entry["last_used"] = datetime.now(timezone.utc)

        return True

    async def _run_conversion(self, item, is_silent_mode: bool = False):
        """
        The core logic for converting a single sticker pack.
        Raises an Exception on any failure to signal the caller.
        """
        if not is_silent_mode:
            try:
                await self.ctx.client.edit_message(
                    entity=item.chat_id,
                    message=item.bot_reply_message_id,
                    text=f"<tg-emoji emoji-id='5454074580010295588'>⌛</tg-emoji> Your request for the pack is now processing...",
                    buttons=None,
                    parse_mode='html'
                )
            except Exception as e:
                logger.warning(f"Could not edit message {item.bot_reply_message_id} to remove cancel button: {e}")

            status_message = await self.ctx.client.send_message(
                item.chat_id,
                "<tg-emoji emoji-id='5188481279963715781'>🚀</tg-emoji> Starting conversion for your pack...\n"
                "<tg-emoji emoji-id='5382194935057372936'>🤔</tg-emoji> Estimated time: Calculating...",
                parse_mode='html'
            )
        # sticker info
        sticker_set = None
        try:
            sticker_set = await self.ctx.network_task.get_sticker_set(item.sticker_set_info['set_id'], access_hash=item.sticker_set_info['access_hash'])
        except Exception:
            raise
        pack_title = sticker_set.set.title
        safe_pack_title = html.escape(pack_title)
        total_stickers = len(sticker_set.documents)
        doc_info = [[doc.id, doc.mime_type] for doc in sticker_set.documents]
        num_packs = (total_stickers + MAX_STICKERS_PER_PACK - 1) // MAX_STICKERS_PER_PACK
        pack_short_name = sticker_set.set.short_name
        is_emoji_pack = sticker_set.set.emojis
        estimated_seconds = item.estimated_seconds
        processing_timeout = max(60, estimated_seconds * ESTIMATED_TIME_MULTIPLIER)
        status_for_db = "failed"

        pack_type_url = "addemoji" if is_emoji_pack else "addstickers"
        pack_url = f"https://t.me/{pack_type_url}/{pack_short_name}"

        final_author = item.custom_author or self.ctx.bot_username
        final_title = item.custom_title # This can be None create wasticker pack handles this
        

        if not is_silent_mode:
            # Round off the time for better UI
            if estimated_seconds < 60:
                estimated_time_str = f"{round(estimated_seconds)} seconds"
            else:
                minutes = round(estimated_seconds / 60)
                estimated_time_str =  f"~{minutes} minute(s)"

            await self.ctx.client.edit_message(
                entity=item.chat_id,
                message=status_message.id,
                text=f"<tg-emoji emoji-id='5188481279963715781'>🚀</tg-emoji> Starting conversion for your pack...\n"
                    f"<tg-emoji emoji-id='5382194935057372936'>🤔</tg-emoji> Estimated time: {estimated_time_str}",
                parse_mode='html'
            )
            
            item_name = "emojis" if is_emoji_pack else "stickers"
            message = (f"<tg-emoji emoji-id='5339166917598916047'>📊</tg-emoji> <b>Pack Details:</b>\n"
                    f"<tg-emoji emoji-id='5787399776307776752'>◾️</tg-emoji> Name: <a href=\"{pack_url}\">{safe_pack_title}</a>\n"
                    f"<tg-emoji emoji-id='5787399776307776752'>◾️</tg-emoji> Total {item_name}: {total_stickers}\n" +
                    (f"<blockquote>This pack will be split into {num_packs} packs. <a href='{WHY_SPLIT_LINK}'>Why?</a></blockquote>" if num_packs > 1 else ""))
            await self.ctx.client.send_message(item.chat_id, message, parse_mode='html', link_preview=False)

        # run the conversion with a timeout (either 60 sec or 3x the estimated time)
        conversion_start_time = time.monotonic()
        try:
            wastickers_files = await asyncio.wait_for(self.ctx.converter.create_wastickers_pack(sticker_set, final_author, custom_title=final_title), timeout=processing_timeout)
        except asyncio.TimeoutError:
            status_for_db = "failed_conversion_timeout"
            logger.error(f"Conversion timed out while creating .wasticker files for user {item.user_id}. Log ID: {item.log_id}")
            if not is_silent_mode:
                try:
                    await self.ctx.client.send_message(
                        item.chat_id,
                        (f"<tg-emoji emoji-id='5258113901106580375'>⏱️</tg-emoji> The conversion for your pack <b>took longer than expected</b> and has <b>timed out</b>.<tg-emoji emoji-id='5980953710157632545'>❌</tg-emoji>\n\n"
                        f"It is generally due to Telegram server issues.\n"
                        f"<b>Please try again after some time or with a different pack.</b>\n\n"
                        f"If the problem persists, ping us at <b>{SUPPORT_GROUP}</b>"),
                        parse_mode='html'
                    )
                except Exception as e:
                    logger.warning(f"Could not send timeout message to {item.user_id}: {e}")
            user = await self.ctx.client.get_entity(item.user_id)
            user_display_name =get_user_display_name(user)
            await self.ctx.notification_manager.send_conversion_failure(item.user_id, user_display_name, item.log_id, "ConversionTimeout", "Creating .wasticker files took longer than expected.", sticker_set=sticker_set)
            return status_for_db # return failed status immidiately 
        except Exception as e:
            status_for_db = "failed_conversion_exception"
            logger.error(f"Conversion failed while creating .wasticker files for user {item.user_id}. Log ID: {item.log_id}")
            if not is_silent_mode:
                try:
                    await self.ctx.client.send_message(
                        item.chat_id,
                        (f"<tg-emoji emoji-id='5980953710157632545'>❌</tg-emoji> The conversion for your pack has failed.\n"
                        f"Please try again later or with a different pack.\n\n"
                        f"If the problem persists, ping us at <b>{SUPPORT_GROUP}</b>"),
                        parse_mode='html'
                    )
                except Exception as e:
                    logger.warning(f"Could not send timeout message to {item.user_id}: {e}")
            user = await self.ctx.client.get_entity(item.user_id)
            user_display_name =get_user_display_name(user)
            await self.ctx.notification_manager.send_conversion_failure(item.user_id, user_display_name, item.log_id, type(e).__name__, str(e), sticker_set=sticker_set)
            return status_for_db # return failed status immidiately 
    
        if not wastickers_files:
            status_for_db = "failed_no_wasticker_file"
            if not is_silent_mode:
                await self.ctx.client.send_message(item.chat_id, f"<tg-emoji emoji-id='5980953710157632545'>❌</tg-emoji> Failed to convert the pack <b><a href=\"{pack_url}\">{safe_pack_title}</a></b>. \nIf the problem persists, ping us at <b>{SUPPORT_GROUP}</b>", link_preview=False, parse_mode='html')
            # This is a failure so we raise an exception.
            user = await self.ctx.client.get_entity(item.user_id)
            user_display_name =get_user_display_name(user)
            await self.ctx.notification_manager.send_conversion_failure(item.user_id, user_display_name, item.log_id, "NoWastickerFileCreated", "The conversion returned no .wasticker file.", sticker_set=sticker_set)
            return status_for_db

        conversion_end_time = time.monotonic()

        conversion_duration = conversion_end_time - conversion_start_time


        # update the stats with duration
        new_cache_score = await db.add_or_update_sticker_set_details(
            set_id=sticker_set.set.id,
            short_name=pack_short_name,
            is_emoji=is_emoji_pack,
            pack_title=pack_title,
            sticker_count=total_stickers,
            doc_info=doc_info,
            conversion_duration=conversion_duration,
            is_system_process=is_silent_mode,
            user_id=item.user_id if not is_silent_mode else None
        )

        # ------------UPLOAD -------------
        # If we get here conversion was successful now we upload to channel for cache or if cahing diabled upload directly
        cached_messages = []
        target_cache_channel = None
        if (
            self.ctx.cache_enabled 
            and not item.custom_title 
            and not item.custom_author
            and (target_cache_channel:= await self.helpers.get_cache_channel())
        ):
            if not is_silent_mode:
                await self.ctx.client.send_message(item.chat_id, f"<tg-emoji emoji-id='5336985409220001678'>✅</tg-emoji> Conversion complete! Sending <b>{len(wastickers_files)}</b> {'file' if len(wastickers_files) == 1 else 'files'}...", link_preview=False, parse_mode='html')
            
            all_uploads_succeeded = True
            try:
                cached_messages = await self.ctx.network_task.upload_files(wastickers_files, pack_url, safe_pack_title, target_cache_channel)
                if not cached_messages or len(cached_messages) != len(wastickers_files): all_uploads_succeeded = False
                # Now, log this to our database
                if all_uploads_succeeded:
                    status_for_db = "completed"
                    cached_messages_id = [cached_message.id for cached_message in cached_messages]
                    await db.add_to_cache(sticker_set.set.id, new_cache_score, target_cache_channel, cached_messages_id)
                    logger.info(f"Successfully cached pack {sticker_set.set.id} with message IDs: {cached_messages_id}")

            except* FileUploadTimeoutError as eg_t:
                all_uploads_succeeded = False
                status_for_db = "failed_upload_timeout_while_caching"
                # collecting erros 
                failed_uploads = []
                first_failed_index = eg_t.exceptions[0].index
                for exc in eg_t.exceptions:
                    logger.error(f"Upload timeout while caching for user {item.user_id}, file {exc.file_path}")
                    failed_uploads.append(exc.file_path)
                # reporting to user
                if not is_silent_mode:
                    if num_packs == 1:
                        await self.ctx.client.send_message(item.chat_id, f"<tg-emoji emoji-id='5980953710157632545'>❌</tg-emoji> Timed out while uploading pack. Please try again later.", parse_mode='html')
                    else:
                        await self.ctx.client.send_message(item.chat_id, f"<tg-emoji emoji-id='5980953710157632545'>❌</tg-emoji> Timed out while uploading pack part {first_failed_index+1}. Please try again later.", parse_mode='html')
                #notify owner
                user = await self.ctx.client.get_entity(item.user_id)
                user_display_name =get_user_display_name(user)
                await self.ctx.notification_manager.send_conversion_failure(item.user_id, user_display_name, item.log_id, "UploadTimeoutCaching", f"File: {', '.join(failed_uploads)}", sticker_set=sticker_set)
            except* FileUploadWrapperError as eg_w:
                all_uploads_succeeded = False
                status_for_db = "failed_upload_error_while_caching"
                # collecting erros 
                failed_uploads = []
                first_failed_index = eg_w.exceptions[0].index
                for exc in eg_w.exceptions:
                    # Log the original exception for full debug info
                    logger.error(f"Upload error while caching for user {item.user_id}, file {exc.file_path}", exc_info=exc.original_exception)
                    failed_uploads.append(exc.file_path)
                # reporting to user
                if not is_silent_mode:
                    if num_packs == 1:
                        await self.ctx.client.send_message(item.chat_id, f"<tg-emoji emoji-id='5980953710157632545'>❌</tg-emoji> Failed to upload pack due to an error. Please use <b>/contact</b> to report it to the admins.", parse_mode='html')
                    else:
                        await self.ctx.client.send_message(item.chat_id, f"<tg-emoji emoji-id='5980953710157632545'>❌</tg-emoji> Failed to upload pack part {first_failed_index+1} due to an error. Please use <b>/contact</b> to report it to the admins.", parse_mode='html')
                #notify owner
                user = await self.ctx.client.get_entity(item.user_id)
                user_display_name =get_user_display_name(user)
                await self.ctx.notification_manager.send_conversion_failure(item.user_id, user_display_name, item.log_id, "UploadErrorCaching", f"File: {', '.join(failed_uploads)}", sticker_set=sticker_set)
            finally:
                # This ensures temporary .wastickers files are deleted if they weren't cached and moved.
                for file_path in wastickers_files:
                    try:
                        if os.path.exists(file_path):
                            logger.debug(f"Cleaning up temporary output file: {file_path}")
                            os.remove(file_path)
                    except Exception as e:
                        logger.error(f"Error removing temporary output file: {e}")
                # if we coudnt uplaod all files sucessfully delete others too
                if not all_uploads_succeeded and cached_messages:
                    cached_message_ids = [message.id for message in cached_messages]
                    custom_log_msg = "Failed to delete incompletely uploaded pack."
                    asyncio.create_task(self.helpers.delete_multiple_messages(target_cache_channel, cached_message_ids, custom_log_msg))

            # ----- now send from cache (if not a system task) --------
            if not is_silent_mode and all_uploads_succeeded:
                try:
                    for message in cached_messages:
                        await self.ctx.client.send_message(entity=item.chat_id, message=message, link_preview=False)

                    await self.ctx.client.send_message(item.chat_id, AFTER_SUCCESSFUL_CONVERSION_MESSAGE,
                                                        buttons= self.templates.create_post_conversion_buttons(),
                                                        link_preview=False, parse_mode="html")
                    status_for_db = "completed"
                except UserIsBlockedError:
                    # some dumbass block the bot even before it sends files
                    status_for_db = "completed_but_blocked"
                    logger.error(f"User has blocked the bot! Failed to forward cached messages for pack {sticker_set.set.id} to user {item.user_id}.")
                except Exception as e:
                    logger.error(f"Failed to forward newly cached pack {sticker_set.set.id} to user {item.user_id}: {e}")
                    await self.ctx.client.send_message(item.chat_id, "<tg-emoji emoji-id='5980953710157632545'>❌</tg-emoji> An error occurred while sending your files. Please use <b>/contact</b> to report this.", parse_mode='html')
                    status_for_db = "failed_forward"

        else: # caching is off or cache channels full or its a custom premium request
            if not is_silent_mode:
                await self.ctx.client.send_message(item.chat_id, f"<tg-emoji emoji-id='5336985409220001678'>✅</tg-emoji> Conversion complete! Sending <b>{len(wastickers_files)}</b> {'file' if len(wastickers_files) == 1 else 'files'}...", link_preview=False, parse_mode='html')
                
                all_uploads_succeeded = True
                try:
                    await self.ctx.network_task.upload_files(wastickers_files, pack_url, safe_pack_title, item.chat_id)
                    status_for_db = "completed"
                except* UserIsBlockedError:
                    # some dumbass block the bot even before it sends files
                    status_for_db = "completed_but_blocked"
                    all_uploads_succeeded = False
                    logger.error(f"User has blocked the bot! Failed to send .wasticker files for pack {sticker_set.set.id} to user {item.user_id}.")
                except* FileUploadTimeoutError as eg_t:
                    status_for_db = "failed_upload_timeout"
                    all_uploads_succeeded = False
                    # collecting erros 
                    failed_uploads = []
                    first_failed_index = eg_t.exceptions[0].index
                    for exc in eg_t.exceptions:
                        logger.error(f"Upload timeout for user {item.user_id}, file {exc.file_path}")
                        failed_uploads.append(exc.file_path)
                    # reporting user 
                    if num_packs == 1:
                        await self.ctx.client.send_message(item.chat_id, f"<tg-emoji emoji-id='5980953710157632545'>❌</tg-emoji> Timed out while uploading pack. Please try again later.", parse_mode="html")
                    else:
                        await self.ctx.client.send_message(item.chat_id, f"<tg-emoji emoji-id='5980953710157632545'>❌</tg-emoji> Timed out while uploading pack part {first_failed_index+1}. Please try again later.", parse_mode="html")
                    #notify owner
                    user = await self.ctx.client.get_entity(item.user_id)
                    user_display_name =get_user_display_name(user)
                    await self.ctx.notification_manager.send_conversion_failure(item.user_id, user_display_name, item.log_id, "UploadTimeout", f"File: {', '.join(failed_uploads)}", sticker_set=sticker_set)
                except* FileUploadWrapperError as eg_w:
                    status_for_db = "failed_upload_error"
                    all_uploads_succeeded = False
                    # collecting erros 
                    failed_uploads = []
                    first_failed_index = eg_w.exceptions[0].index
                    for exc in eg_w.exceptions:
                        # Log the original exception for full debug info
                        logger.error(f"Upload error for user {item.user_id}, file {exc.file_path}", exc_info=exc.original_exception)
                        failed_uploads.append(exc.file_path)
                    # reporting user
                    if num_packs == 1:
                        await self.ctx.client.send_message(item.chat_id, f"<tg-emoji emoji-id='5980953710157632545'>❌</tg-emoji> Failed to upload pack due to an error. Please use <b>/contact</b> to report it to the admins.", parse_mode="html")
                    else:
                        await self.ctx.client.send_message(item.chat_id, f"<tg-emoji emoji-id='5980953710157632545'>❌</tg-emoji> Failed to upload pack part {first_failed_index+1} due to an error. Please use <b>/contact</b> to report it to the admins.", parse_mode="html")
                    #notify owner
                    user = await self.ctx.client.get_entity(item.user_id)
                    user_display_name =get_user_display_name(user)
                    await self.ctx.notification_manager.send_conversion_failure(item.user_id, user_display_name, item.log_id, "UploadError", f"File: {', '.join(failed_uploads)}", sticker_set=sticker_set)
                finally:
                    # This ensures temporary .wastickers files are deleted if they weren't cached and moved.
                    for file_path in wastickers_files:
                        try:
                            if os.path.exists(file_path):
                                logger.debug(f"Cleaning up temporary output file: {file_path}")
                                os.remove(file_path)
                        except Exception as e:
                            logger.error(f"Error removing temporary output file: {e}")

                # If all uploads were successful
                if all_uploads_succeeded:
                    await self.ctx.client.send_message(item.chat_id, AFTER_SUCCESSFUL_CONVERSION_MESSAGE,
                                                        buttons= self.templates.create_post_conversion_buttons(),
                                                        link_preview=False, parse_mode="html")
                    
        return status_for_db

    async def process_queue(self):
        """Process the conversion queue."""
        async with self.ctx.processing_lock:
            while True and not self.ctx.shutting_down:
                item = await queue_manager.get_next_item()
                if not item:
                    break

                # ------ last cache check (if applicable) ------------------
                # check for cache suspecious item (for user items)
                if item.is_cache_suspicious:
                    logger.info(f"Re-checking cache for suspicious item from user {item.user_id} (Log ID: {item.log_id})")
                    try:
                        # We pass the item's log_id so we don't create a new DB entry
                        if await self.check_cache(item.chat_id, item.user_id, item.message_id, item.sticker_set_info, log_id=item.log_id):
                            logger.info(f"Suspicious item was a cache hit! Skipping conversion.")
                            await self.ctx.client.edit_message(entity=item.chat_id, message=item.bot_reply_message_id, text=f"<tg-emoji emoji-id='5456140674028019486'>⚡</tg-emoji> The pack you requested was processed instantly from the cache.", parse_mode="html")
                            await queue_manager.complete_processing(item.id, success=True)
                            continue # Success! Move to the next item in the queue.
                    except Exception as e:
                        logger.error(f"Error during suspicious cache check for log {item.log_id}: {e}")
                
                # Before running cache refresh or add, check if the pack got cached by another process (for system items)
                if item.is_silent_mode:
                    sticker_set_info = item.sticker_set_info
                    try:
                        cache_status, channel_id, msg_ids = await db.is_pack_cached(sticker_set_info['set_id'], sticker_set_info['title'], sticker_set_info['doc_info'])

                        if cache_status == 'hit':
                            # The DB says it's cached. Let's quickly verify the files are still there.
                            messages = await self.ctx.client.get_messages(channel_id, ids=msg_ids)

                            if messages and all(m is not None for m in messages):
                                await db.record_cache_hit(sticker_set_info['set_id'], is_system_process=True) # update last upadted timestamp 

                                # The cache is valid and exists. We can safely skip this redundant job.
                                logger.info(f"Skipping processing for pack '{sticker_set_info['short_name']}' (Log ID: {item.log_id}) as it's already cached.")
                                
                                # We must properly close out this queue item and log it.
                                await db.update_conversion_log(item.log_id, "completed_skipped_pre_cached", datetime.now(timezone.utc), 0.0)
                                await queue_manager.complete_processing(item.id, success=True)
                                
                                # And importantly clean up our system job trackers i mean those damn sets
                                if item.log_id in self.ctx.active_refresh_jobs:
                                    self.ctx.active_refresh_jobs.discard(item.log_id)
                                    if not self.ctx.active_refresh_jobs and not self.ctx.active_refresh_message:
                                        await self.ctx.client.send_message(OWNER_ID, "<tg-emoji emoji-id='5336985409220001678'>✅</tg-emoji> Cache refresh operation complete!", parse_mode="html")
                                
                                if item.log_id in self.ctx.active_add_jobs:
                                    self.ctx.active_add_jobs.discard(item.log_id)
                                    if not self.ctx.active_add_jobs and not self.ctx.active_add_message:
                                        await self.ctx.client.send_message(OWNER_ID, "<tg-emoji emoji-id='5336985409220001678'>✅</tg-emoji> Add-to-cache operation complete!", parse_mode="html")

                                continue # Success! Move to the next item in the queue.
                                
                    except Exception as e:
                        logger.warning(f"Pre-check failed for pack '{sticker_set_info['short_name']}': {e}. Proceeding with conversion as a fallback.")


                start_time = datetime.now(timezone.utc)
                success = False 
                status_for_db = "None"
                try:                    
                    status_for_db = await self._run_conversion(item, item.is_silent_mode)

                except UserIsBlockedError:
                    status_for_db = "blocked_by_user"
                    logger.error(f"User has blocked the bot! Cannot proceed further, skiped.")
                    
                except Exception as e:
                    status_for_db = "failed_exception"
                    logger.error(f"An exception occurred while processing queue item for user {item.user_id}: {e}", exc_info=True)
                    user = await self.ctx.client.get_entity(item.user_id)
                    user_display_name =get_user_display_name(user)
                    await self.ctx.notification_manager.send_conversion_failure(item.user_id, user_display_name, item.log_id, f"Some error that you never expeted: {type(e).__name__}", str(e), sticker_set_info=item.sticker_set_info)

                finally:
                    # Update the database log
                    completion_time = datetime.now(timezone.utc)
                    duration = (completion_time - start_time).total_seconds()
                    await db.update_conversion_log(item.log_id, status_for_db, completion_time, duration)
                    if status_for_db.startswith("completed"):
                        success = True
                    await queue_manager.complete_processing(item.id, success)

                    # check if it was a system generated task ---------      
      
                    if item.log_id in self.ctx.active_refresh_jobs:
                        self.ctx.active_refresh_jobs.discard(item.log_id)
                        # If that was the last job, notify the owner
                        if not self.ctx.active_refresh_jobs and not self.ctx.active_refresh_message:
                            logger.info("All cache refresh jobs have been completed.")
                            await self.ctx.client.send_message(OWNER_ID, "<tg-emoji emoji-id='5336985409220001678'>✅</tg-emoji> Cache refresh operation complete!", parse_mode="html")

                    if item.log_id in self.ctx.active_add_jobs:
                        self.ctx.active_add_jobs.discard(item.log_id)
                        # If that was the last job, notify the owner
                        if not self.ctx.active_add_jobs and not self.ctx.active_add_message:
                            logger.info("All add-cache jobs have been completed.")
                            await self.ctx.client.send_message(OWNER_ID, "<tg-emoji emoji-id='5336985409220001678'>✅</tg-emoji> Add-to-cache operation complete!", parse_mode="html")

    async def execute_refresh_task(self, action_type: str, payload: dict, original_event_info: dict):
        """The background task that fetches pack details and queues them for refresh."""
        system_id = SYSTEM_USER_ID
        packs_to_queue = []
        
        if action_type == "refreshcache_top_n":
            limit = payload['limit']
            if self.ctx.active_refresh_message: await self.ctx.client.edit_message(self.ctx.active_refresh_message, f"Step 1/2: Clearing entire cache...")
            
            # Clear entire cache
            all_packs = await db.get_all_cached_pack_ids()
            asyncio.create_task(self.helpers.delete_multiple_cache(all_packs))

            all_packs_short_name = None
            if limit == "all":
                all_packs_short_name = await db.get_all_known_pack_short_names()
            packs_to_queue = all_packs_short_name if limit == "all" else await db.get_top_packs_by_score(limit) 

        elif action_type == "refreshcache_links":
            pack_names = payload['pack_short_names']
            if self.ctx.active_refresh_message: await self.ctx.client.edit_message(self.ctx.active_refresh_message, f"Step 1/2: Clearing cache for {len(pack_names)} specified packs...")
            # Clear specified packs and prepare for queueing
            set_ids = []
            for name in pack_names:
                set_id = await db.get_set_id_by_short_name(name)
                if set_id:
                    set_ids.append(set_id)
            asyncio.create_task(self.helpers.delete_multiple_cache(set_ids))

            packs_to_queue = pack_names

        total_to_queue = len(packs_to_queue)
        if self.ctx.active_refresh_message: await self.ctx.client.edit_message(self.ctx.active_refresh_message, f"Step 2/2: Checking and Queueing {total_to_queue} packs for conversion...")
        else: return

        queued_count = 0
        for short_name in packs_to_queue:

            if queued_count > 0 and not self.ctx.active_refresh_jobs:
                logger.info("Refresh operation was cancelled. Halting queueing task.")
                break

            try:
                sticker_set = await self.ctx.network_task.get_sticker_set(short_name)
                if not sticker_set or not sticker_set.documents: continue

                is_emoji = sticker_set.set.emojis
                pack_url = f"https://t.me/add{'emoji' if is_emoji else 'stickers'}/{short_name}"
                log_id = await db.log_conversion_request(system_id, sticker_set.set.id, pack_url, is_emoji)

                doc_info = [[doc.id, doc.mime_type] for doc in sticker_set.documents]
                sticker_set_info = {"set_id": sticker_set.set.id, "access_hash": sticker_set.set.access_hash, "short_name": sticker_set.set.short_name, "is_emoji": sticker_set.set.emojis, "doc_info": doc_info, "title": sticker_set.set.title, }
                estimated_seconds = estimate_wait_time(sticker_set_info['doc_info'])

                await queue_manager.add_to_queue(
                    user_id=system_id, chat_id=original_event_info['chat_id'], message_id=original_event_info['message_id'], username="System Refresh", bot_reply_message_id=original_event_info['bot_reply_message_id'],
                    sticker_set_info=sticker_set_info, estimated_seconds=estimated_seconds, log_id=log_id,
                    priority=SYSTEM_PRIORITY, is_cache_suspicious=False,
                    is_silent_mode=True
                )
                self.ctx.active_refresh_jobs.add(log_id)
                queued_count += 1
                if queued_count % 10 == 0 and self.ctx.active_refresh_message: # Update every 10 packs
                    await self.ctx.client.edit_message(self.ctx.active_refresh_message, f"Step 2/2: Queued {queued_count}/{total_to_queue} packs...")

            except Exception as e:
                logger.error(f"Failed to queue pack {short_name} for refresh: {e}")

        
        if self.ctx.active_refresh_message: 
            await self.ctx.client.edit_message(self.ctx.active_refresh_message, f"✅ Successfully queued **{queued_count}/{total_to_queue}** packs for cache refresh.\nConversions will now run in the background with low priority.")
        self.ctx.active_refresh_message = None # We're done editing this message
        # start the queue if its not running
        if not self.ctx.processing_lock.locked():
            queue_stats = await queue_manager.get_queue_stats()
            is_processing = queue_stats["currently_processing"]
            if not is_processing:
                asyncio.create_task(self.process_queue())

    async def execute_addcache_task(self, action_type: str, payload: dict, original_event_info: dict):
        """The background task that fetches, verifies, and queues non-cached packs."""
        system_id = SYSTEM_USER_ID
        packs_to_process = []

        # Step 1: Get the list of pack short_names to process
        try:
            if action_type == "addcache_links":
                packs_to_process = payload['pack_short_names']
                if self.ctx.active_add_message: await self.ctx.client.edit_message(self.ctx.active_add_message, f"Step 1/2: Preparing to check {len(packs_to_process)} specified packs...")

            elif action_type == "addcache_all":
                if self.ctx.active_add_message: await self.ctx.client.edit_message(self.ctx.active_add_message, "Step 1/2: Fetching ALL non-cached packs from the database...")
                packs_to_process = await db.get_non_cached_packs()

            elif action_type == "addcache_n":
                limit = payload['limit']
                if self.ctx.active_add_message: await self.ctx.client.edit_message(self.ctx.active_add_message, f"Step 1/2: Fetching top {limit} non-cached packs from the database...")
                packs_to_process = await db.get_non_cached_packs(limit=limit)
        except Exception as e:
            logger.error(f"AddCache: Failed to fetch packs from DB: {e}", exc_info=True)
            if self.ctx.active_add_message: await self.ctx.client.edit_message(self.ctx.active_add_message, f"❌ Failed to fetch pack list from database: {e}")
            return

        total_to_process = len(packs_to_process)
        if self.ctx.active_add_message: await self.ctx.client.edit_message(self.ctx.active_add_message, f"Step 2/2: Checking and queueing {total_to_process} packs...")
        else: return

        queued_count = 0
        skipped_count = 0
        failed_count = 0

        for i, short_name in enumerate(packs_to_process, 1):
            if i > 1 and not self.ctx.active_add_message:
                logger.info("Add-cache operation was cancelled. Halting queueing task.")
                break
            
            try:
                sticker_set = await self.ctx.network_task.get_sticker_set(short_name)
                if not sticker_set or not sticker_set.documents:
                    logger.warning(f"AddCache: Could not fetch sticker set for '{short_name}'. Skipping.")
                    failed_count += 1
                    continue
                
                set_id = sticker_set.set.id
                set_title = sticker_set.set.title
                doc_info = [[doc.id, doc.mime_type] for doc in sticker_set.documents]

                cache_status, channel_id, message_ids = await db.is_pack_cached(set_id, set_title, doc_info)
                
                if cache_status == 'hit':
                    try:
                        messages = await self.ctx.client.get_messages(channel_id, ids=message_ids)
                        if messages and all(msg is not None for msg in messages):
                            await db.record_cache_hit(set_id, is_system_process=True)
                            skipped_count += 1
                            continue
                        else:
                            logger.warning(f"AddCache: Inconsistent cache for {short_name}. Clearing and re-queueing.")
                            asyncio.create_task(self.helpers.delete_cache(set_id))
                    except Exception as e:
                        logger.error(f"AddCache: Error verifying messages for {short_name}: {e}. Re-queueing.")
                        asyncio.create_task(self.helpers.delete_cache(set_id))
                
                elif cache_status == 'stale':
                    logger.warning(f"AddCache: Stale cache for {short_name}. Clearing and re-queueing.")
                    asyncio.create_task(self.helpers.delete_cache(set_id))

                is_emoji = sticker_set.set.emojis
                pack_url = f"https://t.me/add{'emoji' if is_emoji else 'stickers'}/{short_name}"
                log_id = await db.log_conversion_request(system_id, sticker_set.set.id, pack_url, is_emoji)
                
                sticker_set_info = {"set_id": sticker_set.set.id, "access_hash": sticker_set.set.access_hash, "short_name": sticker_set.set.short_name, "is_emoji": sticker_set.set.emojis, "doc_info": doc_info, "title": sticker_set.set.title, }
                estimated_seconds = estimate_wait_time(sticker_set_info['doc_info'])
                
                await queue_manager.add_to_queue(
                    user_id=system_id, chat_id=original_event_info['chat_id'], message_id=original_event_info['message_id'], username="System AddCache", bot_reply_message_id=original_event_info['bot_reply_message_id'],
                    sticker_set_info=sticker_set_info, estimated_seconds=estimated_seconds, log_id=log_id,
                    priority=SYSTEM_PRIORITY, is_cache_suspicious=False,
                    is_silent_mode=True
                )
                self.ctx.active_add_jobs.add(log_id)
                queued_count += 1

                if i % 10 == 0 and self.ctx.active_add_message:
                    await self.ctx.client.edit_message(self.ctx.active_add_message, f"Step 2/2: Progress...\n- Queued: {queued_count}\n- Skipped: {skipped_count}\n- Failed: {failed_count}\n- Total: {i}/{total_to_process}")

            except Exception as e:
                failed_count += 1
                logger.error(f"Failed to queue pack {short_name} for add-cache: {e}")

        if self.ctx.active_add_message:
            final_message = (
                f"✅ **Add-Cache Queuing Complete!**\n\n"
                f"• Successfully queued: **{queued_count}**\n"
                f"• Skipped (already cached): **{skipped_count}**\n"
                f"• Failed to queue: **{failed_count}**\n\n"
                f"Conversions will now run in the background with low priority."
            )
            await self.ctx.client.edit_message(self.ctx.active_add_message, final_message)

        self.ctx.active_add_message = None
        if not self.ctx.processing_lock.locked():
            queue_stats = await queue_manager.get_queue_stats()
            is_processing = queue_stats["currently_processing"]
            if not is_processing:
                asyncio.create_task(self.process_queue())

    async def execute_interactive_addcache(self, event: events.NewMessage.Event):
        """Handles a single pack submission in interactive add-cache mode."""
        pack_input  = await self.helpers.get_pack_input_from_event(event)

        if not pack_input:
            return
        
        try:
            sticker_set = await self.ctx.network_task.get_sticker_set(pack_input)
            if not sticker_set or not sticker_set.documents:
                await event.reply("<tg-emoji emoji-id='5019523782004441717'>❌</tg-emoji> Couldn't find that sticker pack. It might be private or empty.", parse_mode='html')
                return

            # Perform a silent cache check
            set_id = sticker_set.set.id
            set_title = sticker_set.set.title
            doc_info = [[doc.id, doc.mime_type] for doc in sticker_set.documents]

            cache_status, channel_id, message_ids = await db.is_pack_cached(set_id, set_title, doc_info)

            if cache_status == 'hit':
                messages = await self.ctx.client.get_messages(channel_id, ids=message_ids)
                if messages and all(msg is not None for msg in messages):
                    await db.record_cache_hit(set_id, is_system_process=True)
                    await event.reply(f"<tg-emoji emoji-id='5336985409220001678'>✅</tg-emoji> Pack '<code>{set_title}</code>' is already in the cache. Skipped.", parse_mode='html')
                    return
                else:
                    asyncio.create_task(self.helpers.delete_cache(set_id)) # Inconsistent cache
            elif cache_status == 'stale':
                asyncio.create_task(self.helpers.delete_cache(set_id))
            
            # Queue it
            placeholder = await event.reply(f"<tg-emoji emoji-id='5787344001862471785'>⏳</tg-emoji> Adding '<code>{set_title}</code>' to the queue...", parse_mode='html')
            system_id = SYSTEM_USER_ID

            is_emoji = sticker_set.set.emojis
            pack_url = f"https://t.me/add{'emoji' if is_emoji else 'stickers'}/{sticker_set.set.short_name}"
            log_id = await db.log_conversion_request(system_id, set_id, pack_url, is_emoji)
            
            sticker_set_info = {"set_id": sticker_set.set.id, "access_hash": sticker_set.set.access_hash, "short_name": sticker_set.set.short_name, "is_emoji": sticker_set.set.emojis, "doc_info": doc_info, "title": sticker_set.set.title, }
            estimated_seconds = estimate_wait_time(sticker_set_info['doc_info'])
            
            position = await queue_manager.add_to_queue(
                user_id=system_id, chat_id=event.chat_id, message_id=event.message.id, username="System AddCache (Interactive)", bot_reply_message_id=placeholder.id,
                sticker_set_info=sticker_set_info, estimated_seconds=estimated_seconds, log_id=log_id,
                priority=SYSTEM_PRIORITY, is_cache_suspicious=False,
                is_silent_mode=True
            )
            self.ctx.active_add_jobs.add(log_id)
            await placeholder.edit(f"<tg-emoji emoji-id='6296577138615125756'>✅</tg-emoji> Queued '<code>{set_title}</code>' for caching at position {position}.", parse_mode='html')
            
            if not self.ctx.processing_lock.locked():
                queue_stats = await queue_manager.get_queue_stats()
                if not queue_stats["currently_processing"]:
                    asyncio.create_task(self.process_queue())

        except Exception as e:
            await event.reply(f"<tg-emoji emoji-id='5019523782004441717'>❌</tg-emoji> An error occurred: {e}", parse_mode='html')
            logger.error(f"Interactive AddCache Error: {e}", exc_info=True)

    async def _gstats_send_list(self, event: events.CallbackQuery.Event, title: str, content: str, filename: str):
        """Helper to send gstats lists, sending as a file if too long."""

        buttons = [[Button.inline("Back to Stats", b"gstats_back", icon=5877629862306385808)]]
        header = f"<tg-emoji emoji-id='5956561916573782596'>📋</tg-emoji> <b>{title}</b>\n\n"

        if not content.strip():
            await event.edit(header + f"The list for <code>{title}</code> is empty.", buttons= buttons, link_preview=False, parse_mode='html')
            return


        if len(header + content) > 4000: # A bit less than 4096 to be safe
            file_content = content.replace("`", "").replace("*", "") # Clean formatting for .txt
            with open(filename, 'w', encoding='utf-8') as f:
                f.write(file_content)

            # Delete the previous message and send a new one with the file
            await event.delete()
            await self.ctx.client.send_file(
                event.chat_id,
                filename,
                caption=f"The list of **{title}** was too long, so I've sent it as a file.",
                buttons=buttons
            )
            try:
                if os.path.exists(filename):
                    os.remove(filename)
            except Exception as e:
                logger.error(f"Error removing gstats list file: {e}")
        else:
            await event.edit(header + content, buttons=buttons, link_preview=False, parse_mode='html')


    @check_banned
    @update_user_info
    async def handle_callback_query(self, event: events.CallbackQuery.Event):
        """Handle callback queries from inline keyboards."""
        user_id = event.sender_id

        # Get or create a lock for this user
        async with self.ctx.user_callback_locks_lock:
            if user_id not in self.ctx.user_callback_locks:
                self.ctx.user_callback_locks[user_id] = {"lock": asyncio.Lock(), "last_used": datetime.now(timezone.utc)}
            
            user_lock_entry = self.ctx.user_callback_locks[user_id]
            user_lock = user_lock_entry["lock"]
            user_lock_entry["last_used"] = datetime.now(timezone.utc) # Update last used

        if user_lock.locked():
            # if its already locked, its a rapid click
            await event.answer("Hey, please click one at a time 😓")
            return 
        
        async with user_lock:
            data = event.data.decode('utf-8')

            if data == "check_membership":
                if await self.helpers.check_user_membership(user_id):
                    await event.answer("✅ Great! You're now a member.")
                    await event.edit("<tg-emoji emoji-id='5208541126583136130'>✅</tg-emoji> Great! You're now a member.\n\n" + self.ctx.START_MESSAGE, buttons=self.ctx.START_BUTTONS, link_preview=False, parse_mode='html')
                else:
                    try:
                        await event.answer("❌ You still need to join the required channels.")
                        await event.edit("<tg-emoji emoji-id='5980953710157632545'>❌</tg-emoji> You still need to join the required channels.\n\n" + CHANNEL_JOIN_MESSAGE, buttons=self.templates.create_channel_join_buttons(), link_preview=False, parse_mode='html')
                    except Exception as e:
                        logger.warning(f"Could not edit the Join message: {e}")
            
            elif data.startswith("cancel_item_"):
                await event.answer()
                log_id = int(data.split("_", 2)[2])
                success = await queue_manager.cancel_item(user_id, log_id)
                if success:
                    await db.update_conversion_log(log_id, "cancelled", datetime.now(timezone.utc), 0.0)
                    await db.decrement_daily_requests(user_id)
                    await event.edit("<tg-emoji emoji-id='5336985409220001678'>✅</tg-emoji> Your request has been successfully cancelled.", parse_mode="html")
                else:
                    await event.edit("<tg-emoji emoji-id='5980953710157632545'>❌</tg-emoji> Could not cancel. The item may be processing or completed.", parse_mode="html")

            elif data == "check_queue":
                try:
                    await event.answer("Refreshed!")
                    await self.ctx.user.show_queue_status(event, user_id, mode="callback")
                except Exception as e:
                    logger.debug(f"Could not edit the check_queue message: {e}")
            
            elif data == "help":
                await event.answer()
                buttons = [
                    [Button.inline("Back to Start", b"start", style = None, icon=5258236805890710909), Button.inline("Commands", b"commands", style = None, icon=5787544344906959608)]
                ]
                await edit_rich_message(self.ctx.client, event.chat_id, event.message_id, HELP_MESSAGE_RICH, HELP_MESSAGE_FALLBACK, buttons=buttons, link_preview=False)

            elif data == "help_import":
                await event.answer()
                buttons = [ [Button.inline("Back", b"post_conv", style = None, icon=5877629862306385808)]]
                await edit_rich_message(self.ctx.client, event.chat_id, event.message_id, HELP_IMPORT_MESSAGE, HELP_MESSAGE_FALLBACK, buttons=buttons, link_preview=False)

            elif data == "post_conv":
                await event.answer()
                buttons= self.templates.create_post_conversion_buttons()
                await event.edit(AFTER_SUCCESSFUL_CONVERSION_MESSAGE, buttons=buttons, link_preview=False, parse_mode='html')

            elif data == "start":
                await event.answer()
                await event.edit(self.ctx.START_MESSAGE, buttons=self.ctx.START_BUTTONS, link_preview=False, parse_mode='html')
            
            elif data == "premium":
                await event.answer()
                message_text, buttons = await self.templates.get_premium_text_and_buttons(user_id)
                await event.edit(message_text, buttons=buttons, parse_mode='html', link_preview=False)

            elif data.startswith("buy_premium_") or data.startswith("extend_premium_"):
                await event.answer()

                if data.startswith("buy_premium_") and await db.is_premium(user_id):
                    message_text, buttons = await self.templates.get_premium_text_and_buttons(user_id)
                    await event.edit(message_text, buttons=buttons, parse_mode='html', link_preview=False)
                    return
                
                days = int(data.split("_")[2])
                
                if days == 30:
                    amount = PREMIUM_STARS_MONTHLY
                    title = "1 Month Premium"
                elif days == 365:
                    amount = PREMIUM_STARS_YEARLY
                    title = "1 Year Premium"
                else:
                    return

                description = f"Upgrade your account to {title}. Enjoy priority queue, custom titles/authors, higher limits and more!"
                
                # Fetch the invoice from our shiny new reusable manager
                invoice_media = self.ctx.payment_manager.create_stars_invoice(
                    title=title,
                    description=description,
                    payload=f"premium_{days}",
                    amount=amount
                )
                
                # Send the invoice message
                await self.ctx.client.send_message(event.chat_id, file=invoice_media)


            elif data == "commands":
                await event.answer()
                buttons = [
                    [Button.inline("Back to Start", b"start", style = None, icon=5258236805890710909), Button.inline("Help", b"help", style = None, icon=5818947586702184246)]
                ]
                await event.edit(COMMANDS_MESSAGE, buttons=buttons, parse_mode='html')

            elif data == "contact":
                await event.answer()
                await self.ctx.user.show_contact_prompt(event, user_id, mode="callback")

            elif data == "contact_cancel_reply":
                await event.edit("<tg-emoji emoji-id='5336985409220001678'>✅</tg-emoji> Action cancelled. The reply was not sent.", parse_mode="html")
                
            elif data.startswith("contact_send_"):
                await event.answer()
                *_, sid = data.split("_", 2)
                session = await session_manager.get(user_id, Flow.CONTACT, sid)

                if session and session.active:
                    # Update the session state to wait for the user's message
                    await session_manager.update(user_id, Flow.CONTACT, sid, state="awaiting_contact_message", ttl_seconds=3600)
                    prompt_message = await event.edit(
                        "<tg-emoji emoji-id='5319161050128459957'>✅</tg-emoji> Great! Please send the message you'd like to forward now. You can reply to this message or send a new one.", 
                        buttons=[Button.inline("Cancel", f"contact_cancel_{sid}", style="danger", icon=5465665476971471368)], parse_mode="html"
                    )
                    # Link this message to the session so we can identify replies
                    await session_manager.mark_message(user_id, Flow.CONTACT, sid, event.chat_id, prompt_message.id)
                else:
                    await event.edit("This action has expired. Please use /contact again.")

            elif data.startswith("contact_cancel_"):
                await event.answer()
                *_, sid = data.split("_", 2)
                session = await session_manager.get(user_id, Flow.CONTACT, sid)

                if session and session.active:
                    # Expire the session to deactivate it
                    await session_manager.expire(user_id, Flow.CONTACT, sid)
                    await event.edit("<tg-emoji emoji-id='5336985409220001678'>✅</tg-emoji> Action cancelled.", buttons=None, parse_mode="html")
                else:
                    await event.edit("This action has expired or already completed.")

            elif data.startswith("contact_force_reply_"):
                await event.answer()
                original_user_id = None
                try:
                    *_, contact_id_str, admin_msg_id_str = data.split("_")
                    contact_id = int(contact_id_str)
                    admin_msg_id = int(admin_msg_id_str)

                    # Fetch details of the original user
                    details = await db.get_contact_details(contact_id)
                    if not details:
                        logger.error(f"Failed to get the original contact message of contact ID {contact_id}.")
                        await event.edit("❌ Error: Could not find the original contact message.")
                        return

                    original_user_id = details['user_message']['user_id']
                    
                    # Fetch the admin's reply message
                    admin_msg = await self.ctx.client.get_messages(event.chat_id, ids=admin_msg_id)
                    reply_content = get_message_content_for_db(admin_msg)
                    
                    # Send the reply and log it
                    await self.ctx.client.send_message(original_user_id, CONTACT_ADMIN_REPLY_HEADER, parse_mode='html')
                    sent_msg = await self.ctx.client.send_message(original_user_id, admin_msg)
                    await db.log_admin_reply(contact_id, user_id, sent_msg.id, reply_content)
                    logger.info(f"An admin replied to the already replied user {original_user_id}")
                    await event.edit("✅ Your additional reply has been sent.")
                except Exception as e:
                    logger.error(f"Failed to send duplicate admin reply to {original_user_id if original_user_id else 'Unknown User ID'}: {e}")
                    await event.edit(f"❌ An error occurred: {e}")

            elif data.startswith("contact_details_"):
                await event.answer()
                *_, contact_id_str, admin_msg_id_str = data.split("_")
                contact_id = int(contact_id_str)
                
                details = await db.get_contact_details(contact_id)
                if not details:
                    await event.edit("❌ Could not retrieve details for this contact.")
                    return

                # Format the details into a nice, readable message
                user_msg = details['user_message']
                admin_reps = details['admin_replies']
                user_message_text = user_msg['user_message_text'] if len(user_msg['user_message_text']) <= 1000 else user_msg['user_message_text'][:994] + "......"
                sent_time = user_msg['action_time_sent'].strftime('%Y-%m-%d %H:%M:%S')
                safe_user_name = html.escape(user_msg['user_full_name'])
                safe_user_message = html.escape(user_message_text)
                response_text = (
                    f"📖 <b>Contact Details for Ticket #{contact_id}</b>\n\n"
                    f"👤 <b>From User:</b> <code>{user_msg['user_id']}</code> ({safe_user_name})\n"
                    f"⏰ <b>Query Sent:</b> <code>{sent_time}</code>\n"
                    f"💬 <b>Message:</b> <blockquote>{safe_user_message}</blockquote>"
                    f"---"
                )

                if not admin_reps:
                    response_text += "\n\n<i>No replies have been sent for this query yet.</i>"
                else:
                    for i, reply in enumerate(admin_reps, 1):
                        # i have tested myself that upto 13 replies it can be displayed without any issue like max characters reached and formatting issues
                        if i > 13: 
                            response_text += "\n\nThere are <b>some more replies left</b> but the message got too long, so please check the database yourself."
                            break
                        
                        reply_time = reply['action_time_replied'].strftime('%H:%M:%S on %Y-%m-%d')
                        admin_name = reply['admin_full_name'][:20] or "N/A"
                        admin_reply_text = reply['admin_reply_text'] if len(reply['admin_reply_text']) <= 100 else reply['admin_reply_text'][0:96]+ "..."
                        safe_admin_name = html.escape(admin_name)
                        safe_admin_reply_text = html.escape(admin_reply_text)
                        response_text += (
                            f"\n\n↪️ <b>Reply #{i}</b>\n"
                            f"  - <b>By Admin:</b> <code>{reply['admin_id']}</code> ({safe_admin_name})\n"
                            f"  - <b>Replied at:</b> <code>{reply_time}</code>\n"
                            f"  - <b>Reply:</b> <blockquote>{safe_admin_reply_text}</blockquote>"
                        )
                
                buttons = [[Button.inline("⬅️ Back", f"contact_back_{contact_id_str}_{admin_msg_id_str}")]]
                await event.edit(response_text, buttons=buttons, parse_mode='html', link_preview=False)

            elif data.startswith("contact_back_"):
                await event.answer()
                # This allows the owner to go back to the initial confirmation prompt
                *_, contact_id_str, admin_msg_id_str = data.split("_")
                previous_replies = await db.get_previous_replies(int(contact_id_str))
                
                prompt_text = f"⚠️ **This query has already been handled {len(previous_replies)} time(s).**\n\nAre you sure you want to send another reply?"
                buttons = [
                    [Button.inline("✔️ Yes, reply again", f"contact_force_reply_{contact_id_str}_{admin_msg_id_str}")],
                    [Button.inline("❌ Cancel", "contact_cancel_reply")],
                    [Button.inline("🔍 Show Reply Details", f"contact_details_{contact_id_str}_{admin_msg_id_str}")]  
                ]
                await event.edit(prompt_text, buttons=buttons)

            elif data.startswith("cancel_session_"):
                try:
                    *_, flow_val, sid = data.split("_", 3)
                    flow = Flow(flow_val)
                    session = await session_manager.get(user_id, flow, sid)
                    session_active = session and session.active
                        
                    msg = await event.get_message()
                    text = telethon_html.unparse(msg.message, msg.entities)
                    text_to_remove = None
                    buttons = msg.buttons

                    for row in buttons:
                        for btn in row:
                            if btn.data and btn.data.decode() == data:
                                row.remove(btn)
                                text_to_remove = btn.text.replace("Cancel: ", "")
                                break
                        if not row:
                            buttons.remove(row)
                    
                    if session_active:
                        await session_manager.expire(user_id, flow, sid)
                        await event.answer(f"✅ Cancelled {text_to_remove}")
                        # if only clear all button is there but all actions have been already cleared individually
                        if len(buttons)==1:
                            await event.edit("<tg-emoji emoji-id='5336985409220001678'>✅</tg-emoji> All pending actions have been cancelled.", parse_mode='html')
                        else:
                            final_text = text.replace(html.escape(text_to_remove), "<s>Cancelled</s>", 1)
                            await event.edit(text=final_text, buttons=buttons, parse_mode='html')
                    else:
                        await event.answer("⛔ This action has already expired or been cancelled.")
                        # if only clear all button is there but all actions have been already cleared individually
                        if len(buttons)==1:
                            await event.edit("<tg-emoji emoji-id='5336985409220001678'>✅</tg-emoji> All pending actions have been cancelled.", parse_mode='html')
                        else:
                            final_text = text.replace(html.escape(text_to_remove), "<s>Already expired/cancelled</s>", 1)
                            await event.edit(text=final_text, buttons=buttons, parse_mode='html')

                except Exception as e:
                    logger.error(f"Error cancelling session from callback: {e}")
                    await event.answer("❌ Could not cancel this action.", alert=True)

            elif data == "cancel_all_input_sessions":
                await event.answer("🧹 Cancelling all pending inputs...")
                active_sessions_with_flow = await self.sessions.get_active_input_sessions(user_id)
                
                if not active_sessions_with_flow:
                    await event.edit("<tg-emoji emoji-id='5336985409220001678'>✅</tg-emoji> No pending actions to cancel.", parse_mode='html')
                    return
                    
                cancelled_count = 0
                for session, flow in active_sessions_with_flow:
                    await session_manager.expire(user_id, flow, session.session_id)
                    cancelled_count += 1
                    
                await event.edit(f"<tg-emoji emoji-id='5336985409220001678'>✅</tg-emoji> Cancelled {cancelled_count} pending {'action' if cancelled_count==1 else 'actions'}.", parse_mode='html')


            # gstats command button handlers
            elif data.startswith("gstats_"):
                if not db.is_owner(user_id):
                    await event.answer("You are not authorized to perform this action.", alert=True)
                    return
                await event.answer()

                action = data.split("_", 1)[1]

                if action == "refresh":
                    message, buttons = await self.templates.get_gstats_message_and_buttons()
                    try:
                        await event.edit(message, buttons=buttons, parse_mode='html')
                    except Exception as e:
                        logger.debug(f"Ignoring gstats refresh error (likely not modified): {e}")
                        pass

                if action == "premium":
                    users = await db.get_gstats_premium_list()
                    content = ""
                    for user in users:
                        expiry = user['expiry_date'].strftime('%Y-%m-%d %H:%M')
                        content += f"• <code>{user['user_id']}</code> (@{user['username'] or 'N/A'}) - Expires: <code>{expiry}</code>\n"
                    await self._gstats_send_list(event, "Active Premium Members", content, "premium_users.txt")

                elif action == "top_users":
                    users = await db.get_gstats_top_users()
                    content = ""
                    for i, user in enumerate(users, 1):
                        content += f"{i}. <code>{user['user_id']}</code> ({html.escape(user['full_name'])}) - <b>{user['total_requests']}</b> requests\n"
                    await self._gstats_send_list(event, "Top 50 Users by Requests", content, "top_users.txt")

                elif action == "admins":
                    users = await db.get_gstats_admins_list()
                    content = ""
                    for user in users:
                        content += f"• <code>{user['user_id']}</code> (@{user['username'] or 'N/A'})\n"
                    await self._gstats_send_list(event, "Admins List", content, "admins.txt")

                elif action == "banned":
                    users = await db.get_gstats_banned_list()
                    content = ""
                    for user in users:
                        ban_date = user['ban_date'].strftime('%Y-%m-%d')
                        content += f"• <code>{user['user_id']}</code> - Banned on <code>{ban_date}</code>\n  Reason: {html.escape(user['reason'])}\n\n"
                    await self._gstats_send_list(event, "Banned Users List", content, "banned_users.txt")

                elif action == "back":
                    message, buttons = await self.templates.get_gstats_message_and_buttons()
                    await event.edit(message, buttons=buttons, parse_mode='html')

            elif data == "cancel_refresh_prompt":
                await event.answer()
                await event.edit("To cancel the ongoing refresh and clear all pending refresh jobs from the queue, please send the command: /cancelrefresh")

            elif data == "cancel_addcache_prompt":
                await event.answer()
                await event.edit("To cancel the ongoing add-cache operation and clear all pending add jobs from the queue, please send the command: /canceladdcache")

            # Handle various confirmations
            elif data.startswith(("confirm_action_", "cancel_action_")):
                if not db.is_owner(user_id):
                    await event.answer("You are not authorized to perform this action.", alert=True)
                    return
                
                await event.answer()

                action, _, action_id = data.split("_", 2)
                if action_id not in self.ctx.pending_actions:
                    await event.edit("This action has expired or is invalid.")
                    return

                if action == "cancel":
                    del self.ctx.pending_actions[action_id]
                    await event.edit("<tg-emoji emoji-id='5336985409220001678'>✅</tg-emoji> Action cancelled.", parse_mode="html")
                    return

                # If action is "confirm"
                pending_action = self.ctx.pending_actions.pop(action_id)

                action_type = pending_action['action_type']

                if action_type in ('broadcast', 'send'):
                    target_ids = pending_action['target_ids']
                    message_to_send = pending_action['message_to_send']
                    text_to_send = pending_action['text_to_send']
                    no_forward = pending_action['no_forward']
                    silent = pending_action['silent']

                    await event.edit(f"🚀 Starting {action_type} to {len(target_ids)} users...")

                    success_count = 0
                    fail_count = 0

                    for target_id in target_ids:
                        try:
                            if text_to_send:
                                await self.ctx.client.send_message(target_id, text_to_send, link_preview=False, silent=silent)
                            elif no_forward:
                                await self.ctx.client.send_message(target_id, message_to_send, silent=silent)
                            else:
                                await self.ctx.client.forward_messages(target_id, message_to_send, silent=silent)
                            success_count += 1
                        except Exception as e:
                            fail_count += 1
                            logger.warning(f"Failed to send message to user {target_id}: {e}")
                        await asyncio.sleep(0.1)

                    # Logging
                    flags_for_db = ""
                    if no_forward:
                        flags_for_db += "-nf"
                    if silent:
                        flags_for_db += "-s"
                    if not flags_for_db:
                        flags_for_db += "none"
                    
                    is_forward = False
                    fwd_chat_id, fwd_msg_id = None, None
                    message_for_db = text_to_send or get_message_content_for_db(message_to_send)

                    if message_to_send and message_to_send.forward:
                        is_forward = True
                        if from_peer := getattr(message_to_send.forward, 'from_id', None):
                            fwd_chat_id = getattr(from_peer, 'channel_id', None) or getattr(from_peer, 'chat_id', None) or getattr(from_peer, 'user_id', None)
                        fwd_msg_id = getattr(message_to_send.forward, 'channel_post', None)

                    if action_type == 'broadcast':
                        await db.log_broadcast(user_id, message_for_db, flags_for_db, len(target_ids), success_count, fail_count, is_forward, fwd_chat_id, fwd_msg_id)
                    elif action_type == 'send':
                        await db.log_send(user_id, message_for_db, flags_for_db, target_ids, success_count, fail_count, is_forward, fwd_chat_id, fwd_msg_id)

                    await event.edit(
                        f"✅ **{action_type.capitalize()} Complete!**\n\n"
                        f"• Sent to: `{success_count}` users\n"
                        f"• Failed for: `{fail_count}` users"
                    )
                    return
                
                elif action_type == 'clearcache_all':
                    packs_to_clear = pending_action['payload']['packs_to_clear']
                    skip_telegram_deletion = pending_action['payload']['skip_telegram_deletion']
                    
                    if skip_telegram_deletion:
                        await event.edit(f"🗑️ Removing **all {len(packs_to_clear)}** cached packs from database, skipping Telegram deletion...")
                    else:
                        await event.edit(f"🗑️ Deleting **all {len(packs_to_clear)}** cached packs from Telegram channels...")
                    
                    results = await self.helpers.delete_multiple_cache(packs_to_clear, skip_telegram_deletion)

                    if skip_telegram_deletion:
                        logger.info(f"Cache Removed from DB! Removed: {results['succeeded']}, Not Found: {results['not_found']}.")
                        message = (f"✅ **Cache Clear Operation Complete!**\n\n"
                        f"• Removed & logged as junk: `{results['succeeded']}`\n"
                        f"• Not found in DB: `{results['not_found']}`")
                    else:
                        logger.info(f"Cache Cleared! Succeeded: {results['succeeded']}, Failed/Junked: {results['failed']}, Not Found: {results['not_found']}.")
                        message = (f"✅ **Cache Clear Operation Complete!**\n\n"
                        f"• Successfully deleted: `{results['succeeded']}`\n"
                        f"• Failed (logged as junk): `{results['failed']}`\n"
                        f"• Not found in DB: `{results['not_found']}`")
                        
                    await event.edit(message)
                    return

                elif action_type == 'clearcache_packs':
                    pack_short_names = pending_action['payload']['pack_short_names']
                    skip_telegram_deletion = pending_action['payload']['skip_telegram_deletion']

                    if skip_telegram_deletion:
                        await event.edit(f"🗑️ Removing **{len(pack_short_names)}** cached packs from database, skipping Telegram deletion...")
                    else:
                        await event.edit(f"🗑️ Deleting **{len(pack_short_names)}** cached packs from Telegram channels...")

                    success_list, fail_list, not_found_list = [], [], []

                    for name in pack_short_names:
                        set_id = await db.get_set_id_by_short_name(name)
                        if not set_id:
                            not_found_list.append(f"• `{name}` (Not in stats DB)")
                            continue
                        
                        result = await self.helpers.delete_cache(set_id, skip_telegram_deletion)
                        if result is True:
                            success_list.append(f"• `{name}`")
                        elif result is False:
                            fail_list.append(f"• `{name}`")
                        else: # None
                            not_found_list.append(f"• `{name}` (Not in cache DB)")

                    
                    response_message = "✅ **Cache Clearing Complete!**\n\n"

                    if skip_telegram_deletion:
                        logger.info(f"Cache Removed from DB! Removed: {len(success_list)}, Not Found: {len(not_found_list)}")
                        if success_list:
                            response_message += f"**Successfully Removed & Logged as Junk:**\n" + "\n".join(success_list) + "\n\n"
                        if not_found_list:
                            response_message += f"**Not Found:**\n" + "\n".join(not_found_list)
                    else:
                        logger.info(f"Cache clear complete! Succeeded: {len(success_list)}, Failed/Junked: {len(fail_list)}, Not Found: {len(not_found_list)}")
                        if success_list:
                            response_message += f"**Successfully Deleted:**\n" + "\n".join(success_list) + "\n\n"
                        if fail_list:
                            response_message += f"**Failed (Logged as Junk):**\n" + "\n".join(fail_list) + "\n\n"
                        if not_found_list:
                            response_message += f"**Not Found:**\n" + "\n".join(not_found_list)
                    
                    await event.edit(response_message[:4000] + "..." if len(response_message) > 4000 else response_message)
                    return
                
                elif action_type in ("refreshcache_top_n", "refreshcache_links"):
                    self.ctx.active_refresh_message = await event.edit("🚀 **Starting Cache Refresh...**\nThis may take a moment to prepare.", buttons=None)
                    original_event_info = pending_action['original_event_info']
                    original_event_info['bot_reply_message_id'] = event.message_id
                    asyncio.create_task(self.execute_refresh_task(action_type, pending_action['payload'], original_event_info))
                    return

                elif action_type in ("addcache_all", "addcache_n", "addcache_links"):
                    self.ctx.active_add_message = await event.edit("🚀 **Starting Add-Cache...**\nThis may take a moment to prepare.", buttons=None)
                    original_event_info = pending_action['original_event_info']
                    original_event_info['bot_reply_message_id'] = event.message_id
                    asyncio.create_task(self.execute_addcache_task(action_type, pending_action['payload'], original_event_info))
                    return

                elif action_type == "addcache_interactive":
                    session = await session_manager.create(
                        user_id=user_id,
                        flow=Flow.ADDCACHE,
                        state='awaiting_addcache_input',
                        single_active=True,
                        ttl_seconds=7200 # 2 hours
                    )
                    await event.edit(
                        "✅ **Interactive Add-Cache Mode is active.**\n\n"
                        "Send sticker packs to add them to the cache. Reply to this message or send them directly.\n"
                        "Send /done when you are finished.", 
                        buttons=None
                    )
                    await session_manager.mark_message(user_id, Flow.ADDCACHE, session.session_id, event.chat_id, event.message_id)
                    return
                
                elif action_type == 'clearjunk':
                    await event.edit("🗑️ Clearing junk file entries from the database...")
                    cleared_count = await db.clear_junk_file_entries()
                    await event.edit(f"✅ Successfully cleared **{cleared_count}** junk file entries from the database.")
                    return
                
                elif action_type == 'shutdown':
                    immediate = pending_action['immediate']
                    call_pm2_stop = pending_action['call_pm2_stop']
                    await event.edit("<tg-emoji emoji-id='5267434641563853196'>🛑</tg-emoji> <b>Stopping the bot...</b>", parse_mode='html')
                    await self.ctx.lc_manager.handle_shutdown(immediate=immediate, call_pm2_stop=call_pm2_stop)
                    return
                elif action_type == 'restart':
                    immediate = pending_action['immediate']
                    call_pm2_restart = pending_action['call_pm2_restart']
                    await event.edit("<tg-emoji emoji-id='5188481279963715781'>🚀</tg-emoji> <b>Restarting the bot...</b>", parse_mode='html')

                    # Save restart info to a temp file in DATA_DIR
                    restart_file = os.path.join(DATA_DIR, "restart_state.json")
                    try:
                        with open(restart_file, "w") as f:
                            json.dump({
                                "chat_id": event.chat_id,
                                "message_id": event.message_id,
                                "timestamp": time.time(),
                                "immediate": immediate,
                                "call_pm2_restart": call_pm2_restart
                            }, f)
                    except Exception as e:
                        logger.error(f"Failed to save restart state: {e}")

                    await self.ctx.lc_manager.handle_restart(immediate=immediate, call_pm2_restart=call_pm2_restart)
                    return
            elif data.startswith("suggest_"):
                await event.answer()
                list_type = data.split('_', 1)[1] # 'daily' or 'all_time'
                
                try:
                    message, buttons = self.templates.format_suggestion_message(list_type)
                    await event.edit(message, buttons=buttons, parse_mode='html', link_preview=False)
                except Exception as e:
                    logger.warning(f"Could not edit the suggest message: {e}")

            elif data.startswith("customize_"):

                parts = data.split("_",2)
                action = parts[1]
                sid = parts[2]

                session = await session_manager.get(user_id, Flow.CUSTOMIZE, sid)
                if not session or not session.active:
                    await event.edit("This customization session has <b>expired</b>. Please send the sticker again.", parse_mode='html')
                    return
                
                payload = session.payload

                if action == "title":
                    await session_manager.update(user_id, Flow.CUSTOMIZE, sid, state='awaiting_custom_title', ttl_seconds=3600)
                    await event.edit(
                        "Okay, send me the new <b>title</b> for your sticker pack (max 50 characters).",
                        buttons=[[Button.inline("Back", f"customize_back_{sid}", style="primary", icon=5877629862306385808)]],
                        parse_mode='html'
                    )
                    await session_manager.mark_message(user_id, Flow.CUSTOMIZE, sid, event.chat_id, event.message_id)

                elif action == "author":
                    await session_manager.update(user_id, Flow.CUSTOMIZE, sid, state='awaiting_custom_author', ttl_seconds=3600)
                    await event.edit(
                        "Sure, send me the <b>author name</b> you'd like to use (max 30 characters).",
                        buttons=[[Button.inline("Back", f"customize_back_{sid}", style="primary", icon=5877629862306385808)]], 
                        parse_mode='html'
                    )
                    await session_manager.mark_message(user_id, Flow.CUSTOMIZE, sid, event.chat_id, event.message_id)

                elif action == "back":
                    await event.answer()
                    await session_manager.update(user_id, Flow.CUSTOMIZE, sid, state='awaiting_customization_choice', ttl_seconds=3600)
                    await self.helpers.update_customization_prompt(user_id, session)

                elif action == "cancel":
                    await session_manager.expire(user_id, Flow.CUSTOMIZE, sid)
                    await event.edit("<tg-emoji emoji-id='5336985409220001678'>✅️</tg-emoji> Conversion cancelled.", buttons=None, parse_mode='html')

                elif action == "convert":
                    # We need the original event object for the queue manager
                    asyncio.create_task(self.helpers.delete_multiple_messages(event.chat_id, payload['failed_inputs'], "Failed to delete invalid customization input messages.")) # clear any invalid input messaages

                    current_queue_count = await queue_manager.get_user_queue_count(user_id)
                    limit = MAX_CONCURRENT_PREMIUM_REQUESTS

                    # max queue limit
                    if current_queue_count >= limit:
                        message = (f"⏳ You've reached your limit!\n\n"
                                f"You currently have {current_queue_count}/{limit} items in the queue. "
                                f"Please wait for one to complete before adding more.")

                        await event.answer(message, alert=True)
                        return
                    await event.answer()

                    original_event_info = payload['original_event_info']
                    sticker_set_info = payload['sticker_set_info']
                    if not (payload['custom_title'] or payload['custom_author']):
                        if self.ctx.cache_enabled and await self.check_cache(original_event_info['chat_id'], original_event_info['user_id'], original_event_info['message_id'], sticker_set_info):
                            await session_manager.expire(user_id, Flow.CUSTOMIZE, sid)
                            await event.delete()
                            return
                    
                    
                    await self._queue_sticker_pack(
                        original_event_info,
                        sticker_set_info,
                        is_premium=True,
                        custom_title=payload['custom_title'],
                        custom_author=payload['custom_author']
                    )
                    await session_manager.expire(user_id, Flow.CUSTOMIZE, sid)
                    await event.delete()

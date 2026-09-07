"""
Configuration file for various settings of the bot. 
"""
import html
import os
import json
import math
from dotenv import load_dotenv

load_dotenv()

# Telegram API things (its must )
API_ID = int(os.getenv("API_ID"))
API_HASH = os.getenv("API_HASH")
BOT_TOKEN = os.getenv("BOT_TOKEN")

# user id of owner and system
OWNER_ID = int(os.getenv("OWNER_ID")) # The owner
SYSTEM_USER_ID = 0

# ----- Premium Pricing Configuration ------
PREMIUM_PRICE_MONTHLY = 0.5
PREMIUM_PRICE_YEARLY = 5
PREMIUM_SAVINGS_PERCENT = math.floor((1 - (PREMIUM_PRICE_YEARLY / (PREMIUM_PRICE_MONTHLY * 12))) * 100)

# ----- Telegram Stars Pricing ------
PREMIUM_STARS_MONTHLY = 20   # Approximate equivalent of $0.50
PREMIUM_STARS_YEARLY = 200   # Approximate equivalent of $5.00

# ------ Links ------
SOURCE_CODE_LINK = "https://github.com/not-right-now/Telegram-to-WhatsApp-Stickers"
TGS_TO_WEBP_MODULE_LINK = "https://github.com/not-right-now/tgs_to_webp"
VIDEO_TO_WEBP_MODULE_LINK = "https://github.com/not-right-now/video_to_webp"

# ------ Conversion Limits ------
DAILY_LIMIT_REGULAR = 10 # (< 0 for unlimited)
DAILY_LIMIT_PREMIUM = 100 # (< 0 for unlimited)
MAX_CONCURRENT_REGULAR_REQUESTS = 1 
MAX_CONCURRENT_PREMIUM_REQUESTS = 3

#----- Timeouts and processing limits -------
# adjust according to your machine's internet speed and performance
DOWNLOAD_TIMEOUT = 10  # seconds to wait for a single sticker/emoji file to download (remmember 30 stickers are downloaded parallely at a time)
UPLOAD_TIMEOUT = 30    # seconds to wait for a .wastickers file to upload
ESTIMATED_TIME_MULTIPLIER = 3 # how many times of calculated estimated time should bot wait for the conversion of the pack
MAX_CONVERSION_SECONDS_REGULAR = 300  # 5 minutes. Max estimated time for non-premium users
DB_UPLOAD_TIMEOUT = 30
DB_DUMP_TIMEOUT = 30
MAX_DOWNLOAD_RETRIES = 2
MAX_UPLOAD_RETRIES = 2
CONVERSION_TIMEOUT = 30 # seconds to wait for a single sticker conversion process

# ------- Database Credentials -------
DB_NAME = os.getenv("DB_NAME")
DB_USER = os.getenv("DB_USER")
DB_PASSWORD = os.getenv("DB_PASSWORD")
DB_HOST = os.getenv("DB_HOST")
DB_PORT = os.getenv("DB_PORT")

# ------File paths ---------- 
DATA_DIR = "storage/data"
TEMP_DIR = "storage/temp"
OUTPUT_DIR = "storage/output"
LOG_DIR = "storage/logs" # for /getlogs command and log backups

# ------ Cache settings ----------
CACHE_ENABLED = True # To use cache or not, owner can change it using the bot too but on bot restarts it will change to this default value
COUNT_CACHE_HITS_AS_REQUESTS = True # If True cache hits count towards user's daily conversion quota
CACHE_SCORE_TIME_WEIGHT = 1.5   # Weight for conversion duration (in seconds)
CACHE_SCORE_REQUEST_WEIGHT = 1 # Weight for the number of times a pack is requested
MAX_FILES_PER_CACHE_CHANNEL = 95000
cache_ids_str = os.getenv("CACHE_CHANNEL_IDS", "")
CACHE_CHANNEL_IDS = [int(channel_id) for channel_id in cache_ids_str.split(',') if channel_id.strip()]

# ----- Links ----------
WHY_SPLIT_LINK = "https://telegra.ph/Why-Multiple-Packs-08-31"

# ------ support group and required channels/groups ----------
# Support group for bot related queries (will be used in help message)
def _normalize_link(l: str) -> str:
    l = l.strip()
    if l.startswith(('https://', 'http://', 'tg://')):
        return l
    if l.startswith(('t.me/', 'telegram.me/')):
        return f"https://{l}"
    return f"https://t.me/{l.lstrip('@')}"
SUPPORT_GROUP = os.getenv("SUPPORT_GROUP")
SUPPORT_GROUP_LINK = _normalize_link(SUPPORT_GROUP)
# should be in format like ("Name", "@username", -12345675678) or ("Name", "link", -1212324141)
REQUIRED_CHANNELS = json.loads(os.getenv("REQUIRED_CHANNELS_JSON"))

# formatting properly for use
try:
    REQUIRED_CHANNELS_FORMATTED = [
        (type_str, name, _normalize_link(link), id) for (type_str, name, link, id) in REQUIRED_CHANNELS
    ]
except Exception as e:
    print(f"Error parsing REQUIRED_CHANNELS_JSON please re-run the env setup script. Error: {e}")
    exit(1)

channel_len = len(REQUIRED_CHANNELS_FORMATTED)
chat_types = ''
_channel_clickable_str = ''
if channel_len == 1:
    chat_types = 'channel' if REQUIRED_CHANNELS_FORMATTED[0][0] == 'channel' else 'group'
    # single channel clickable string
    _channel_clickable_str = f"<b><a href='{REQUIRED_CHANNELS_FORMATTED[0][2]}'>{html.escape(REQUIRED_CHANNELS_FORMATTED[0][1])}</a></b>"
elif channel_len > 1:
    chat_types = 'channels' if all(channel[0] == 'channel' for channel in REQUIRED_CHANNELS_FORMATTED) else 'groups' if all(channel[0] == 'group' for channel in REQUIRED_CHANNELS_FORMATTED) else 'channels/groups'
    # Channel list converted to string 
    _channel_clickable_str = "\n".join([f"• <b><a href=\"{channel[2]}\">{html.escape(channel[1])}</a></b>" for channel in REQUIRED_CHANNELS_FORMATTED])



# ------- Notification Settings --------

# The chat ID of the group where all notifications will be sent. Must be a negative number for groups.
# Get it by sending group to @username_to_id_bot
NOTIFICATION_GROUP_ID = int(os.getenv("NOTIFICATION_GROUP_ID"))
# A list of admin/owner user IDs to mention in critical notifications.
admins_str = os.getenv("ADMINS_TO_MENTION")
if admins_str:
    ADMINS_TO_MENTION = [int(admin_id) for admin_id in admins_str.split(',') if admin_id.strip()]
else:
    ADMINS_TO_MENTION = [OWNER_ID] # Default to the owner if not set


NOTIFICATIONS = {
    # For conversion failures during processing.
    "conversion_failure": {
        "enabled": True,
        "mention_admins": True,
    },
    # For unhandled exceptions that could crash a background task. I recommend you better keep it on.
    "uncaught_exception": {
        "enabled": True,
        "mention_admins": True,
    },
    # For new premium purchases.
    "premium_purchase_success": {
        "enabled": True,
        "mention_admins": True,
    },
    # For when the bot fails to add premium after successful payment.
    "premium_grant_failed": {
        "enabled": True,
        "mention_admins": True,
    },
    # For when caching is enabled but all cache channels are full.
    "cache_channels_full": {
        "enabled": True,
        "mention_admins": True,
    },
    # For when the bot fails to delete files from a cache channel.
    "cache_delete_failure": {
        "enabled": False,
        "mention_admins": False,
    },
    # For any other message deletion failures. Can be messsy so disabled by default.(change if you care for everything)
    "message_delete_failure": {
        "enabled": False,
        "mention_admins": False,
    }
}

# ------- Backup Settings --------

BACKUP_ENABLED = True # Master switch for all backups

# The chat ID for backups is the same as NOTIFICATION_GROUP_ID by default.
# You can override it here if you want a separate channel for backups.
BACKUP_GROUP_ID = NOTIFICATION_GROUP_ID

BACKUPS = {
    "database": {
        "enabled": True, # Toggle for database backups
    },
    "logs": {
        "enabled": True, # Toggle for log file backups
    }
}

# ========== Sticker/emoji pack constraints ==========
# Warning: dont change these unless you know what you are doing
MAX_STICKERS_PER_PACK = 30
MAX_STATIC_WEBP_SIZE_KB = 99 # maximum size of each static WEBP sticker in kilobytes
MAX_ANIMATED_WEBP_SIZE_KB = 495 # maximum size of each animated WEBP sticker in kilobytes
MAX_WEBP_FRAMES = 30 # frame cap for a WEBP sticker
TGS_QUALITY = 10  # Default quality for tgs files
WEBM_QUALITY = 80  # Default quality for webm files
STATIC_QUALITY = 80  # Default quality for static files
MAX_ICON_SIZE = 50 * 1024      # 50KB
STICKER_DIMENSIONS = (512, 512)
ICON_DIMENSIONS = (96, 96)


#================ Messages ===============
_safe_clickable_str = _channel_clickable_str.replace('{', '{{').replace('}', '}}')

START_MESSAGE_FORMAT = (
f"""<tg-emoji emoji-id="5472427507842032538">🎉</tg-emoji> <b>Welcome to <a href='https://t.me/{{bot_username}}'>{{bot_name}}</a></b>

I can convert any <b>Telegram sticker or emoji pack</b> directly into <b>WhatsApp stickers</b> for you. <tg-emoji emoji-id="5334998226636390258">✅</tg-emoji>

<b>To get started, you can either:</b>
• Send me a sticker or emoji pack link
• Or just send a sticker or emoji from the pack you want.

For a full guide on features and how to import the stickers to WhatsApp, please use the /help command.""" 
+ 
(f"\n\n<tg-emoji emoji-id='5447644880824181073'>⚠️</tg-emoji> <b>Note:</b> You must be a member of {_safe_clickable_str} to use this bot" if channel_len == 1 else
f"""\n\n<tg-emoji emoji-id="5447644880824181073">⚠️</tg-emoji> <b>Note:</b> You must be a member of following {chat_types} to use this bot:
{_safe_clickable_str}""" if channel_len > 1 else "")
)

HELP_MESSAGE_FALLBACK = f"""
<tg-emoji emoji-id="5388953246486269495">📖</tg-emoji> <b>Help Guide</b>

<tg-emoji emoji-id="5785045099142450328">🤔</tg-emoji> <b>How to Convert a Pack?</b>
You have two simple options:
<blockquote>1.  <b>Send a Link</b>: Copy the sticker or emoji pack's link and send it to me.</blockquote>
<blockquote>2.  <b>Send a Sticker/Emoji</b>: Just send any sticker or emoji from the pack you want. I'll handle the rest.</blockquote>

---

<tg-emoji emoji-id="5334998226636390258">👉</tg-emoji> <b>How to Add Stickers to WhatsApp</b>

1. <tg-emoji emoji-id="5256186019136421048">📱</tg-emoji> <b>Install the App</b>: 
<blockquote>You'll need a helper app. We recommend <b>Sticker Maker</b>.

<tg-emoji emoji-id="5386533208508609398">🔗</tg-emoji> <b>Play Store</b>: <b><a href="https://play.google.com/store/apps/details?id=com.marsvard.stickermakerforwhatsapp">Click here</a></b>
<tg-emoji emoji-id="5384144180194848649">🔗</tg-emoji> <b>App Store</b>: <b><a href="https://apps.apple.com/us/app/sticker-maker-studio/id1443326857">Click here</a></b>
</blockquote>
2.  <tg-emoji emoji-id="5258134813302332906">📂</tg-emoji> <b>Open the File</b>: 
<blockquote>Once I send you the <code>.wastickers</code> file, tap on it here in Telegram.
</blockquote>
3.  <tg-emoji emoji-id="5258336354642697821">⬇️</tg-emoji> <b>Import</b>: 
<blockquote>Choose to open the file with the <b>Sticker Maker</b> app. Inside the app, tap "Add to my library" and then "Add to WhatsApp".
</blockquote>
That's it, your stickers are ready!

---

<tg-emoji emoji-id="5418077986656112171">✨</tg-emoji> <b>Explore More Features</b>
<blockquote>• Use /commands to see a full list of all available commands.
• Use /premium to check your premium status and learn about the benefits.</blockquote>

---

<tg-emoji emoji-id="6037579284837567462">📋</tg-emoji> <b>Important Notes</b>

• Packs with more than 30 stickers will be split into multiple files since WhatsApp supports only 30 stickers per pack.

<tg-emoji emoji-id="5256143829672672750">⏱️</tg-emoji> <b>Queue System</b>

• During busy times, your request is placed in a queue to ensure fair processing.
• You can check your position at any time using the /queue command.
• <tg-emoji emoji-id="6080171114007367607">⭐</tg-emoji> Premium users get priority and are moved to the front of the line!


<tg-emoji emoji-id="5443038326535759644">💬</tg-emoji> <b>Support</b>

If you run into any issues or have questions, please join our support group for assistance.
<blockquote><b>Support Group</b>: <b>{SUPPORT_GROUP}</b></blockquote>

"""

HELP_MESSAGE_RICH = \
f"""<h1><tg-emoji emoji-id="5388953246486269495">📖</tg-emoji> <strong>Help Guide</strong></h1>
<hr>
<details>
    <summary><tg-emoji emoji-id="5785045099142450328">🤔</tg-emoji> <strong>How to Convert a Pack?</strong></summary>
    <p>You have two simple options:</p>
    <ol>
        <li><strong>Send a Link</strong>: Copy the sticker or emoji pack&#39;s link and send it to me.</li>
        <li><strong>Send a Sticker/Emoji</strong>: Just send any sticker or emoji from the pack you want.</li>
    </ol>
    <p>I&#39;ll handle the rest!</p>
</details>
<details>
    <summary><tg-emoji emoji-id="5334998226636390258">👉</tg-emoji> <strong>How to Add Stickers to WhatsApp</strong>
    </summary>
    <ol>
        <li>
            <p><tg-emoji emoji-id="5256186019136421048">📱</tg-emoji> <strong>Install the App:</strong><br>
                <br>
                You&#39;ll need a helper app. We recommend <strong>Sticker Maker</strong>.
            </p>
            <p><tg-emoji emoji-id="5386533208508609398">🔗</tg-emoji> <strong>Play Store</strong>: <strong><a
                        href="https://play.google.com/store/apps/details?id=com.marsvard.stickermakerforwhatsapp">Click
                        here</a></strong><br>
                <tg-emoji emoji-id="5384144180194848649">🔗</tg-emoji> <strong>App Store</strong>: <strong><a
                        href="https://apps.apple.com/us/app/sticker-maker-studio/id1443326857">Click here</a></strong>
            </p>
        </li>
        <li>
            <p><tg-emoji emoji-id="5258134813302332906">📂</tg-emoji> <strong>Open the File with Sticker Maker:</strong></p>
            <ol>
                <li>Once I send you the .wastickers file, tap on it here in Telegram.</li>
                <li>Choose to open the file with the <strong>Sticker Maker</strong> app.</li>
            </ol>
        </li>
        <li>
            <p><tg-emoji emoji-id="5258336354642697821">⬇️</tg-emoji> <strong>Import:</strong></p>
            <ol>
                <li>Inside the sticker maker app, tap &quot;Add to my library&quot;.</li>
                <li>Then &quot;Add to WhatsApp&quot;.</li>
            </ol>
        </li>
    </ol>
    <p>That&#39;s it, your stickers are ready!</p>
</details>
<details>
    <summary><tg-emoji emoji-id="6037579284837567462">📋</tg-emoji> <strong>Important Notes</strong></summary>
    <ul>
        <li>Packs with more than 30 stickers will be split into multiple files since WhatsApp supports only 30 stickers
            per pack.</li>
        <li>During busy times, your request is placed in a queue to ensure fair processing.</li>
        <li><tg-emoji emoji-id="6080171114007367607">⭐</tg-emoji> Premium users get priority and are served first!</li>
    </ul>
</details>
<details>
    <summary><tg-emoji emoji-id="5418077986656112171">✨</tg-emoji> <strong>Explore More Features</strong></summary>
    <ul>
        <li>Use /commands to see a full list of all available commands.</li>
        <li>Use /premium to check your premium status and learn about the benefits.</li>
        <li>You can check your position at any time using the /queue command</li>
    </ul>
</details>
<details>
    <summary><tg-emoji emoji-id="5443038326535759644">💬</tg-emoji> <strong>Support</strong></summary>
    <p>If you run into any issues or have questions, please join our support group for assistance.</p>
    <blockquote><strong>Support Group</strong>: <strong><a href="{SUPPORT_GROUP_LINK}">{SUPPORT_GROUP}</a></strong>
    </blockquote>
</details>"""

HELP_IMPORT_MESSAGE = \
"""<h2><tg-emoji emoji-id="5334998226636390258">👉</tg-emoji> <strong>How to Add Stickers to WhatsApp</strong></h2>
<ol>
    <li>
        <p><tg-emoji emoji-id="5256186019136421048">📱</tg-emoji> <strong>Install the App</strong>:<br>
            <br>
            You&#39;ll need a helper app. We recommend <strong>Sticker Maker</strong>.
        </p>
        <p><tg-emoji emoji-id="5386533208508609398">🔗</tg-emoji> <strong>Play Store</strong>: <strong><a
                    href="https://play.google.com/store/apps/details?id=com.marsvard.stickermakerforwhatsapp">Click
                    here</a></strong><br>
            <tg-emoji emoji-id="5384144180194848649">🔗</tg-emoji> <strong>App Store</strong>: <strong><a
                    href="https://apps.apple.com/us/app/sticker-maker-studio/id1443326857">Click here</a></strong>
        </p>
        <hr>
    </li>
    <li>
        <p><tg-emoji emoji-id="5258134813302332906">📂</tg-emoji> <strong>Open the File</strong> <strong>with Sticker
                Maker</strong>: </p>
        <ol>
            <li>Once I send you the .wastickers file, tap on it here in Telegram.</li>
            <li>Choose to open the file with the <strong>Sticker Maker</strong> app.</li>
        </ol>
        <hr>
    </li>
    <li>
        <p><tg-emoji emoji-id="5258336354642697821">⬇️</tg-emoji> <strong>Import</strong>:</p>
        <ol>
            <li>Inside the sticker maker app, tap &quot;Add to my library&quot;.</li>
            <li>Then &quot;Add to WhatsApp&quot;.</li>
        </ol>
        <hr>
    </li>
</ol>
<p>That&#39;s it, your stickers are ready!</p>
<details>
    <summary><tg-emoji emoji-id="5370724846936267183">🤔</tg-emoji> <strong>Why multiple packs?</strong></summary>
    <p>Packs with more than 30 stickers will be split into multiple files since <strong>WhatsApp supports only 30
            stickers per pack</strong>.</p>
</details>"""

QUEUE_CHECK_MESSAGE = "<tg-emoji emoji-id='5258513401784573443'>📊</tg-emoji> <b>Queue Status</b>\n\nYour position: {position}\nTotal in queue: {total}"

CHANNEL_JOIN_MESSAGE = (
f"""<tg-emoji emoji-id="5843952899184398024">❌</tg-emoji> <b>Access Denied!</b>

To use this bot, you must join {_channel_clickable_str} first.

After joining try again!""" if channel_len == 1 else

f"""<tg-emoji emoji-id="5843952899184398024">❌</tg-emoji> <b>Access Denied!</b>

To use this bot, you must join these {chat_types} first:
{_channel_clickable_str}

After joining try again!""" if channel_len > 1 else "")

COMMANDS_MESSAGE = """
<tg-emoji emoji-id="5258093637450866522">🤖</tg-emoji> <b>Here are the commands you can use:</b>

• /start - <tg-emoji emoji-id="6041921818896372382">👋</tg-emoji> Displays the welcome message.
• /help - <tg-emoji emoji-id="6030848053177486888">📖</tg-emoji> Shows the detailed help guide.
• /queue - <tg-emoji emoji-id="6032609071373226027">👥</tg-emoji> Checks your current position in the conversion queue.
• /mystats - <tg-emoji emoji-id="5936143551854285132">📊</tg-emoji> Shows your usage statistics and current role.
• /premium - <tg-emoji emoji-id="5886685105065300941">⭐</tg-emoji> Displays your premium status and its benefits.
• /commands - <tg-emoji emoji-id="6028435952299413210">⚙️</tg-emoji> Shows a list of Available Commands
• /suggest - <tg-emoji emoji-id="6037533152593842454">✨</tg-emoji> Get recommendations for popular packs.
• /contact - <tg-emoji emoji-id="6037421444789440735">📩</tg-emoji> Send a message to the bot administrators.

Just send any of these commands to get started!
"""

CONTACT_PROMPT_MESSAGE = """
<tg-emoji emoji-id="5447644880824181073">⚠️</tg-emoji> <b>Contact an Admin</b>

This will forward your next message to the entire admin team. Please be patient for a response.

<b>Please Note:</b>
- This feature is for genuine queries and feedback only.
- Abusing this feature for spam may result in a ban.
"""

CONTACT_SUCCESS_MESSAGE = '<tg-emoji emoji-id="5336985409220001678">✅</tg-emoji> <b>Message Sent!</b>\n\nYour message has been forwarded to the admin team. If a reply is needed, they will contact you directly through me.'

CONTACT_FAILURE_MESSAGE = '<tg-emoji emoji-id="5019523782004441717">❌</tg-emoji> <b>Failed to Send Message!</b>\n\nYour message could not be forwarded to the admin team. Please try again later.'

CONTACT_ADMIN_REPLY_HEADER = '<tg-emoji emoji-id="5406631276042002796">📨</tg-emoji> <b>A reply from the admin team <tg-emoji emoji-id="4992796097442218769">👇</tg-emoji></b>'

CONTACT_ADMIN_NOTIFICATION_HEADER = """
<tg-emoji emoji-id="5253742260054409879">📩</tg-emoji> <b>New User Message</b>

<tg-emoji emoji-id="5258503720928288433">📄</tg-emoji> <b>Contact ID:</b> <code>{contact_id}</code>
<tg-emoji emoji-id="5258011929993026890">👤</tg-emoji> <b>From:</b> {user_display_name}
- <b>User ID:</b> <code>{user_id}</code>
- <b>Status:</b> {role}
- <b>Stats:</b>
<tg-emoji emoji-id="5260416304224936047">✅</tg-emoji> Succeeded: <code>{succeeded}</code>
<tg-emoji emoji-id="5260342697075416641">❌</tg-emoji> Failed: <code>{failed}</code>
<tg-emoji emoji-id="5258318620722733379">🚫</tg-emoji> Cancelled: <code>{cancelled}</code>
<tg-emoji emoji-id="5258330865674494479">📍</tg-emoji> Total: <code>{total}</code>
"""

AFTER_SUCCESSFUL_CONVERSION_MESSAGE = """<tg-emoji emoji-id='5386506901833921374'>📱</tg-emoji> To import to WhatsApp, use '<b>Sticker Maker</b>' app on your phone.
<tg-emoji emoji-id='5386533208508609398'>🔗</tg-emoji> <b>Play Store</b>: <b><a href='https://play.google.com/store/apps/details?id=com.marsvard.stickermakerforwhatsapp'>Click here</a></b>
<tg-emoji emoji-id='5384144180194848649'>🔗</tg-emoji> <b>App Store</b>: <b><a href='https://apps.apple.com/us/app/sticker-maker-studio/id1443326857'>Click here</a></b>

Use the buttons below for detailed steps or to report any issues you encounter. Enjoy :)"""
from re import match as re_match, findall as re_findall
from threading import Thread, Event
from time import time
from math import ceil
from html import escape
from psutil import virtual_memory, cpu_percent, disk_usage
from requests import head as rhead
from urllib.request import urlopen
from telegram import InlineKeyboardMarkup

from bot.helper.telegram_helper.bot_commands import BotCommands
from bot import FINISHED_PROGRESS_STR, UN_FINISHED_PROGRESS_STR, download_dict, download_dict_lock, STATUS_LIMIT, botStartTime, DOWNLOAD_DIR, WEB_PINCODE, BASE_URL
from bot.helper.telegram_helper.button_build import ButtonMaker

import psutil
from telegram.error import RetryAfter
from telegram.ext import CallbackQueryHandler
from telegram.message import Message
from telegram.update import Update
from bot import *

MAGNET_REGEX = r"magnet:\?xt=urn:btih:[a-zA-Z0-9]*"

URL_REGEX = r"(?:(?:https?|ftp):\/\/)?[\w/\-?=%.]+\.[\w/\-?=%.]+"

COUNT = 0
PAGE_NO = 1


class MirrorStatus:
    STATUS_UPLOADING = "Uploading...📤"
    STATUS_DOWNLOADING = "Downloading...📥"
    STATUS_CLONING = "Cloning...♻️"
    STATUS_WAITING = "Queued...💤"
    STATUS_PAUSED = "Paused...⛔️"
    STATUS_ARCHIVING = "Archiving...🔐"
    STATUS_EXTRACTING = "Extracting...📂"
    STATUS_SPLITTING = "Splitting...✂️"
    STATUS_CHECKING = "CheckingUp...📝"
    STATUS_SEEDING = "Seeding...🌧"


class EngineStatus:
    STATUS_ARIA = "Aria2c v1.35.0"
    STATUS_GD = "Google Api v2.51.0"
    STATUS_MEGA = "MegaSDK v3.12.0"
    STATUS_QB = "qBittorrent v4.3.9"
    STATUS_TG = "Pyrogram v2.0.27"
    STATUS_YT = "YT-dlp v22.5.18"
    STATUS_EXT = "Extract | pExtract"
    STATUS_SPLIT = "FFmpeg v2.9.1"
    STATUS_ZIP = "p7zip v16.02"


SIZE_UNITS = ['B', 'KB', 'MB', 'GB', 'TB', 'PB']

PROGRESS_MAX_SIZE = 100 // 9
PROGRESS_INCOMPLETE = ['◔', '◔', '◑', '◑', '◑', '◕', '◕']


class setInterval:
    def __init__(self, interval, action):
        self.interval = interval
        self.action = action
        self.stopEvent = Event()
        thread = Thread(target=self.__setInterval)
        thread.start()

    def __setInterval(self):
        nextTime = time() + self.interval
        while not self.stopEvent.wait(nextTime - time()):
            nextTime += self.interval
            self.action()

    def cancel(self):
        self.stopEvent.set()


def get_readable_file_size(size_in_bytes) -> str:
    if size_in_bytes is None:
        return '0B'
    index = 0
    while size_in_bytes >= 1024:
        size_in_bytes /= 1024
        index += 1
    try:
        return f'{round(size_in_bytes, 2)}{SIZE_UNITS[index]}'
    except IndexError:
        return 'File too large'


def getDownloadByGid(gid):
    with download_dict_lock:
        for dl in list(download_dict.values()):
            dl.status()
            if dl.gid() == gid:
                return dl
    return None


def getAllDownload(req_status: str):
    with download_dict_lock:
        for dl in list(download_dict.values()):
            status = dl.status()
            if req_status in ['all', status]:
                return dl
    return None


def bt_selection_buttons(id_: str):
    if len(id_) > 20:
        gid = id_[:12]
    else:
        gid = id_

    pincode = ""
    for n in id_:
        if n.isdigit():
            pincode += str(n)
        if len(pincode) == 4:
            break

    buttons = ButtonMaker()
    if WEB_PINCODE:
        buttons.buildbutton("Select Files", f"{BASE_URL}/app/files/{id_}")
        buttons.sbutton("Pincode", f"btsel pin {gid} {pincode}")
    else:
        buttons.buildbutton(
            "Select Files",
            f"{BASE_URL}/app/files/{id_}?pin_code={pincode}")
    buttons.sbutton("Done Selecting", f"btsel done {gid} {id_}")
    return InlineKeyboardMarkup(buttons.build_menu(2))


def get_progress_bar_string(status):
    completed = status.processed_bytes() / 8
    total = status.size_raw() / 8
    p = 0 if total == 0 else round(completed * 100 / total)
    p = min(max(p, 0), 100)
    cFull = p // 8
    cPart = p % 8 - 1
    p_str = '⬤' * cFull
    if cPart >= 0:
        p_str += PROGRESS_INCOMPLETE[cPart]
    p_str += '○' * (PROGRESS_MAX_SIZE - cFull)
    p_str = f"「{p_str}」"
    return p_str


def progress_bar(percentage):
    p_used = '⬢'
    p_total = '⬡'
    if isinstance(percentage, str):
        return 'NaN'
    try:
        percentage = int(percentage)
    except BaseException:
        percentage = 0
    return ''.join(
        p_used if i <= percentage // 10 else p_total for i in range(1, 11)
    )


def get_readable_message():
    with download_dict_lock:
        msg = ""
        if STATUS_LIMIT is not None:
            tasks = len(download_dict)
            global pages
            pages = ceil(tasks / STATUS_LIMIT)
            if PAGE_NO > pages and pages != 0:
                globals()['COUNT'] -= STATUS_LIMIT
                globals()['PAGE_NO'] -= 1
        for index, download in enumerate(
                list(download_dict.values())[COUNT:], start=1):
            msg += f"<b>Name:</b> <code>{escape(str(download.name()))}</code>"
            msg += f"\n<b>╭Status:</b> <i>{download.status()}</i>"
            if download.status() not in [
                    MirrorStatus.STATUS_SPLITTING,
                    MirrorStatus.STATUS_SEEDING]:
                msg += f"\n<b>├</b>{get_progress_bar_string(download)} {download.progress()}"
                if download.status() in [MirrorStatus.STATUS_DOWNLOADING,
                                         MirrorStatus.STATUS_WAITING,
                                         MirrorStatus.STATUS_PAUSED]:
                    msg += f"\n<b>├Downloaded:</b> {get_readable_file_size(download.processed_bytes())} of {download.size()}"
                elif download.status() == MirrorStatus.STATUS_UPLOADING:
                    msg += f"\n<b>├Uploaded:</b> {get_readable_file_size(download.processed_bytes())} of {download.size()}"
                elif download.status() == MirrorStatus.STATUS_CLONING:
                    msg += f"\n<b>├Cloned:</b> {get_readable_file_size(download.processed_bytes())} of {download.size()}"
                elif download.status() == MirrorStatus.STATUS_ARCHIVING:
                    msg += f"\n<b>├Archived:</b> {get_readable_file_size(download.processed_bytes())} of {download.size()}"
                elif download.status() == MirrorStatus.STATUS_EXTRACTING:
                    msg += f"\n<b>├Extracted:</b> {get_readable_file_size(download.processed_bytes())} of {download.size()}"
                msg += f"\n<b>├Speed:</b> {download.speed()}"
                msg += f"\n<b>├ETA:</b> {download.eta()}"
                msg += f"\n<b>├Elapsed: </b>{get_readable_time(time() - download.message.date.timestamp())}"
                msg += f"\n<b>├Engine :</b> {download.eng()}"
                msg += f"\n<b>├Warn: </b> <code>/warn {download.message.from_user.id}</code>"
                try:
                    msg += f"\n<b>├Seeders:</b> {download.aria_download().num_seeders}" \
                           f" | <b>🧲 Peers:</b> {download.aria_download().connections}"
                except BaseException:
                    pass
                try:
                    msg += f"\n<b>├Seeders:</b> {download.torrent_info().num_seeds}" \
                           f" | <b>🧲 Leechers:</b> {download.torrent_info().num_leechs}"
                except BaseException:
                    pass
                if download.message.chat.type != 'private':
                    try:
                        chatid = str(download.message.chat.id)[4:]
                        msg += f'\n<b>├Source: </b><a href="https://t.me/c/{chatid}/{download.message.message_id}">{download.message.from_user.first_name}</a> | <b>Id :</b> <code>{download.message.from_user.id}</code>'
                    except BaseException:
                        pass
                else:
                    msg += f'\n<b>├User:</b> ️<code>{download.message.from_user.first_name}</code> | <b>Id:</b> <code>{download.message.from_user.id}</code>'

            elif download.status() == MirrorStatus.STATUS_SEEDING:
                msg += f"\n<b>├Size: </b>{download.size()}"
                msg += f"\n<b>├Engine:</b> <code>qBittorrent v4.4.2</code>"
                msg += f"\n<b>├Speed: </b>{get_readable_file_size(download.torrent_info().upspeed)}/s"
                msg += f" | <b>🔺Uploaded: </b>{get_readable_file_size(download.torrent_info().uploaded)}"
                msg += f"\n<b>├Ratio: </b>{round(download.torrent_info().ratio, 3)}"
                msg += f" | <b>├Time: </b>{get_readable_time(download.torrent_info().seeding_time)}"
                msg += f"\n<b>├Elapsed: </b>{get_readable_time(time() - download.message.date.timestamp())}"
            else:
                msg += f"\n<b>├Engine :</b> {download.eng()}"
                msg += f"\n<b>├Size: </b>{download.size()}"
                #msg += f"\n<b>▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬</b>"
            msg += f"\n<b>╰Cancel: </b><code>/{BotCommands.CancelMirror} {download.gid()}</code>"
            msg += f"\n<b>▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬</b>"
            msg += "\n\n"
            if STATUS_LIMIT is not None and index == STATUS_LIMIT:
                break
        if len(msg) == 0:
            return None, None
        bmsg = f"<b>🖥 CPU:</b> {cpu_percent()}% | <b>💿 FREE:</b> {get_readable_file_size(disk_usage(DOWNLOAD_DIR).free)}"
        bmsg += f"\n<b>🎮 RAM:</b> {virtual_memory().percent}% | <b>🟢 ONLINE:</b> {get_readable_time(time() - botStartTime)}"
        dlspeed_bytes = 0
        upspeed_bytes = 0
        for download in list(download_dict.values()):
            spd = download.speed()
            if download.status() == MirrorStatus.STATUS_DOWNLOADING:
                if 'K' in spd:
                    dlspeed_bytes += float(spd.split('K')[0]) * 1024
                elif 'M' in spd:
                    dlspeed_bytes += float(spd.split('M')[0]) * 1048576
            elif download.status() == MirrorStatus.STATUS_UPLOADING:
                if 'KB/s' in spd:
                    upspeed_bytes += float(spd.split('K')[0]) * 1024
                elif 'MB/s' in spd:
                    upspeed_bytes += float(spd.split('M')[0]) * 1048576
        bmsg += f"\n<b>🔻 DL:</b> {get_readable_file_size(dlspeed_bytes)}/s | <b>🔺 UL:</b> {get_readable_file_size(upspeed_bytes)}/s"

        buttons = ButtonMaker()
        # buttons.sbutton("Refresh", "status refresh")
        buttons.sbutton("📈", str(THREE))
      #  buttons.sbutton("Close", "status close")
        sbutton = InlineKeyboardMarkup(buttons.build_menu(3))

        if STATUS_LIMIT is not None and tasks > STATUS_LIMIT:
            msg += f"<b>Tasks:</b> {tasks}\n"
            buttons = ButtonMaker()
            buttons.sbutton("⏪", "status pre")
            buttons.sbutton(f"{PAGE_NO}/{pages}", str(THREE))
            buttons.sbutton("⏩", "status nex")
            buttons.sbutton("🔄", "status refresh")
            buttons.sbutton("❌", "status close")
            button = InlineKeyboardMarkup(buttons.build_menu(3))
            return msg + bmsg, button
        return msg + bmsg, sbutton


def turn(data):
    try:
        with download_dict_lock:
            global COUNT, PAGE_NO
            if data[1] == "nex":
                if PAGE_NO == pages:
                    COUNT = 0
                    PAGE_NO = 1
                else:
                    COUNT += STATUS_LIMIT
                    PAGE_NO += 1
            elif data[1] == "pre":
                if PAGE_NO == 1:
                    COUNT = STATUS_LIMIT * (pages - 1)
                    PAGE_NO = pages
                else:
                    COUNT -= STATUS_LIMIT
                    PAGE_NO -= 1
        return True
    except BaseException:
        return False


def secondsToText():
    secs = AUTO_DELETE_UPLOAD_MESSAGE_DURATION
    days = secs // 86400
    hours = (secs - days * 86400) // 3600
    minutes = (secs - days * 86400 - hours * 3600) // 60
    seconds = secs - days * 86400 - hours * 3600 - minutes * 60
    return (
        ("{0} ᴅᴀʏ{1}, ".format(days, "s" if days != 1 else "") if days else "")
        + ("{0} ʜᴏᴜʀ{1} ".format(hours, "s" if hours != 1 else "") if hours else "")
        + (
            "{0} ᴍɪɴᴜᴛᴇ{1} ".format(minutes, "s" if minutes != 1 else "")
            if minutes
            else ""
        )
        + (
            "{0} sᴇᴄᴏɴᴅ{1} ".format(seconds, "s" if seconds != 1 else "")
            if seconds
            else ""
        )
    )

def get_readable_time(seconds: int) -> str:
    result = ''
    (days, remainder) = divmod(seconds, 86400)
    days = int(days)
    if days != 0:
        result += f'{days}d'
    (hours, remainder) = divmod(remainder, 3600)
    hours = int(hours)
    if hours != 0:
        result += f'{hours}h'
    (minutes, seconds) = divmod(remainder, 60)
    minutes = int(minutes)
    if minutes != 0:
        result += f'{minutes}m'
    seconds = int(seconds)
    result += f'{seconds}s'
    return result


def is_url(url: str):
    url = re_findall(URL_REGEX, url)
    return bool(url)


def is_gdrive_link(url: str):
    return "drive.google.com" in url

def is_gdtot_link(url: str):
    url = re_match(r'https?://.+\.gdtot\.\S+', url)
    return bool(url)

def is_unified_link(url: str):
    url1 = re_match(r'https?://(anidrive|driveroot|driveflix|indidrive|drivehub)\.in/\S+', url)
    url = re_match(r'https?://(appdrive|driveapp|driveace|gdflix|drivelinks|drivebit|drivesharer|drivepro)\.\S+', url)
    if bool(url1) == True:
        return bool(url1)
    elif bool(url) == True:
        return bool(url)
    else:
        return False

def is_udrive_link(url: str):
    if 'drivehub.ws' in url:
        return 'drivehub.ws' in url
    else:
        url = re_match(r'https?://(hubdrive|katdrive|kolop|drivefire|drivebuzz)\.\S+', url)
        return bool(url)

def is_sharer_link(url: str):
    url = re_match(r'https?://(sharer)\.pw/\S+', url)

def is_mega_link(url: str):
    return "mega.nz" in url or "mega.co.nz" in url

def get_mega_link_type(url: str):
    if "folder" in url:
        return "folder"
    elif "file" in url:
        return "file"
    elif "/#F!" in url:
        return "folder"
    return "file"

def is_magnet(url: str):
    magnet = re_findall(MAGNET_REGEX, url)
    return bool(magnet)

def new_thread(fn):
    """To use as decorator to make a function call threaded.
    Needs import
    from threading import Thread"""

    def wrapper(*args, **kwargs):
        thread = Thread(target=fn, args=args, kwargs=kwargs)
        thread.start()
        return thread

    return wrapper


def get_content_type(link: str) -> str:
    try:
        res = rhead(
            link,
            allow_redirects=True,
            timeout=5,
            headers={
                'user-agent': 'Wget/1.12'})
        content_type = res.headers.get('content-type')
    except BaseException:
        try:
            res = urlopen(link, timeout=5)
            info = res.info()
            content_type = info.get_content_type()
        except BaseException:
            content_type = None
    return content_type


ONE, TWO, THREE = range(3)


def pop_up_stats(update, context):
    query = update.callback_query
    stats = bot_sys_stats()
    query.answer(text=stats, show_alert=True)


def bot_sys_stats():
    currentTime = get_readable_time(time() - botStartTime)
    total, used, free, disk = disk_usage('/')
    disk_t = get_readable_file_size(total)
    disk_f = get_readable_file_size(free)
    memory = virtual_memory()
    mem_p = memory.percent
    recv = get_readable_file_size(psutil.net_io_counters().bytes_recv)
    sent = get_readable_file_size(psutil.net_io_counters().bytes_sent)
    cpuUsage = cpu_percent(interval=1)
    return f"""
{TITLE_NAME} BOT STATS
CPU:  {progress_bar(cpuUsage)} {cpuUsage}%
RAM: {progress_bar(mem_p)} {mem_p}%
DISK: {progress_bar(disk)} {disk}%
T: {disk_t}GB | F: {disk_f}GB
Working For: {currentTime}
T-DL: {recv} | T-UL: {sent}
Made with ❤️ by Dipesh
"""


dispatcher.add_handler(
    CallbackQueryHandler(pop_up_stats, pattern="^" + str(THREE) + "$")
)

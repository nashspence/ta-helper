from distutils.util import strtobool
from dotenv import load_dotenv
import html2text
import logging
import requests
import re
import os
import apprise
import time

# Configure logging.
logger = logging.getLogger(__name__)
handler = logging.StreamHandler()
formatter = logging.Formatter(fmt='%(asctime)s %(filename)s:%(lineno)s %(levelname)-8s %(message)s',
                              datefmt='%d-%b-%y %H:%M:%S')
handler.setFormatter(formatter)
logger.addHandler(handler)

# Pull configuration details from .env file.
load_dotenv()
NOTIFICATIONS_ENABLED = bool(strtobool(os.environ.get("NOTIFICATIONS_ENABLED", 'False')))
GENERATE_NFO = bool(strtobool(os.environ.get("GENERATE_NFO", 'False')))
FROMADDR = os.environ.get("MAIL_USER")
RECIPIENTS = os.environ.get("MAIL_RECIPIENTS")
RECIPIENTS = RECIPIENTS.split(',')
TA_MEDIA_FOLDER = os.environ.get("TA_MEDIA_FOLDER")
TA_SERVER = os.environ.get("TA_SERVER")
TA_TOKEN = os.environ.get("TA_TOKEN")
TA_CACHE = os.environ.get("TA_CACHE")
TARGET_FOLDER = os.environ.get("TARGET_FOLDER")
APPRISE_LINK = os.environ.get("APPRISE_LINK")
QUICK = bool(strtobool(os.environ.get("QUICK", 'True')))

logger.setLevel(os.environ.get("LOGLEVEL", "INFO"))

def setup_new_channel_resources(chan_name, chan_data):
    logger.info("New Channel %s, setup resources.", chan_name)
    # Link the channel logo from TA docker cache into target folder for media managers
    # and file explorers.  Provide cover.jpg, poster.jpg and banner.jpg symlinks.
    channel_thumb_path = TA_CACHE + chan_data['channel_thumb_url']
    logger.debug("%s poster is at %s", chan_name, channel_thumb_path)
    file_name = 'http://' + TARGET_FOLDER + '/' + chan_name + '/' + 'poster.jpg'
    os.symlink(channel_thumb_path, TARGET_FOLDER + "/" + chan_name + "/" + "poster.jpg")
    os.symlink(channel_thumb_path, TARGET_FOLDER + "/" + chan_name + "/" + "cover.jpg")
    channel_banner_path = TA_CACHE + chan_data['channel_banner_url']
    os.symlink(channel_banner_path, TARGET_FOLDER + "/" + chan_name + "/" + "banner.jpg")
    # generate tvshow.nfo for media managers.
    f= open(TARGET_FOLDER + "/" + chan_name + "/" + "tvshow.nfo","w+")
    f.write('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>' + '\n'
            '<tvshow>' + '\n\t' + '<title>' +
            chan_data['channel_name'] + "</title>\n\t" +
            "<showtitle>" + chan_data['channel_name'] + "</showtitle>\n\t" +
            "<uniqueid>" + chan_data['channel_id'] + "</uniqueid>\n\t" +
            "<plot>" + chan_data['channel_description'] + "</plot>\n\t" +
            "<premiered>" + chan_data['channel_last_refresh'] + "</premiered>\n</episodedetails>")
    f.close()

def generate_new_video_nfo(chan_name, title, video_meta_data):
    logger.debug("Generating NFO file for %s video: %s", video_meta_data['channel']['channel_name'], video_meta_data['title'])
    # TA has added a new video.  Create an NFO file for media managers.
    title = title.replace('.mp4','.nfo')
    f= open(TARGET_FOLDER + "/" + chan_name + "/" + title,"w+")
    f.write('<?xml version="1.0" ?>\n<episodedetails>\n\t' +
        "<title>" + video_meta_data['title'] + "</title>\n\t" +
        "<showtitle>" + video_meta_data['channel']['channel_name'] + "</showtitle>\n\t" +
        "<uniqueid>" + video_meta_data['youtube_id'] + "</uniqueid>\n\t" +
        "<plot>" + video_meta_data['description'] + "</plot>\n\t" +
        "<premiered>" + video_meta_data['published'] + "</premiered>\n</episodedetails>")
    f.close()

def notify(video_meta_data):

    # Send a notification via apprise library.
    logger.debug("Sending new %s video notification: %s", video_meta_data['channel']['channel_name'],
                video_meta_data['title'])

    email_body = '<!DOCTYPE PUBLIC “-//W3C//DTD XHTML 1.0 Transitional//EN” '
    email_body += '“https://www.w3.org/TR/xhtml1/DTD/xhtml1-transitional.dtd”>' + '\n'
    email_body += '<html xmlns="http://www.w3.org/1999/xhtml">' + '\n'
    email_body += '<head>' + '\n\t'
    email_body += '<title>' + video_meta_data['title'] + '</title>' + '\n'
    email_body += '</head>' + '\n'
    email_body += '<body>'

    video_url = TA_SERVER + "/video/" + video_meta_data['youtube_id']
    email_body += "\n\n<b>Video Title:</b> " + video_meta_data['title']  + "<br>" + '\n'
    email_body += "\n<b>Video Date:</b> " + video_meta_data['published'] + "<br>" + '\n'
    email_body += "\n<b>Video Views:</b> " + str(video_meta_data['stats']['view_count']) + "<br>" + '\n'
    email_body += "\n<b>Video Likes:</b> " + str(video_meta_data['stats']['like_count']) + "<br>" + '\n\n'
    email_body += "\n<b>Video Link:</b> <a href=\"" + video_url + "\">" + video_url + "</a><br>" + '\n'
    email_body += "\n<b>Video Description:</b>\n\n<pre>" + video_meta_data['description'] + '</pre></br>\n\n'
    email_body += '\n</body>\n</html>'

    # Dump for local debug viewing
    pretty_text = html2text.HTML2Text()
    pretty_text.ignore_links = True
    pretty_text.body_width = 200
    logger.debug(pretty_text.handle(email_body))
    logger.debug(email_body)

    video_title = "[TA] New video from " + video_meta_data['channel']['channel_name']

    apobj = apprise.Apprise()
    apobj.add(APPRISE_LINK)
    apobj.notify(body=email_body,title=video_title)

def urlify(s):
    s = re.sub(r"[^\w\s]", '', s)
    s = re.sub(r"\s+", '-', s)
    return s

os.makedirs(TARGET_FOLDER, exist_ok = True)
url = TA_SERVER + '/api/channel/'
headers = {'Authorization': 'Token ' + TA_TOKEN}
req = requests.get(url, headers=headers)
channels_json = req.json() if req and req.status_code == 200 else None
chan_data = channels_json['data']

while channels_json['paginate']['last_page']:
    channels_json = requests.get(url, headers=headers, params={'page': channels_json['paginate']['current_page'] + 1}).json()
    chan_data.extend(channels_json['data'])
                     
for x in chan_data:
    chan_name = urlify(x['channel_name'])
    description = x['channel_description']
    logger.debug("Video Description: " + description)
    logger.debug("Channel Name: " + chan_name)
    if(len(chan_name) < 1): chan_name = x['channel_id']
    chan_url = url+x['channel_id']+"/video/"
    try:
        os.makedirs(TARGET_FOLDER + "/" + chan_name, exist_ok = False)
        setup_new_channel_resources(chan_name, x)
    except OSError as error:
        logger.debug("We already have %s channel folder", chan_name)

    logger.debug("Channel URL: " + chan_url)
    chan_videos = requests.get(chan_url, headers=headers)
    chan_videos_json = chan_videos.json() if chan_videos and chan_videos.status_code == 200 else None

    if chan_videos_json is not None:
        chan_videos_data = chan_videos_json['data']
        while chan_videos_json['paginate']['last_page']:
            chan_videos_json = requests.get(chan_url, headers=headers, params={'page': chan_videos_json['paginate']['current_page'] + 1}).json()
            chan_videos_data.extend(chan_videos_json['data'])

        for y in chan_videos_data:
            y['media_url'] = y['media_url'].replace('/media','')
            logger.debug(y['published'] + "_" + y['youtube_id'] + "_" + urlify(y['title']) + ", " + y['media_url'])
            title=y['published'] + "_" + y['youtube_id'] + "_" + urlify(y['title']) + ".mp4"
            try:
                os.symlink(TA_MEDIA_FOLDER + os.path.splitext(y['media_url'])[0]+ ".en.vtt", TARGET_FOLDER + "/" + chan_name + "/" + title + ".en.vtt");
                os.symlink(TA_MEDIA_FOLDER + y['media_url'], TARGET_FOLDER + "/" + chan_name + "/" + title)
                # Getting here means a new video.
                logger.info("Processing new video from %s: %s", chan_name, title)
                if NOTIFICATIONS_ENABLED:
                    notify(y)
                else:
                    logger.info("Notification not sent for %s new video %s as NOTIFICATIONS_ENABLED is set to False in .env settings.", chan_name, title)
                if GENERATE_NFO:
                    generate_new_video_nfo(chan_name, title, y)
                else:
                    logger.info("Not generating NFO files for %s new video: %s", chan_name, title)
            except FileExistsError:
                # This means we already had processed the video, completely normal.
                logger.debug("Symlink exists for " + title)
                if(QUICK):
                    time.sleep(.5)
                    break;

# app.py
import os
import logging
from flask import Flask, render_template, Response, request, jsonify
from pymongo import MongoClient
from bson import ObjectId
from telegram import Bot, Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Updater, CommandHandler, MessageHandler, Filters, CallbackContext
import requests
from datetime import datetime
import re

app = Flask(__name__)

# Environment variables
TELEGRAM_TOKEN = os.environ['TELEGRAM_TOKEN']
CHANNEL_NAME = os.environ['CHANNEL_NAME']
WEBSITE_URL = os.environ['WEBSITE_URL']
ADMIN_ID = int(os.environ.get('ADMIN_ID', 0))
MONGO_URI = os.environ['MONGO_URI']

# Configure logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# MongoDB setup
client = MongoClient(MONGO_URI)
db = client.videotv
videos_collection = db.videos

# Routes
@app.route('/')
def index():
    return render_template('index.html', website_url=WEBSITE_URL)

@app.route('/playlist')
def playlist():
    videos = list(videos_collection.find().sort('added_at', 1))
    return render_template('playlist.html', videos=videos)

@app.route('/player/<video_id>')
def player(video_id):
    video = videos_collection.find_one({'_id': ObjectId(video_id)})
    if not video:
        return "Video not found", 404
    return render_template('player.html', video=video)

@app.route('/video/<video_id>')
def video_stream(video_id):
    video = videos_collection.find_one({'_id': ObjectId(video_id)})
    if not video:
        return "Video not found", 404
    
    # Get file URL from Telegram
    file_url = f"https://api.telegram.org/file/bot{TELEGRAM_TOKEN}/{video['file_name']}"
    
    # Stream video from Telegram
    req = requests.get(file_url, stream=True)
    return Response(
        req.iter_content(chunk_size=8192),
        content_type=req.headers['content-type'],
        headers={'Content-Disposition': f'inline; filename="{video["file_name"]}"'}
    )

@app.route('/api/playlist')
def api_playlist():
    videos = list(videos_collection.find({'played': False}).sort('added_at', 1))
    playlist = []
    for video in videos:
        playlist.append({
            'id': str(video['_id']),
            'title': video['file_name'],
            'thumbnail': video.get('thumbnail', ''),
            'streams': video.get('streams', {})
        })
    return jsonify(playlist)

@app.route('/api/played/<video_id>', methods=['POST'])
def mark_played(video_id):
    videos_collection.update_one(
        {'_id': ObjectId(video_id)},
        {'$set': {'played': True}}
    )
    return jsonify({'status': 'success'})

# Telegram Bot Handlers
def start(update: Update, context: CallbackContext):
    keyboard = [[InlineKeyboardButton("📺 Watch Videos", url=WEBSITE_URL)]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    update.message.reply_text(
        '📺 Welcome to Video TV Bot!\n\n'
        'I automatically stream videos from our channel. '
        f'Visit our website to watch: {WEBSITE_URL}',
        reply_markup=reply_markup
    )

def handle_message(update: Update, context: CallbackContext):
    if update.channel_post and update.channel_post.chat.username == CHANNEL_NAME[1:]:
        process_channel_post(update.channel_post)

def process_channel_post(post):
    # Handle video files
    if post.video:
        save_video(post.video)
    # Handle document files (video formats)
    elif post.document and post.document.mime_type.startswith('video/'):
        save_video(post.document)

def save_video(file):
    # Check if video already exists
    if videos_collection.find_one({'file_id': file.file_id}):
        return

    # Get video details
    file_path = telegram_bot.get_file(file.file_id).file_path
    
    # Create streams info
    streams = {
        'video': [{'resolution': '720p', 'codec': 'h264'}],
        'audio': [{'language': 'en', 'codec': 'aac'}],
        'subtitles': []
    }

    # Save to database
    video_data = {
        'file_id': file.file_id,
        'file_name': file_path.split('/')[-1],
        'mime_type': getattr(file, 'mime_type', 'video/mp4'),
        'thumbnail': f"https://api.telegram.org/file/bot{TELEGRAM_TOKEN}/{file_path}_thumb.jpg",
        'added_at': datetime.utcnow(),
        'played': False,
        'streams': streams
    }
    videos_collection.insert_one(video_data)

# Initialize Telegram bot
telegram_bot = Bot(token=TELEGRAM_TOKEN)

# Start Telegram bot in a separate thread
def start_bot():
    updater = Updater(TELEGRAM_TOKEN, use_context=True)
    dp = updater.dispatcher

    dp.add_handler(CommandHandler("start", start))
    dp.add_handler(MessageHandler(Filters.update.channel_post, handle_message))

    updater.start_polling()
    updater.idle()

# Run both Flask and Telegram bot
if __name__ == '__main__':
    import threading
    threading.Thread(target=start_bot, daemon=True).start()
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))

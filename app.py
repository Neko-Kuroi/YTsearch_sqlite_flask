from flask import Flask, render_template, request, jsonify, send_file, session, redirect, url_for
import urllib.request
import urllib.parse
import re
import json
import secrets
import os
import shutil
import logging
from bs4 import BeautifulSoup
import datetime
import time
from sqlalchemy.orm import declarative_base
from sqlalchemy import create_engine, Column, Integer, String
from sqlalchemy.orm import sessionmaker
import tempfile
from werkzeug.utils import secure_filename

app = Flask(__name__)
app.secret_key = secrets.token_urlsafe(32)

# Configure logging
logging.basicConfig(level=logging.INFO)

# SQLAlchemy setup
Base = declarative_base()

class Item(Base):
    __tablename__ = 'item'
    id = Column(Integer, primary_key=True)
    title_name = Column(String)
    video_id = Column(String)
    channel_id = Column(String)
    date_time = Column(String)
    view_counter = Column(String)
    channel_name = Column(String)

    @property
    def item_info(self):
        return f"id: {self.id}, title: {self.title_name}, video_id: {self.video_id}, channel_id: {self.channel_id}, date_time: {self.date_time}, view_counter: {self.view_counter}, channel_name: {self.channel_name}"

def setup_requests():
    opener = urllib.request.build_opener()
    opener.addheaders = [
        ('Referer', 'http://www.google.com/'),
        ('User-Agent', 'Mozilla/5.0'),
    ]
    urllib.request.install_opener(opener)

def my_makedirs(path):
    if not os.path.isdir(path):
        os.makedirs(path)

def get_session_db(temp_dir):
    engine = create_engine(f'sqlite:///{temp_dir}/sqlite_.db')
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    return Session()

def first_access(keyword):
    time.sleep(1)
    target_url = "https://www.youtube.com/results?search_query=" + keyword
    try:
        search_response = urllib.request.urlopen(target_url)
        if search_response.getcode() != 200:
            time.sleep(1)
            return [], []

        html = search_response.read()
        html_strings = html.decode()
        del(html)

        json_strings = ""
        soup = BeautifulSoup(html_strings, 'html.parser')
        for script_tag in soup.find_all('script'):
            if re.search('ytInitialData', str(script_tag)):
                start = int(re.search('{', str(script_tag)).start())
                end = int(re.search(';\<', str(script_tag)).end())
                json_strings = str(script_tag)[start:(end-2)]
                break
        del(soup)
        
        if not json_strings:
            return [], []
            
        json_dict = json.loads(json_strings)

        co = json_dict['contents']['twoColumnSearchResultsRenderer']['primaryContents']['sectionListRenderer']['contents'][0]['itemSectionRenderer']['contents']
        amounts = len(co)
        videoIds_ = []
        channels_ = []
        
        for i in range(amounts):
            d = json_dict['contents']['twoColumnSearchResultsRenderer']['primaryContents']['sectionListRenderer']['contents'][0]['itemSectionRenderer']['contents'][i]
            if 'videoRenderer' in d.keys():
                if 'videoId' in d['videoRenderer'].keys():
                    videoIds_.append(str(d['videoRenderer']['videoId']))
                if 'ownerText' in d['videoRenderer'].keys():
                    channels_.append(str(d['videoRenderer']['ownerText']['runs'][0]['text']))

        return videoIds_, channels_
    except Exception as e:
        logging.error(f"Error in first_access: {e}")
        return [], []

@app.route('/')
def index():
    if 'session_id' not in session:
        session['session_id'] = secrets.token_urlsafe()
    return render_template('index.html')

@app.route('/search', methods=['POST'])
def search():
    setup_requests()
    
    keywords = request.json.get('keywords', '').strip()
    if not keywords:
        return jsonify({'error': 'Keywords are required'}), 400

    # Create session directory
    if 'session_id' not in session:
        session['session_id'] = secrets.token_urlsafe()
    
    temp_dir = f"removefolder/{session['session_id']}"
    my_makedirs(temp_dir)
    
    # Process keywords
    words = ""
    for num, x in enumerate(keywords.split()):
        if num == 0:
            words = x
        else:
            words += "+" + x

    # Regex patterns
    strings = ""
    strings2 = ""
    for word in words.split('+'):
        strings += '(?=.*' + word + ')'
        strings2 += word + '|'

    strings2 = strings2.rstrip('|')
    strings = strings + ".*$"

    r_strings_NG = re.compile(r"\#shorts|ひろゆき|ホリエモン|堀江貴文|武田邦彦", flags=re.IGNORECASE)
    r_strings = re.compile(strings, flags=re.IGNORECASE)
    r_strings2 = re.compile(strings2, flags=re.IGNORECASE)
    
    KEYWORDS = urllib.parse.quote(words)
    BASEURL = 'https://www.youtube.com/watch?v='

    # Get initial video IDs
    videoIds = []
    channel_t = []
    if KEYWORDS:
        for _ in range(10):
            ids, channels = first_access(KEYWORDS)
            if len(ids) > 0:
                videoIds += ids
                channel_t += channels

    ids_channels = list(zip(videoIds, channel_t))
    videoIds = list(dict.fromkeys(videoIds))  # Remove duplicates
    ids_channels = dict(ids_channels)

    all_videoIds = videoIds[:]
    all_channels = {}
    visited_url = []
    data_list = []
    stock_channel_name = []
    
    # Get database session
    db_session = get_session_db(temp_dir)
    
    results = []
    
    for n, videoid in enumerate(all_videoIds):
        if n >= 50:  # Limit for demo purposes
            break
            
        target_url = BASEURL + str(videoid)
        if target_url in visited_url:
            continue
            
        visited_url.append(target_url)
        
        try:
            html = urllib.request.urlopen(target_url).read()
            html_strings = html.decode()
            del(html)
        except Exception as e:
            logging.error(f"Error fetching {target_url}: {e}")
            time.sleep(10)
            continue

        temp_channel_name = ""
        if videoid in all_channels.keys():
            temp_channel_name = all_channels[videoid]
        elif videoid in ids_channels.keys():
            temp_channel_name = ids_channels[videoid]

        if re.search(r_strings_NG, temp_channel_name):
            continue

        try:
            json_strings = ""
            soup = BeautifulSoup(html_strings, 'html.parser')
            for script_tag in soup.find_all('script'):
                if re.search('ytInitialData', str(script_tag)):
                    start = int(re.search('{', str(script_tag)).start())
                    end = int(re.search(';\<', str(script_tag)).end())
                    json_strings = str(script_tag)[start:(end-2)]
                    break
            del(soup)
            
            if not json_strings:
                continue
                
            json_dict = json.loads(json_strings)
            
            if 'contents' not in json_dict:
                continue

            temp_title = ""
            temp_dateText = None
            temp_viewCount = ""
            temp_channelid = ""
            temp_channel_url = ""
            check = False
            check_important = False

            # Extract video information
            for x in json_dict['contents']['twoColumnWatchNextResults'].values():
                if 'results' in x.keys():
                    for y in x['results']['contents']:
                        if 'videoPrimaryInfoRenderer' in y.keys():
                            # Title
                            if 'title' in y['videoPrimaryInfoRenderer'].keys():
                                for t in range(len(y['videoPrimaryInfoRenderer']['title']['runs'])):
                                    temp_title += re.sub(r'\n', ' ', y['videoPrimaryInfoRenderer']['title']['runs'][t]['text'])

                                if re.search(r_strings_NG, temp_title):
                                    check_important = True
                                elif re.search(r_strings2, str(temp_title)):
                                    check = True

                            # Date
                            if 'dateText' in y['videoPrimaryInfoRenderer'].keys():
                                temp_str = y['videoPrimaryInfoRenderer']['dateText']['simpleText']
                                if (m_o := re.match(r'(\d+)\/(\d+)\/(\d+)', temp_str)):
                                    str_date = m_o.group()
                                    fmt = "%Y/%m/%d"
                                    temp_dateText = datetime.datetime.strptime(str_date, fmt)

                            # View count
                            if 'viewCount' in y['videoPrimaryInfoRenderer'].keys():
                                if 'simpleText' in y['videoPrimaryInfoRenderer']['viewCount']['videoViewCountRenderer']['viewCount'].keys():
                                    temp_viewCount = y['videoPrimaryInfoRenderer']['viewCount']['videoViewCountRenderer']['viewCount']['simpleText']
                                else:
                                    temp_viewCount = y['videoPrimaryInfoRenderer']['viewCount']['videoViewCountRenderer']['viewCount']['runs'][0]['text']

                        # Channel info
                        if 'videoSecondaryInfoRenderer' in y.keys():
                            if 'subscribeButton' in y['videoSecondaryInfoRenderer'].keys():
                                temp_channelid = str(y['videoSecondaryInfoRenderer']['subscribeButton']['subscribeButtonRenderer']['channelId'])
                                temp_channel_url = "https://www.youtube.com/channel/" + temp_channelid

            if temp_dateText is not None and check and not check_important:
                # Save to database
                item = Item()
                item.title_name = temp_title
                item.video_id = target_url
                item.channel_id = temp_channel_url
                item.date_time = str(temp_dateText)[:10]
                item.view_counter = temp_viewCount
                item.channel_name = temp_channel_name
                db_session.add(item)
                
                result_item = {
                    'title': temp_title,
                    'url': target_url,
                    'channel_name': temp_channel_name,
                    'channel_url': temp_channel_url,
                    'date': str(temp_dateText)[:10] if temp_dateText else '',
                    'view_count': temp_viewCount
                }
                results.append(result_item)

        except Exception as e:
            logging.error(f"Error processing video {videoid}: {e}")
            continue

    db_session.commit()
    db_session.close()
    
    # Sort results by date
    results.sort(key=lambda x: x['date'], reverse=True)
    
    return jsonify({
        'results': results,
        'total': len(results),
        'session_id': session['session_id']
    })

@app.route('/download/<file_type>')
def download_file(file_type):
    if 'session_id' not in session:
        return jsonify({'error': 'No active session'}), 400
    
    temp_dir = f"removefolder/{session['session_id']}"
    
    if file_type == 'sqlite':
        file_path = f"{temp_dir}/sqlite_.db"
        if os.path.exists(file_path):
            return send_file(file_path, as_attachment=True, download_name='youtube_search.db')
    
    return jsonify({'error': 'File not found'}), 404

@app.route('/clear_session', methods=['POST'])
def clear_session():
    if 'session_id' in session:
        temp_dir = f"removefolder/{session['session_id']}"
        if os.path.exists(temp_dir):
            shutil.rmtree(temp_dir)
        session.clear()
    return jsonify({'status': 'cleared'})

@app.teardown_appcontext
def cleanup_session(error):
    """Clean up session files when app context tears down"""
    if 'session_id' in session:
        temp_dir = f"removefolder/{session['session_id']}"
        # Note: In production, you might want to implement a more sophisticated cleanup strategy
        pass

if __name__ == '__main__':
    # Ensure removefolder directory exists
    my_makedirs('removefolder')
    app.run(debug=True, host='0.0.0.0', port=5000)

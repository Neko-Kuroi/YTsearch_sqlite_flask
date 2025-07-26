# app.py
from flask import Flask, render_template_string, request, jsonify, send_file, session
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
import socket
import ssl

app = Flask(__name__)
app.secret_key = secrets.token_urlsafe(32)

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# HTML template as string
HTML_TEMPLATE = '''
<!DOCTYPE html>
<html lang="ja">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>YouTube Search 𓃻</title>
    <style>
        body {
            font-family: Arial, sans-serif;
            max-width: 1200px;
            margin: 0 auto;
            padding: 20px;
            background-color: #f5f5f5;
        }
        .container {
            background: white;
            padding: 30px;
            border-radius: 10px;
            box-shadow: 0 2px 10px rgba(0,0,0,0.1);
        }
        h1 {
            color: #333;
            text-align: center;
            margin-bottom: 30px;
        }
        .search-section {
            margin-bottom: 30px;
        }
        input[type="text"] {
            width: 70%;
            padding: 12px;
            border: 2px solid #ddd;
            border-radius: 5px;
            font-size: 16px;
        }
        button {
            padding: 12px 20px;
            margin-left: 10px;
            background-color: #007bff;
            color: white;
            border: none;
            border-radius: 5px;
            cursor: pointer;
            font-size: 16px;
        }
        button:hover {
            background-color: #0056b3;
        }
        button:disabled {
            background-color: #ccc;
            cursor: not-allowed;
        }
        .cancel-btn {
            background-color: #dc3545;
        }
        .download-btn {
            background-color: #28a745;
            margin-right: 10px;
            margin-bottom: 10px;
        }
        .status {
            margin: 20px 0;
            padding: 10px;
            border-radius: 5px;
            display: none;
        }
        .status.info {
            background-color: #d1ecf1;
            border: 1px solid #bee5eb;
            color: #0c5460;
        }
        .status.error {
            background-color: #f8d7da;
            border: 1px solid #f5c6cb;
            color: #721c24;
        }
        .status.success {
            background-color: #d4edda;
            border: 1px solid #c3e6cb;
            color: #155724;
        }
        .results {
            margin-top: 30px;
        }
        .result-item {
            background: #f8f9fa;
            margin: 15px 0;
            padding: 20px;
            border-radius: 8px;
            border-left: 4px solid #007bff;
        }
        .result-title {
            font-weight: bold;
            margin-bottom: 10px;
            color: #333;
        }
        .result-title a {
            color: #007bff;
            text-decoration: none;
        }
        .result-meta {
            color: #666;
            font-size: 14px;
            margin: 5px 0;
        }
        .result-channel {
            margin-top: 10px;
        }
        .result-channel a {
            color: #28a745;
            text-decoration: none;
        }
        .loading {
            text-align: center;
            padding: 20px;
        }
        .spinner {
            border: 4px solid #f3f3f3;
            border-top: 4px solid #3498db;
            border-radius: 50%;
            width: 40px;
            height: 40px;
            animation: spin 2s linear infinite;
            margin: 20px auto;
        }
        @keyframes spin {
            0% { transform: rotate(0deg); }
            100% { transform: rotate(360deg); }
        }
        .download-section {
            margin: 20px 0;
            padding: 15px;
            background-color: #e9ecef;
            border-radius: 5px;
            display: none;
        }
        .progress-info {
            margin-top: 10px;
            font-size: 14px;
            color: #555;
        }
    </style>
</head>
<body>
    <div class="container">
        <h1>YouTube Search 𓃻</h1>
        <div class="search-section">
            <input type="text" id="keywords" placeholder="検索キーワードを入力..." maxlength="60">
            <button id="searchBtn" onclick="startSearch()">検索</button>
            <button id="cancelBtn" class="cancel-btn" onclick="cancelSearch()" style="display: none;">キャンセル</button>
        </div>
        <div id="status" class="status"></div>
        <div id="loading" class="loading" style="display: none;">
            <div class="spinner"></div>
            <p>YouTube 動画を検索中...</p>
            <div id="progressInfo" class="progress-info"></div>
        </div>
        <div class="download-section" id="downloadSection">
            <h3>結果をダウンロード</h3>
            <button class="download-btn" onclick="downloadFile('sqlite')">SQLite データベース (.db)</button>
            <button class="download-btn" onclick="downloadFile('txt')">テキストファイル (.txt)</button>
        </div>
        <div id="results" class="results"></div>
    </div>
    <script>
        let searchInProgress = false;
        function showStatus(message, type = 'info') {
            const status = document.getElementById('status');
            status.textContent = message;
            status.className = `status ${type}`;
            status.style.display = 'block';
        }
        function hideStatus() {
            document.getElementById('status').style.display = 'none';
        }
        function updateProgress(message) {
            document.getElementById('progressInfo').textContent = message;
        }
        function startSearch() {
            const keywords = document.getElementById('keywords').value.trim();
            if (!keywords) {
                showStatus('検索キーワードを入力してください。', 'error');
                return;
            }
            searchInProgress = true;
            document.getElementById('searchBtn').disabled = true;
            document.getElementById('cancelBtn').style.display = 'inline-block';
            document.getElementById('loading').style.display = 'block';
            document.getElementById('results').innerHTML = '';
            document.getElementById('downloadSection').style.display = 'none';
            hideStatus();
            updateProgress('検索を開始しています...');
            
            fetch('/search', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({ keywords: keywords })
            })
            .then(response => response.json())
            .then(data => {
                searchInProgress = false;
                document.getElementById('searchBtn').disabled = false;
                document.getElementById('cancelBtn').style.display = 'none';
                document.getElementById('loading').style.display = 'none';
                if (data.error) {
                    showStatus(data.error, 'error');
                    return;
                }
                displayResults(data.results);
                showStatus(`検索完了! ${data.total_results} 件の動画が見つかりました。`, 'success');
                if (data.total_results > 0) {
                    document.getElementById('downloadSection').style.display = 'block';
                }
            })
            .catch(error => {
                searchInProgress = false;
                document.getElementById('searchBtn').disabled = false;
                document.getElementById('cancelBtn').style.display = 'none';
                document.getElementById('loading').style.display = 'none';
                showStatus('検索中にエラーが発生しました: ' + error.message, 'error');
            });
        }
        function cancelSearch() {
            if (searchInProgress) {
                fetch('/clear_session', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                    }
                })
                .then(() => {
                    location.reload();
                })
                .catch(error => {
                    console.error('Cancel error:', error);
                    location.reload(); // エラー時もリロード
                });
            }
        }
        function displayResults(results) {
            const resultsDiv = document.getElementById('results');
            if (results.length === 0) {
                resultsDiv.innerHTML = '<p>結果が見つかりませんでした。</p>';
                return;
            }
            let html = `<h2>検索結果 (${results.length} 件)</h2>`;
            results.forEach((result, index) => {
                html += `
                    <div class="result-item">
                        <div class="result-title">
                            <a href="${result.url}" target="_blank">${escapeHtml(result.title)}</a>
                        </div>
                        <div class="result-meta">
                            📅 ${escapeHtml(result.date)} | 👁️ ${escapeHtml(result.view_count)}
                        </div>
                        <div class="result-channel">
                            チャンネル: <a href="${result.channel_url}" target="_blank">${escapeHtml(result.channel_name)}</a>
                        </div>
                    </div>
                `;
            });
            resultsDiv.innerHTML = html;
        }
        function escapeHtml(text) {
            if (typeof text !== 'string') return text;
            const map = {
                '&': '&amp;',
                '<': '<',
                '>': '>',
                '"': '&quot;',
                "'": '&#039;'
            };
            return text.replace(/[&<>"']/g, function(m) { return map[m]; });
        }
        function downloadFile(fileType) {
            // より安全なダウンロード方法 (fetch を使用)
            fetch(`/download/${fileType}`)
                .then(response => {
                    if (!response.ok) {
                        throw new Error('Network response was not ok ' + response.statusText);
                    }
                    return response.blob();
                })
                .then(blob => {
                    // ファイル名を Content-Disposition ヘッダーから取得するか、デフォルトを設定
                    const contentDisposition = response.headers.get('Content-Disposition');
                    let filename = `youtube_search.${fileType === 'sqlite' ? 'db' : 'txt'}`;
                    if (contentDisposition) {
                        const filenameMatch = contentDisposition.match(/filename="?(.+)"?/);
                        if (filenameMatch && filenameMatch.length === 2) {
                            filename = filenameMatch[1];
                        }
                    }
                    // ダウンロードリンクを作成してクリック
                    const url = window.URL.createObjectURL(blob);
                    const link = document.createElement('a');
                    link.href = url;
                    link.download = filename;
                    document.body.appendChild(link);
                    link.click();
                    document.body.removeChild(link);
                    window.URL.revokeObjectURL(url); // メモリ解放
                })
                .catch(error => {
                    console.error('Download error:', error);
                    alert('ダウンロードに失敗しました: ' + error.message);
                });
        }
        document.getElementById('keywords').addEventListener('keypress', function(e) {
            if (e.key === 'Enter') {
                startSearch();
            }
        });
    </script>
</body>
</html>
'''

# SQLAlchemy setup
Base = declarative_base()

class Item(Base):
    __tablename__ = 'item'
    id = Column(Integer, primary_key=True)
    title_name = Column(String)
    video_id = Column(String)
    channel_id = Column(String)
    date_time = Column(String) # 文字列として保存
    view_counter = Column(String)
    channel_name = Column(String)

def setup_requests():
    """Setup urllib with better headers and SSL context"""
    try:
        # Create SSL context that's more permissive
        ssl_context = ssl.create_default_context()
        ssl_context.check_hostname = False
        ssl_context.verify_mode = ssl.CERT_NONE
        opener = urllib.request.build_opener(urllib.request.HTTPSHandler(context=ssl_context))
        opener.addheaders = [
            ('Referer', 'http://www.google.com/'),
            ('User-Agent', 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'),
        ]
        urllib.request.install_opener(opener)
    except Exception as e:
        logging.error(f"Error setting up requests: {e}")

def my_makedirs(path):
    if not os.path.isdir(path):
        os.makedirs(path)

def get_session_db(temp_dir):
    engine = create_engine(f'sqlite:///{temp_dir}/sqlite_.db')
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    return Session()

# --- 移植した first_access 関数 ---
def first_access(keyword):
    """Streamlit コードから移植した first_access 関数"""
    time.sleep(1) # 必要に応じて調整
    target_url = "https://www.youtube.com/results?search_query=" + keyword
    try:
        # setup_requests() で設定された opener を使用
        search_response = urllib.request.urlopen(target_url, timeout=10)
        if search_response.getcode() != 200:
            time.sleep(1)
            return [], []
        html = search_response.read()
        html_strings = html.decode()
        # del(html) # Python では不要だが、メモリ節約のため残す

        # """ extract json data """
        json_strings = ""
        soup = BeautifulSoup(html_strings, 'html.parser')
        for ind, script_tag in enumerate(soup.find_all('script')):
            if re.search('ytInitialData', str(script_tag)):
                start_match = re.search('{', str(script_tag))
                end_match = re.search('};', str(script_tag)) # ';' の後に '<' が来ない場合もあるため調整
                if start_match and end_match:
                     start = start_match.start()
                     end = end_match.end() - 1 # ';' の位置を終端とする
                     json_strings = str(script_tag)[start:end]
                     break
        # del(soup) # Python では不要だが、メモリ節約のため残す

        if not json_strings:
             logging.warning("Failed to extract JSON data from search results.")
             return [], []

        json_dict = json.loads(json_strings)

        # """ extract videoId data """
        # 構造が異なる場合があるため、少し柔軟に取得を試みる
        videoIds_ = []
        channels_ = []

        # コンテンツのパスを探索 (エラーハンドリングを追加)
        contents_path = json_dict
        try:
            for key in ['contents', 'twoColumnSearchResultsRenderer', 'primaryContents', 'sectionListRenderer', 'contents']:
                contents_path = contents_path[key]
            # 最初の itemSectionRenderer の内容を取得
            if contents_path and isinstance(contents_path, list) and len(contents_path) > 0:
                 item_section = contents_path[0].get('itemSectionRenderer', {}).get('contents', [])
                 for item in item_section:
                     if 'videoRenderer' in item:
                         video_renderer = item['videoRenderer']
                         video_id = video_renderer.get('videoId')
                         channel_name = video_renderer.get('ownerText', {}).get('runs', [{}])[0].get('text') if video_renderer.get('ownerText') else None
                         if video_id:
                             videoIds_.append(video_id)
                             channels_.append(channel_name if channel_name else "")
        except (KeyError, IndexError, TypeError) as e:
            logging.error(f"Error navigating JSON structure for video IDs: {e}")
            # 失敗しても、もし json_strings が取得できていれば、別の方法を試すか、空リストを返す

        return videoIds_, channels_

    except urllib.error.HTTPError as e:
        logging.error(f"HTTP Error during first_access for {keyword}: {e.code} {e.reason}")
    except urllib.error.URLError as e:
        logging.error(f"URL Error during first_access for {keyword}: {e.reason}")
    except json.JSONDecodeError as e:
        logging.error(f"JSON Decode Error during first_access for {keyword}: {e}")
    except Exception as e:
        logging.error(f"Unexpected error in first_access for {keyword}: {e}")

    time.sleep(1) # エラー時も少し待機
    return [], [] # エラー時は空のリストを返す

# --- 新規関数: 個別動画ページから詳細情報を取得 ---
def scrape_video_details(video_id, base_url='https://www.youtube.com/watch?v='):
    """
    Streamlit コードの動画詳細取得ロジックの一部を移植した関数。
    """
    target_url = base_url + video_id
    logging.info(f"Scraping details for video: {video_id}")

    # --- ここに Streamlit の for ループ内のスクレイピングロジックを移植 ---
    # (簡略化した例です。実際にはもっと多くの情報を抽出します)
    try:
        time.sleep(2.5) # リクエスト間隔を空ける
        # setup_requests() で設定された opener を使用
        response = urllib.request.urlopen(target_url, timeout=30)
        if response.getcode() != 200:
             logging.warning(f"Failed to fetch {target_url}, status code: {response.getcode()}")
             return None

        html = response.read()
        html_strings = html.decode('utf-8', errors='ignore') # エンコードエラー対策
        # del(html) # Python では不要

        # """ extract json data """
        json_strings = ""
        soup = BeautifulSoup(html_strings, 'html.parser')
        for script_tag in soup.find_all('script'):
            if re.search('ytInitialData', str(script_tag)):
                start_match = re.search('{', str(script_tag))
                end_match = re.search('};', str(script_tag)) # ';' の後に '<' が来ない場合もあるため調整
                if start_match and end_match:
                     start = start_match.start()
                     end = end_match.end() - 1 # ';' の位置を終端とする
                     json_strings = str(script_tag)[start:end]
                     break
        # del(soup) # Python では不要

        if not json_strings:
             logging.warning(f"Failed to extract JSON data for video {video_id}.")
             return None

        try:
            json_dict = json.loads(json_strings)
        except json.JSONDecodeError as e:
            logging.error(f"JSON Decode Error for video {video_id}: {e}")
            return None

        # """ extract video details """
        temp_title = ""
        temp_super_title = "" # 追加
        temp_description = ""
        temp_dateText = "" # 文字列として保持
        temp_viewCount = ""
        temp_channel_name = ""
        temp_channel_url = ""
        temp_channel_id = ""

        # コンテンツのパスを探索 (エラーハンドリングを追加)
        try:
            # videoPrimaryInfoRenderer からタイトルなどを取得
            contents = json_dict['contents']['twoColumnWatchNextResults']['results']['results']['contents']
            for item in contents:
                 if 'videoPrimaryInfoRenderer' in item:
                     vpr = item['videoPrimaryInfoRenderer']
                     # タイトル
                     if 'title' in vpr and 'runs' in vpr['title']:
                         temp_title = ''.join(run.get('text', '') for run in vpr['title']['runs'])
                     # スーパータイトル (追加)
                     if 'superTitleLink' in vpr and 'runs' in vpr['superTitleLink']:
                         temp_super_title = ''.join(run.get('text', '') for run in vpr['superTitleLink']['runs'])
                     # 投稿日
                     if 'dateText' in vpr and 'simpleText' in vpr['dateText']:
                         temp_dateText = vpr['dateText']['simpleText']
                     # 再生回数
                     if 'viewCount' in vpr and 'videoViewCountRenderer' in vpr['viewCount']:
                         vcr = vpr['viewCount']['videoViewCountRenderer']
                         if 'simpleText' in vcr.get('viewCount', {}):
                             temp_viewCount = vcr['viewCount']['simpleText']
                         elif 'runs' in vcr.get('viewCount', {}):
                             temp_viewCount = ''.join(run.get('text', '') for run in vcr['viewCount']['runs'])

                 if 'videoSecondaryInfoRenderer' in item:
                     vsr = item['videoSecondaryInfoRenderer']
                     # 説明
                     if 'attributedDescription' in vsr:
                         temp_description = vsr['attributedDescription'].get('content', '')
                     # チャンネル情報
                     if 'owner' in vsr and 'videoOwnerRenderer' in vsr['owner']:
                         vor = vsr['owner']['videoOwnerRenderer']
                         if 'title' in vor and 'runs' in vor['title']:
                             temp_channel_name = vor['title']['runs'][0].get('text', '') if vor['title']['runs'] else ''
                         if 'navigationEndpoint' in vor and 'browseEndpoint' in vor['navigationEndpoint']:
                             temp_channel_id = vor['navigationEndpoint']['browseEndpoint'].get('browseId', '')
                             temp_channel_url = f"https://www.youtube.com/channel/{temp_channel_id}"

        except (KeyError, IndexError, TypeError) as e:
            logging.error(f"Error extracting details for video {video_id}: {e}")
            # 一部の情報が取得できなくても、他の情報があれば返すか、None を返すか判断する

        # --- 重要: raw_json_dict を返り値に追加 ---
        # 取得した情報を辞書で返す
        return {
            'video_id': video_id,
            'title': temp_title,
            'super_title': temp_super_title, # 追加
            'description': temp_description,
            'date_text': temp_dateText,
            'view_count': temp_viewCount,
            'channel_name': temp_channel_name,
            'channel_url': temp_channel_url,
            'channel_id': temp_channel_id,
            'video_url': target_url,
            # --- 重要: JSON データ全体を返す ---
            'raw_json_dict': json_dict # 追加
            # 必要に応じて他のフィールドも追加
        }

    except urllib.error.HTTPError as e:
        logging.error(f"HTTP Error scraping {target_url}: {e.code} {e.reason}")
    except urllib.error.URLError as e:
        logging.error(f"URL Error scraping {target_url}: {e.reason}")
    except Exception as e:
        logging.error(f"Unexpected error scraping {target_url} (video ID: {video_id}): {e}", exc_info=True)

    return None # エラー時は None を返す

# --- 日付パース関数 ---
def parse_date_for_sorting(date_str):
    """日付文字列を datetime オブジェクトに変換する（失敗時は最小値）"""
    if not date_str:
        return datetime.datetime.min
    try:
        # Streamlit のコードから形式を参考に
        if (m_o := re.match(r'(\d+)\/(\d+)\/(\d+)', date_str)):
            return datetime.datetime.strptime(m_o.group(), "%Y/%m/%d")
        elif (m_o := re.search(r'(\d+)\S(\d+)\S(\d+)\S', date_str)): # 例: 首播日期：2022年6月21日
            return datetime.datetime.strptime(f"{m_o.group(1)} {m_o.group(2)} {m_o.group(3)}", "%Y %m %d")
        elif (m_o := re.match(r'^(...)\s(\d+)\,\s(\d+)', date_str)): # 例: Feb 11, 2023
            return datetime.datetime.strptime(m_o.group(), "%b %d, %Y")
        elif (m_o := re.search(r'(...)\s(\d+)\,\s(\d+)', date_str)): # 例: ... Feb 11, 2023 ...
            return datetime.datetime.strptime(m_o.group(), "%b %d, %Y")
        else:
            # 他の形式の試行...
            return datetime.datetime.strptime(date_str, "%Y年%m月%d日") # 例のため、必要に応じて追加
    except Exception as e:
        logging.warning(f"Could not parse date '{date_str}' for sorting: {e}")
        return datetime.datetime.min # パース失敗時はリストの最後に来るよう最小値を返す

# --- Flask Routes ---

@app.route('/')
def index():
    try:
        if 'session_id' not in session:
            session['session_id'] = secrets.token_urlsafe()
        return render_template_string(HTML_TEMPLATE)
    except Exception as e:
        logging.error(f"Error in index route: {e}")
        return f"<h1>YouTube Search</h1><p>Error: {str(e)}</p>", 500

@app.route('/search', methods=['POST'])
def search():
    try:
        setup_requests() # urllib の設定
        keywords_input = request.json.get('keywords', '').strip()
        if not keywords_input:
            return jsonify({'error': 'Keywords are required'}), 400

        # セッションと一時ディレクトリの設定
        if 'session_id' not in session:
            session['session_id'] = secrets.token_urlsafe()
        temp_dir = f"removefolder/{session['session_id']}"
        my_makedirs(temp_dir)

        # データベースセッションの取得
        db_session = get_session_db(temp_dir)

        # Streamlit と同様にキーワードを処理
        words_list = keywords_input.split()
        words_joined = "+".join(words_list)
        KEYWORDS_QUOTED = urllib.parse.quote(words_joined)
        # ファイル名用のキーワード整形 (Streamlit から移植)
        words_for_filename = re.sub(r"\+|\s+|\/|\\","_", words_joined)

        logging.info(f"Searching YouTube for: {KEYWORDS_QUOTED}")

        # --- フィルタリング用正規表現の定義 (Streamlit から移植) ---
        strings = ""
        strings2 = ""
        for word in words_list:
            strings += '(?=.*' + word + ')'
            strings2 += word + '|'
        strings2 = strings2.rstrip('|')
        strings = strings + ".*$" # 全てのキーワードを含む
        # NG ワードフィルター
        r_strings_NG = re.compile(r"\#shorts|ひろゆき|ホリエモン|堀江貴文|武田邦彦", flags=re.IGNORECASE)
        # キーワードフィルター (AND 検索)
        r_strings = re.compile(strings, flags=re.IGNORECASE)
        # キーワードフィルター (OR 検索 - Streamlit の主要な使用箇所)
        r_strings2 = re.compile(strings2, flags=re.IGNORECASE)
        # ログ出力
        logging.info(f"Filter regex - AND: {strings}, OR: {strings2}")

        # first_access を呼び出して初期データを取得
        videoIds_initial = []
        channel_names_initial = []
        if KEYWORDS_QUOTED:
            # リトライロジック
            for attempt in range(3):
                 videoIds_initial, channel_names_initial = first_access(KEYWORDS_QUOTED)
                 if videoIds_initial:
                     logging.info(f"Successfully fetched {len(videoIds_initial)} initial video IDs.")
                     break
                 else:
                     logging.warning(f"Attempt {attempt + 1} failed to fetch initial video IDs. Retrying...")
                     time.sleep(2)

        # 重複排除 (Streamlit の dict.fromkeys を使用)
        videoIds_unique = list(dict.fromkeys(videoIds_initial))
        # 初期の ID とチャンネル名のペアを辞書化
        ids_channels_dict = dict(zip(videoIds_initial, channel_names_initial))

        # --- 検索とフィルタリングのメインループ ---
        all_videoIds = videoIds_unique[:] # 処理対象のIDリスト (初期リストで初期化)
        visited_urls = set() # 訪問済みURLを記録 (効率化のため set を使用)
        filtered_results = [] # フィルタリングされた結果を格納
        items_to_save = [] # DB保存用 Item オブジェクトリスト
        BASEURL = 'https://www.youtube.com/watch?v='

        # --- ループ制御のための定数 ---
        MAX_VIDEOS_TO_PROCESS = 100 # 処理する動画の最大数
        processed_count = 0 # 処理済みカウンター

        # 各動画IDを処理 (while ループ)
        index = 0
        while index < len(all_videoIds) and processed_count < MAX_VIDEOS_TO_PROCESS:
            video_id = all_videoIds[index]
            index += 1
            processed_count += 1 # カウンターをインクリメント

            target_url = BASEURL + video_id
            if target_url in visited_urls:
                continue
            visited_urls.add(target_url)

            logging.info(f"Processing video {processed_count}/{MAX_VIDEOS_TO_PROCESS} (List index {index-1}/{len(all_videoIds)}): {video_id}")

            # 個別動画ページから詳細情報を取得
            video_details = scrape_video_details(video_id)
            if not video_details:
                continue # 取得失敗時はスキップ

            # --- フィルタリング ---
            temp_channel_name = video_details.get('channel_name', '')
            temp_title = video_details.get('title', '')
            temp_super_title = video_details.get('super_title', '') # scrape_video_details で取得
            temp_description = video_details.get('description', '')

            if re.search(r_strings_NG, temp_channel_name) or re.search(r_strings_NG, temp_title):
                logging.info(f"NG word found in channel ({temp_channel_name}) or title ({temp_title}) for video {video_id}. Skipping.")
                continue

            check = False
            if re.search(r_strings2, temp_title) or re.search(r_strings2, temp_super_title) or re.search(r_strings2, temp_description):
                 check = True
                 logging.info(f"Keyword match found for video {video_id}.")
            # else: # AND条件もチェックする場合 (オプション)
            #     if re.search(r_strings, temp_title) or re.search(r_strings, temp_super_title) or re.search(r_strings, temp_description):
            #         check = True
            #         logging.info(f"AND Keyword match found for video {video_id}.")

            if not check:
                logging.info(f"No keyword match for video {video_id}. Skipping.")
                continue # 条件に合わなければスキップ

            # --- 条件に合致した場合の処理 ---
            # 結果リストに追加
            filtered_results.append(video_details)

            # SQLAlchemy Item オブジェクトを作成して保存リストに追加
            item = Item()
            item.title_name = video_details.get('title', '')
            item.video_id = video_details.get('video_url', '')
            item.channel_id = video_details.get('channel_url', '')
            item.date_time = video_details.get('date_text', '') # 文字列を保存
            item.view_counter = video_details.get('view_count', '')
            item.channel_name = video_details.get('channel_name', '')
            items_to_save.append(item)

            # --- 関連動画の収集 ---
            json_dict = video_details.get('raw_json_dict') # scrape_video_details から取得
            if json_dict:
                try:
                    # Streamlit のロジックと同様に関連動画を取得
                    if 'contents' in json_dict and 'twoColumnWatchNextResults' in json_dict['contents']:
                        secondary_results_section = json_dict['contents']['twoColumnWatchNextResults'].get('secondaryResults', {})
                        if secondary_results_section:
                            secondary_results = secondary_results_section.get('secondaryResults', {}).get('results', [])
                            for result in secondary_results:
                                if 'compactVideoRenderer' in result:
                                    related_video_id = result['compactVideoRenderer'].get('videoId')
                                    if related_video_id:
                                        related_video_url = BASEURL + related_video_id
                                        # 新しい動画IDで、かつ訪問済みでも処理待ちでもない場合に追加
                                        if related_video_id not in all_videoIds and related_video_url not in visited_urls:
                                             all_videoIds.append(related_video_id)
                                             logging.debug(f"Added related video ID: {related_video_id}")
                                             # リストが長くなりすぎないように制限 (オプション)
                                             if len(all_videoIds) > MAX_VIDEOS_TO_PROCESS * 2:
                                                 logging.warning("Related video list is very long, trimming.")
                                                 all_videoIds = all_videoIds[:MAX_VIDEOS_TO_PROCESS * 2]
                                                 break # これ以上追加しない

                except (KeyError, IndexError, TypeError) as e:
                    logging.error(f"Error extracting related videos for {video_id}: {e}")

        # --- 結果のソート ---
        try:
            filtered_results.sort(key=lambda x: parse_date_for_sorting(x.get('date_text', '')), reverse=True)
            logging.info("Results sorted by date (newest first).")
        except Exception as e:
            logging.error(f"Error sorting results: {e}")

        # --- データベースに保存 ---
        if items_to_save:
            try:
                db_session.add_all(items_to_save)
                db_session.commit()
                logging.info(f"Saved {len(items_to_save)} items to database.")
            except Exception as e:
                logging.error(f"Error saving to database: {e}")
                db_session.rollback()
        # db_session.close() # 一時的に閉じない。テキストファイル作成後にも使用する可能性があるため。

        # --- テキストファイルの生成 ---
        text_file_path = f"{temp_dir}/{words_for_filename}_all.txt"
        try:
            with open(text_file_path, "w", encoding='utf-8') as f: # エンコーディング指定
                for ind, data in enumerate(filtered_results):
                    # Streamlit の txt ファイル出力形式に近づける
                    f.write(f"{ind + 1 :07}\n") # インデックス (7桁ゼロ埋め)
                    f.write(f"{data.get('title', 'N/A')}\n")
                    f.write(f"{data.get('super_title', '')}\n") # スーパータイトル
                    f.write(f"{data.get('date_text', 'N/A')}\n") # 日付
                    f.write(f"{data.get('view_count', 'N/A')}\n")
                    f.write(f"{data.get('video_url', 'N/A')}\n")
                    f.write(f"{data.get('channel_name', 'N/A')}\n")
                    f.write(f"{data.get('channel_url', 'N/A')}\n")
                    f.write("\n----------\n")
            logging.info(f"Text file created at: {text_file_path}")
        except Exception as e:
            logging.error(f"Error creating text file: {e}")
            # テキストファイル作成失敗は致命的ではない

        db_session.close() # ここでセッションを閉じる

        # --- JSON レスポンス: ソートされた結果を返す ---
        # フロントエンド表示用に必要な情報のみを抽出
        results_for_frontend = []
        for res in filtered_results:
            results_for_frontend.append({
                'title': res.get('title', 'N/A'),
                'url': res.get('video_url', '#'),
                'channel_name': res.get('channel_name', 'N/A'),
                'channel_url': res.get('channel_url', '#'),
                'date': res.get('date_text', 'N/A'), # 必要なら整形
                'view_count': res.get('view_count', 'N/A'),
                # 必要に応じて super_title なども追加
            })

        return jsonify({
            'message': 'Search, scraping, filtering, recursive search, sorting, and file creation completed.',
            'total_results': len(filtered_results),
            'results': results_for_frontend, # フロントエンド用に整形された結果
            'session_id': session['session_id'],
        })

    except Exception as e:
        logging.error(f"Error in search route: {e}", exc_info=True)
        # DBセッションが開いていたら閉じる
        try:
            if 'db_session' in locals() and db_session:
                db_session.close()
        except:
            pass
        return jsonify({'error': f'Search error: {str(e)}'}), 500

@app.route('/download/<file_type>')
def download_file(file_type):
    try:
        if 'session_id' not in session:
            return jsonify({'error': 'No active session'}), 400
        temp_dir = f"removefolder/{session['session_id']}"

        if file_type == 'sqlite':
            file_path = f"{temp_dir}/sqlite_.db"
            if os.path.exists(file_path):
                return send_file(file_path, as_attachment=True, download_name='youtube_search.db')
        elif file_type == 'txt':
             # セッションディレクトリ内の *_all.txt ファイルを探す
             txt_files = [f for f in os.listdir(temp_dir) if f.endswith('_all.txt')]
             if txt_files:
                 # 複数ある場合は最初のものを選択
                 file_path = os.path.join(temp_dir, txt_files[0])
                 if os.path.exists(file_path):
                     # ファイル名を適切に設定
                     suggested_filename = txt_files[0]
                     return send_file(file_path, as_attachment=True, download_name=suggested_filename)
                 else:
                     logging.error(f"Text file path does not exist: {file_path}")
                     return jsonify({'error': 'Text file not found on disk'}), 500
             else:
                 logging.warning(f"No text file found in session directory: {temp_dir}")
                 return jsonify({'error': 'Text file not found'}), 404
        return jsonify({'error': 'File type not supported or file not found'}), 404
    except Exception as e:
        logging.error(f"Error in download route: {e}", exc_info=True)
        return jsonify({'error': f'Download error: {str(e)}'}), 500

@app.route('/clear_session', methods=['POST'])
def clear_session():
    try:
        if 'session_id' in session:
            temp_dir = f"removefolder/{session['session_id']}"
            if os.path.exists(temp_dir):
                shutil.rmtree(temp_dir)
                logging.info(f"Cleared session directory: {temp_dir}")
            session.clear()
            logging.info("Session cleared.")
        return jsonify({'status': 'Session cleared successfully.'})
    except Exception as e:
        logging.error(f"Error clearing session: {e}")
        return jsonify({'error': str(e)}), 500

@app.errorhandler(500)
def internal_error(error):
    logging.error(f"Internal server error: {error}")
    return jsonify({'error': 'Internal server error'}), 500

@app.errorhandler(404)
def not_found(error):
    return jsonify({'error': 'Not found'}), 404

if __name__ == '__main__':
    # Ensure removefolder directory exists
    my_makedirs('removefolder')
    app.run(debug=True, host='0.0.0.0', port=5000)

# app.py
from flask import Flask, render_template, request, jsonify, send_file, session, Response # render_template を追加
import httpx
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
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy import create_engine, Column, Integer, String
from sqlalchemy.orm import sessionmaker
import random
import threading

app = Flask(__name__)
app.secret_key = os.environ.get('FLASK_SECRET_KEY', secrets.token_urlsafe(32))

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# --- プロキシローテーション (proxywhirl) ---
try:
    from proxywhirl import (
        ProxyWhirl,
        ProxyConfiguration,
        BootstrapConfig,
        ProxyPoolEmptyError,
        ProxyConnectionError,
        RequestQueueFullError,
    )
    _pw_config = ProxyConfiguration(
        timeout=8,               # 死んだプロキシに長く粘らないよう短縮（元15秒）
        max_retries=2,           # プロキシ切り替えの試行回数を短縮（元3回）
        verify_ssl=False,        # 元の ssl_context (CERT_NONE) 相当
        health_check_enabled=True,
    )
    # デフォルト設定だと全ソースから候補を集めて数万〜十数万件になり、
    # 検証（validate）が終わらずリクエストをブロックし続けるため、
    # ソース数・候補数の上限を絞って初回ブートストラップを高速化する。
    _pw_bootstrap = BootstrapConfig(
        sample_size=5,        # 参照するソース数を絞る（デフォルト10）
        max_proxies=50,       # 候補プロキシ数の上限（デフォルト無制限）
        validate_proxies=True,
        timeout=8,
        max_concurrent=20,
        show_progress=False,  # richの進捗バーでgunicornログを埋め尽くさない
    )
    rotator = ProxyWhirl(config=_pw_config, bootstrap=_pw_bootstrap)  # 空プールは初回利用時に自動取得
    PROXY_ENABLED = True
except Exception as e:
    logging.warning(f"[Proxy] proxywhirlの初期化に失敗しました。プロキシなしで動作します: {e}")
    rotator = None
    PROXY_ENABLED = False
    # 個別のダミー例外クラスを定義（Exceptionへの一括エイリアスをやめる）。
    # 参照箇所はすべて `if PROXY_ENABLED and rotator is not None:` でガードされており
    # PROXY_ENABLED=False の場合はそもそも到達しないため実害はないが、
    # 可読性・将来の変更耐性のために個別クラス化しておく。
    class ProxyPoolEmptyError(Exception):
        pass
    class ProxyConnectionError(Exception):
        pass
    class RequestQueueFullError(Exception):
        pass

def _prewarm_proxy_pool():
    """
    アプリ起動時にバックグラウンドでプロキシプールを事前にブートストラップしておく。
    これをやらないと、最初の検索リクエストの中で初めてブートストラップ（候補取得＋検証）が走り、
    その間ずっとレスポンスが返らず、Cloudflareトンネルなどのアイドルタイムアウトで
    接続が切られてしまうため。
    """
    if not (PROXY_ENABLED and rotator is not None):
        return
    try:
        # 公開APIに事前ブートストラップ用のメソッドが無いため、内部メソッドを利用する。
        # （proxywhirlの将来のバージョンで変更される可能性がある点に注意）
        if hasattr(rotator, "_ensure_bootstrap_for_empty_pool"):
            rotator._ensure_bootstrap_for_empty_pool()
        stats = rotator.get_pool_stats()
        logging.info(f"[Proxy] 事前ブートストラップ完了: {stats}")
    except Exception as e:
        logging.warning(f"[Proxy] 事前ブートストラップに失敗しました（検索時に改めて試行されます）: {e}")

if PROXY_ENABLED and rotator is not None:
    threading.Thread(target=_prewarm_proxy_pool, daemon=True).start()

REQUEST_HEADERS = {
    'Referer': 'http://www.google.com/',
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
}

# SQLAlchemy setup
class Base(DeclarativeBase):
    pass

class Item(Base):
    __tablename__ = 'item'
    id = Column(Integer, primary_key=True)
    title_name = Column(String)
    video_id = Column(String)
    channel_id = Column(String)
    date_time = Column(String) # 文字列として保存
    view_counter = Column(String)
    channel_name = Column(String)

def fetch_url(url, timeout=10):
    """
    proxywhirl の rotator 経由でURLを取得する（自動プロキシ選択・サーキットブレーカー・リトライ付き）。
    プロキシプールが空/全滅している場合、または proxywhirl が使えない場合は
    プロキシなしの直接接続（httpx）にフォールバックする。
    戻り値は httpx.Response。
    """
    if PROXY_ENABLED and rotator is not None:
        try:
            return rotator.get(url, headers=REQUEST_HEADERS, timeout=timeout)
        except (ProxyPoolEmptyError, ProxyConnectionError, RequestQueueFullError) as e:
            logging.warning(f"[Proxy] プロキシ経由の取得に失敗、直接接続にフォールバック: {e}")
        except Exception as e:
            logging.warning(f"[Proxy] 予期しないエラーのため直接接続にフォールバック: {e}")

    # フォールバック: プロキシなしで直接接続
    return httpx.get(url, headers=REQUEST_HEADERS, timeout=timeout, verify=False, follow_redirects=True)

def my_makedirs(path):
    if not os.path.isdir(path):
        os.makedirs(path)

_engine_cache = {}

def get_session_db(temp_dir):
    if temp_dir not in _engine_cache:
        engine = create_engine(
            f'sqlite:///{temp_dir}/sqlite_.db',
            pool_pre_ping=True,
            connect_args={'check_same_thread': False},
        )
        Base.metadata.create_all(engine)
        _engine_cache[temp_dir] = engine
    Session = sessionmaker(bind=_engine_cache[temp_dir])
    return Session()

# --- 移植した first_access 関数 ---
def first_access(keyword):
    """Streamlit コードから移植した first_access 関数"""
    target_url = "https://www.youtube.com/results?search_query=" + keyword
    try:
        search_response = fetch_url(target_url, timeout=10)
        if search_response.status_code != 200:
            time.sleep(1)
            return [], []
        html_strings = search_response.text

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

    except httpx.HTTPStatusError as e:
        logging.error(f"HTTP Error during first_access for {keyword}: {e}")
    except httpx.HTTPError as e:
        logging.error(f"HTTPX Error during first_access for {keyword}: {e}")
    except (ProxyPoolEmptyError, ProxyConnectionError, RequestQueueFullError) as e:
        logging.error(f"Proxy Error during first_access for {keyword}: {e}")
    except json.JSONDecodeError as e:
        logging.error(f"JSON Decode Error during first_access for {keyword}: {e}")
    except Exception as e:
        logging.error(f"Unexpected error in first_access for {keyword}: {e}")

    time.sleep(2) # エラー時も少し待機
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
        response = fetch_url(target_url, timeout=15)
        if response.status_code != 200:
             logging.warning(f"Failed to fetch {target_url}, status code: {response.status_code}")
             return None

        html_strings = response.text

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

    except httpx.HTTPStatusError as e:
        logging.error(f"HTTP Error scraping {target_url}: {e}")
    except httpx.HTTPError as e:
        logging.error(f"HTTPX Error scraping {target_url}: {e}")
    except (ProxyPoolEmptyError, ProxyConnectionError, RequestQueueFullError) as e:
        logging.error(f"Proxy Error scraping {target_url}: {e}")
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

def cleanup_session_files(temp_dir, delay_seconds=300):
    """
    指定されたディレクトリ内の sqlite_.db と results.txt を
    delay_seconds 秒後に削除する。
    """
    def delete_files():
        try:
            # delay_seconds 秒待機
            time.sleep(delay_seconds)
            
            db_file_path = os.path.join(temp_dir, 'sqlite_.db')
            txt_file_path = os.path.join(temp_dir, 'results.txt') # ファイル名を results.txt に統一した前提
            
            # データベースファイルを削除
            if os.path.exists(db_file_path):
                os.remove(db_file_path)
                logging.info(f"[Cleanup] Deleted database file: {db_file_path}")
            else:
                logging.debug(f"[Cleanup] Database file not found (skipped): {db_file_path}")
                
            # テキストファイルを削除
            if os.path.exists(txt_file_path):
                os.remove(txt_file_path)
                logging.info(f"[Cleanup] Deleted text file: {txt_file_path}")
            else:
                logging.debug(f"[Cleanup] Text file not found (skipped): {txt_file_path}")

        except Exception as e:
            logging.error(f"[Cleanup] Error during file cleanup for {temp_dir}: {e}", exc_info=True)

    # ファイル削除関数をバックグラウンドスレッドで実行
    cleanup_thread = threading.Thread(target=delete_files, daemon=True)
    cleanup_thread.start()
    logging.info(f"[Cleanup] Started cleanup thread for {temp_dir} to run in {delay_seconds} seconds.")

# --- Flask Routes ---

@app.route('/')
def index():
    try:
        if 'session_id' not in session:
            session['session_id'] = secrets.token_urlsafe()
        # HTML テンプレートファイルをレンダリング
        return render_template('index.html')
    except Exception as e:
        logging.error(f"Error in index route: {e}")
        return f"<h1>YouTube Search</h1><p>Error: {str(e)}</p>", 500

# --- 新しい SSE ルートを追加 ---

@app.route('/search_sse')
def search_sse():
    from flask import stream_with_context  # トップレベルで未インポートのためここで追加

    def generate():
        db_session = None
        try:
            keywords_input = request.args.get('keywords', '').strip()
            if not keywords_input:
                yield f"data: {json.dumps({'type': 'error', 'message': 'キーワードがありません。'})}\n\n"
                return

            # セッションと一時ディレクトリの設定
            if 'session_id' not in session:
                session['session_id'] = secrets.token_urlsafe()
            temp_dir = os.path.join('removefolder', session['session_id'])
            my_makedirs(temp_dir)

            # データベースセッションの取得
            db_session = get_session_db(temp_dir)

            # Streamlit と同様にキーワードを処理
            words_list = keywords_input.split()
            words_joined = "+".join(words_list)
            KEYWORDS_QUOTED = urllib.parse.quote(words_joined)

            logging.info(f"[SSE] Searching YouTube for: {KEYWORDS_QUOTED}")
            yield f"data: {json.dumps({'type': 'progress', 'message': f'キーワードを処理中: {keywords_input}'})}\n\n"

            # --- フィルタリング用正規表現の定義 (Streamlit から移植) ---
            strings = ""
            strings2 = ""
            for word in words_list:
                strings += '(?=.*' + word + ')'
                strings2 += word + '|'
            strings2 = strings2.rstrip('|')
            strings = strings + ".*$" # 全てのキーワードを含む（ログ表示用）
            # NG ワードフィルター
            r_strings_NG = re.compile(r"\#shorts|ひろゆき|ホリエモン|堀江貴文|武田邦彦", flags=re.IGNORECASE)
            # キーワードフィルター (OR 検索 - 実際のフィルタで使用するのはこちらのみ)
            r_strings2 = re.compile(strings2, flags=re.IGNORECASE)
            logging.info(f"[SSE] Filter regex - AND: {strings}, OR: {strings2}")
            yield f"data: {json.dumps({'type': 'progress', 'message': 'フィルタ条件を設定しました。'})}\n\n"

            # first_access を呼び出して初期データを取得
            videoIds_initial = []
            channel_names_initial = []
            if KEYWORDS_QUOTED:
                yield f"data: {json.dumps({'type': 'progress', 'message': '初期検索を実行中...'})}\n\n"
                for attempt in range(3):
                     videoIds_initial, channel_names_initial = first_access(KEYWORDS_QUOTED)
                     if videoIds_initial:
                         logging.info(f"[SSE] Successfully fetched {len(videoIds_initial)} initial video IDs.")
                         yield f"data: {json.dumps({'type': 'progress', 'message': f'初期検索完了: {len(videoIds_initial)} 件の動画候補'})}\n\n"
                         break
                     else:
                         logging.warning(f"[SSE] Attempt {attempt + 1} failed to fetch initial video IDs. Retrying...")
                         yield f"data: {json.dumps({'type': 'progress', 'message': f'初期検索リトライ中... ({attempt + 1}/3)'})}\n\n"
                         time.sleep(2)

            if not videoIds_initial:
                 yield f"data: {json.dumps({'type': 'error', 'message': '初期検索に失敗しました。'})}\n\n"
                 db_session.close()
                 return

            # 重複排除 (Streamlit の dict.fromkeys を使用)
            videoIds_unique = list(dict.fromkeys(videoIds_initial))

            # --- 検索とフィルタリングのメインループ ---
            all_videoIds = videoIds_unique[:] # 初期リストで初期化
            visited_urls = set()
            filtered_results = []
            BASEURL = 'https://www.youtube.com/watch?v='

            # --- 重要: 処理する動画数の上限を引き上げ ---
            MAX_VIDEOS_TO_PROCESS = 1000 # 例として100に増やす
            processed_count = 0
            index = 0
            total_ids_to_process = len(all_videoIds) # 初期リストの長さ

            yield f"data: {json.dumps({'type': 'progress', 'message': f'詳細情報取得を開始します。対象動画数: {total_ids_to_process}'})}\n\n"

            while index < len(all_videoIds) and processed_count < MAX_VIDEOS_TO_PROCESS:
                video_id = all_videoIds[index]
                index += 1
                processed_count += 1

                # 進捗表示 (5件ごと、または最後)
                if processed_count % 5 == 0 or index >= len(all_videoIds) or processed_count >= MAX_VIDEOS_TO_PROCESS:
                     yield f"data: {json.dumps({'type': 'progress', 'message': f'動画情報を取得中... ({processed_count}/{min(len(all_videoIds), MAX_VIDEOS_TO_PROCESS)}) ID: {video_id}'})}\n\n"

                target_url = BASEURL + video_id
                if target_url in visited_urls:
                    continue
                visited_urls.add(target_url)

                logging.info(f"[SSE] Processing video {processed_count}/{MAX_VIDEOS_TO_PROCESS} (List index {index-1}/{len(all_videoIds)}): {video_id}")

                # 個別動画ページから詳細情報を取得
                if index > 100:
                    time.sleep(random.uniform(2, 4))
                else:  # index <= 100（境界の100も含む）
                    time.sleep(random.uniform(2, 3))
                
                video_details = scrape_video_details(video_id)
                if not video_details:
                    yield f"data: {json.dumps({'type': 'progress', 'message': f'取得失敗 - スキップ: {video_id}'})}\n\n"
                    continue

                # --- フィルタリング (Streamlit ロジックを適用) ---
                temp_channel_name = video_details.get('channel_name', '')
                temp_title = video_details.get('title', '')
                temp_super_title = video_details.get('super_title', '')
                temp_description = video_details.get('description', '')

                # NGワードチェック
                if re.search(r_strings_NG, temp_channel_name) or re.search(r_strings_NG, temp_title):
                    logging.info(f"[SSE] NG word found in channel ({temp_channel_name}) or title ({temp_title}) for video {video_id}. Skipping.")
                    yield f"data: {json.dumps({'type': 'progress', 'message': f'NGワード該当 - スキップ: {video_id}'})}\n\n"
                    continue

                check = False
                # キーワードチェック (OR条件 - タイトル、スーパータイトル、説明)
                if re.search(r_strings2, temp_title) or re.search(r_strings2, temp_super_title) or re.search(r_strings2, temp_description):
                     check = True
                     logging.info(f"[SSE] Keyword match found for video {video_id}.")
                     yield f"data: {json.dumps({'type': 'progress', 'message': f'キーワード一致: {video_id}'})}\n\n"

                if not check:
                    logging.info(f"[SSE] No keyword match for video {video_id}. Skipping.")
                    continue

                # --- 条件に合致した場合の処理 ---
                filtered_results.append(video_details)
                # クライアントに個別結果を送信 (オプション)
                result_for_frontend = {
                    'title': video_details.get('title', 'N/A'),
                    'url': video_details.get('video_url', '#'),
                    'channel_name': video_details.get('channel_name', 'N/A'),
                    'channel_url': video_details.get('channel_url', '#'),
                    'date': video_details.get('date_text', 'N/A'),
                    'view_count': video_details.get('view_count', 'N/A'),
                }
                yield f"data: {json.dumps({'type': 'result', 'result': result_for_frontend})}\n\n"

                 # --- 変更後: Item オブジェクトを作成し、即時データベースに保存 ---
                try:
                    item = Item()
                    item.title_name = video_details.get('title', '')
                    item.video_id = video_details.get('video_url', '')
                    item.channel_id = video_details.get('channel_url', '')
                    item.date_time = video_details.get('date_text', '') # 文字列を保存
                    item.view_counter = video_details.get('view_count', '')
                    item.channel_name = video_details.get('channel_name', '')
                     
                    db_session.add(item) # データベースセッションに追加
                    if processed_count % 10 == 0:
                        db_session.commit()  # 10件ごとにまとめてコミット
                    else:
                        db_session.flush()   # SQLite書き込みロックを毎回発生させないよう flush に留める
                    logging.info(f"[SSE] Saved 1 item (ID: {video_details.get('video_id', 'N/A')}) to database.")
                    # オプション: 進捗に保存件数を追加
                    yield f"data: {json.dumps({'type': 'progress', 'message': f'動画情報を取得中... ({processed_count}/{min(len(all_videoIds), MAX_VIDEOS_TO_PROCESS)}) ID: {video_id} (DB保存済み)'})}\n\n"

                except Exception as e:
                    logging.error(f"[SSE] Error saving item (ID: {video_details.get('video_id', 'N/A')}) to database: {e}")
                    db_session.rollback() # エラー時はロールバック
                    # オプション: エラーを進捗として通知
                    yield f"data: {json.dumps({'type': 'progress', 'message': f'動画 {video_id} のDB保存エラー: {str(e)[:30]}...'})}\n\n"
                # ---

                # --- 関連動画の収集 ---
                # pop で取り出して video_details（filtered_results が保持する同一オブジェクト）から
                # 即座に削除する。raw_json_dict は数百KB〜MB級になり得るため、
                # 保持したままだと大量件数処理時にメモリを圧迫する。
                json_dict = video_details.pop('raw_json_dict', None)
                if json_dict:
                    try:
                        # 正しいパスで関連動画の results 配列を取得 (test1.json.txt の構造に基づく)
                        if 'contents' in json_dict and 'twoColumnWatchNextResults' in json_dict['contents']:
                            secondary_results = json_dict['contents']['twoColumnWatchNextResults'].get('secondaryResults', {}).get('secondaryResults', {}).get('results', [])
                            
                            logging.debug(f"[SSE] Found {len(secondary_results) if isinstance(secondary_results, list) else 'N/A'} items in secondary results for video {video_id}")

                            added_related_count = 0
                            # secondary_results がリストであることを確認
                            if isinstance(secondary_results, list):
                                for result in secondary_results:
                                    related_video_id = None
                                    # compactVideoRenderer から videoId を取得
                                    if 'compactVideoRenderer' in result:
                                        related_video_id = result['compactVideoRenderer'].get('videoId')
                                        logging.debug(f"[SSE] Found related video ID via compactVideoRenderer: {related_video_id}")
                                    # lockupViewModel から contentId を取得
                                    elif 'lockupViewModel' in result:
                                        related_video_id = result['lockupViewModel'].get('contentId')
                                        logging.debug(f"[SSE] Found related video ID via lockupViewModel: {related_video_id}")
                                    
                                    # 有効な ID が取得できた場合の処理
                                    if related_video_id:
                                        related_video_url = BASEURL + related_video_id
                                        # 新しい動画IDで、かつ訪問済みでも処理待ちでもない場合に追加
                                        if related_video_id not in all_videoIds and related_video_url not in visited_urls:
                                             all_videoIds.append(related_video_id)
                                             added_related_count += 1
                                             logging.debug(f"[SSE] Added related video ID: {related_video_id}")
                                             # リストが長くなりすぎないように制限 (オプション)
                                             if len(all_videoIds) > MAX_VIDEOS_TO_PROCESS * 3: # 制限を緩和
                                                 logging.warning("[SSE] Related video list is very long, trimming.")
                                                 all_videoIds = all_videoIds[:MAX_VIDEOS_TO_PROCESS * 3]
                                                 # リストがトリミングされたら、これ以上の追加をやめる
                                                 break 
                            
                            if added_related_count > 0:
                                 yield f"data: {json.dumps({'type': 'progress', 'message': f'関連動画 {added_related_count} 件を追加。リストサイズ: {len(all_videoIds)}'})}\n\n"
                            elif len(secondary_results) > 0:
                                 # 関連動画はあったが、追加されなかった場合（すべて重複など）
                                 logging.debug(f"[SSE] Found related videos for {video_id}, but none were added (duplicates/visited). List size remains: {len(all_videoIds)}")
                            else:
                                 # 関連動画が見つからなかった場合
                                 logging.debug(f"[SSE] No related videos found in the expected JSON path for video {video_id}.")

                    except (KeyError, IndexError, TypeError) as e:
                        logging.error(f"[SSE] Error extracting related videos for {video_id}: {e}")
                        yield f"data: {json.dumps({'type': 'progress', 'message': f'関連動画取得エラー ({video_id}): {str(e)[:30]}...'})}\n\n"
                    except Exception as e: # その他の予期しないエラーもキャッチ
                        logging.error(f"[SSE] Unexpected error while processing related videos for {video_id}: {e}", exc_info=True)
                        yield f"data: {json.dumps({'type': 'progress', 'message': f'関連動画処理中に予期せぬエラー ({video_id})'})}\n\n"

                    del json_dict  # 明示的に解放

            # --- ループ終了後: items_to_save に関連する保存処理は削除 ---
            # ループ内で個別に保存しているので、ここでの一括保存は不要
            # ただし、10件ごとバッチコミットの端数が残っている可能性があるため、
            # クローズ前に確実にコミットする
            try:
                db_session.commit()
                logging.info("[SSE] Final commit of remaining batched items.")
            except Exception as e:
                logging.error(f"[SSE] Error on final commit: {e}")
                db_session.rollback()

            try:
                db_session.close()
                logging.info("[SSE] Database session closed.")
            except Exception as e:
                logging.error(f"[SSE] Error closing database session: {e}")

            yield f"data: {json.dumps({'type': 'progress', 'message': 'データ収集完了。結果をソート中...'})}\n\n"

            # --- 結果のソート ---
            try:
                filtered_results.sort(key=lambda x: parse_date_for_sorting(x.get('date_text', '')), reverse=True)
                logging.info("[SSE] Results sorted by date (newest first).")
                yield f"data: {json.dumps({'type': 'progress', 'message': '結果を日付順にソートしました。'})}\n\n"
            except Exception as e:
                logging.error(f"[SSE] Error sorting results: {e}")
                yield f"data: {json.dumps({'type': 'progress', 'message': f'ソートエラー: {str(e)}'})}\n\n"

            # --- テキストファイルの生成 ---
            yield f"data: {json.dumps({'type': 'progress', 'message': 'テキストファイルを生成中...'})}\n\n"
            text_file_path = os.path.join(temp_dir, "results_all.txt")
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
                logging.info(f"[SSE] Text file created at: {text_file_path}")
                yield f"data: {json.dumps({'type': 'progress', 'message': 'テキストファイルを生成しました。'})}\n\n"
            except Exception as e:
                logging.error(f"[SSE] Error creating text file: {e}")
                yield f"data: {json.dumps({'type': 'progress', 'message': f'テキストファイル生成エラー: {str(e)}'})}\n\n"

            # --- 新規追加: ファイル自動削除タイマーを起動 ---
            # cleanup_session_files 関数を呼び出して、バックグラウンドでタイマー開始
            try:
                cleanup_session_files(temp_dir, delay_seconds=300) # 300秒 = 5分
            except Exception as e:
                logging.error(f"[SSE] Failed to start cleanup timer for {temp_dir}: {e}")
            # --- ここまで新規追加 ---
            
            # --- JSON レスポンス: ソートされた結果を返す ---
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

            # --- 最終完了メッセージを送信 ---
            yield f"data: {json.dumps({'type': 'done', 'total_results': len(results_for_frontend), 'message': '検索完了'})}\n\n"
            logging.info(f"[SSE] Search completed. Total results: {len(results_for_frontend)}")

        except Exception as e:
            logging.error(f"[SSE] Error in search_sse generator: {e}", exc_info=True)
            yield f"data: {json.dumps({'type': 'error', 'message': f'サーバーエラー: {str(e)}'})}\n\n"
        finally:
            # ここより上のどの経路（正常完了・early return・例外）を通っても、
            # db_session が開いたままにならないよう最後に必ず確実にクローズする。
            # close() 済みセッションに対して commit()/rollback()/close() を再度呼んでも
            # SQLAlchemy 2.0 系ではエラーにならないことを確認済み（no-op）。
            # commit() を先に試みるのは、例外がバッチ処理の途中（flush済み・未commitの
            # 最大9件）で発生した場合に、それらを救済できる可能性があるため。
            if db_session is not None:
                try:
                    db_session.commit()
                except Exception:
                    try:
                        db_session.rollback()
                    except Exception:
                        pass
                finally:
                    try:
                        db_session.close()
                    except Exception as close_err:
                        logging.error(f"[SSE] Error closing db_session in finally block: {close_err}")

    # text/event-stream 形式でレスポンスをストリームする
    return Response(stream_with_context(generate()), mimetype='text/event-stream')

@app.route('/download/<file_type>')
def download_file(file_type):
    try:
        logging.info(f"[Download] Request received for file_type: {file_type}")
        if 'session_id' not in session:
            logging.warning("[Download] No active session found.")
            return jsonify({'error': 'No active session'}), 400

        temp_dir = os.path.join('removefolder', session['session_id'])
        logging.info(f"[Download] Looking for files in session directory: {temp_dir}")

        if not os.path.exists(temp_dir):
            logging.error(f"[Download] Session directory does not exist: {temp_dir}")
            return jsonify({'error': 'Session directory not found'}), 404

        try:
            files_in_dir = os.listdir(temp_dir)
            logging.info(f"[Download] Files in session directory: {files_in_dir}")
        except Exception as e:
            logging.error(f"[Download] Error listing session directory: {e}")

        file_path = None
        suggested_filename = "youtube_search"

        if file_type == 'sqlite':
            file_path = os.path.join(temp_dir, "sqlite_.db")
            suggested_filename = "youtube_search.db"
        elif file_type == 'txt':
            txt_files = [f for f in os.listdir(temp_dir) if f.endswith('_all.txt')]
            if txt_files:
                file_path = os.path.join(temp_dir, txt_files[0])
                suggested_filename = 'results_all.txt'
            else:
                logging.warning(f"[Download] No text file found in session directory: {temp_dir}")
                return jsonify({'error': 'Text file not found'}), 404
        else:
            logging.warning(f"[Download] Unsupported file type requested: {file_type}")
            return jsonify({'error': 'File type not supported'}), 400

        if file_path and os.path.exists(file_path):
            logging.info(f"[Download] Attempting to send file: {file_path}")
            try:
                # send_file はファイルをストリーミングで送信するため、
                # ファイル全体をメモリに読み込む方式（大きなファイルでメモリを圧迫する）より安全。
                return send_file(
                    file_path,
                    mimetype='application/octet-stream',
                    as_attachment=True,
                    download_name=suggested_filename,
                )
            except Exception as e:
                logging.error(f"[Download] Error reading or sending file {file_path}: {e}", exc_info=True)
                return jsonify({'error': f'Error reading file: {str(e)}'}), 500
        else:
            logging.error(f"[Download] File not found at: {file_path}")
            return jsonify({'error': 'File not found on disk'}), 404

    except Exception as e:
        logging.error(f"[Download] Error in download route: {e}", exc_info=True)
        return jsonify({'error': f'Download error: {str(e)}'}), 500

@app.route('/clear_session', methods=['POST'])
def clear_session():
    try:
        if 'session_id' in session:
            temp_dir = os.path.join('removefolder', session['session_id'])
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
    # --- 重要: Gunicorn タイムアウトを延長 ---
    # このコードを直接実行する場合 (例: python app.py) は関係ありませんが、
    # Gunicorn で実行する場合は、コマンドラインで --timeout を指定してください。
    # 例: gunicorn --timeout 300 app:app
    # debug=True は Werkzeug の対話的デバッガを有効化するが、
    # これは任意コード実行に繋がりうるため、Cloudflareトンネル等で公開する場合は危険。
    # 明示的に FLASK_DEBUG=1 を設定した時だけ有効にする。
    _debug_mode = os.environ.get('FLASK_DEBUG', '0') == '1'
    app.run(debug=_debug_mode, host='0.0.0.0', port=5000)

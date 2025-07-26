# app.py
from flask import Flask, render_template, request, jsonify, send_file, session # render_template を追加
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
        #time.sleep(2) # リクエスト間隔を空ける (2秒に変更)
        # setup_requests() で設定された opener を使用
        response = urllib.request.urlopen(target_url, timeout=15) # タイムアウトを15秒に延長
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
        # HTML テンプレートファイルをレンダリング
        return render_template('index.html')
    except Exception as e:
        logging.error(f"Error in index route: {e}")
        return f"<h1>YouTube Search</h1><p>Error: {str(e)}</p>", 500

# --- 新しい SSE ルートを追加 ---
import json

@app.route('/search_sse')
def search_sse():
    from flask import Response, stream_with_context
    import datetime # 必要に応じてインポート

    def generate():
        try:
            setup_requests()
            keywords_input = request.args.get('keywords', '').strip()
            if not keywords_input:
                yield f"data: {json.dumps({'type': 'error', 'message': 'キーワードがありません。'})}\n\n"
                return

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

            logging.info(f"[SSE] Searching YouTube for: {KEYWORDS_QUOTED}")
            yield f"data: {json.dumps({'type': 'progress', 'message': f'キーワードを処理中: {keywords_input}'})}\n\n"

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
            ids_channels_dict = dict(zip(videoIds_initial, channel_names_initial))

            # --- 検索とフィルタリングのメインループ ---
            all_videoIds = videoIds_unique[:] # 初期リストで初期化
            visited_urls = set()
            filtered_results = []
            items_to_save = []
            BASEURL = 'https://www.youtube.com/watch?v='

            # --- 重要: 処理する動画数の上限を引き上げ ---
            MAX_VIDEOS_TO_PROCESS = 5000 # 例として100に増やす
            processed_count = 0
            index = 0
            total_ids_to_process = len(all_videoIds) # 初期リストの長さ

            yield f"data: {json.dumps({'type': 'progress', 'message': f'詳細情報取得を開始します。対象動画数: {total_ids_to_process}'})}\n\n"

            while index < len(all_videoIds) and processed_count < MAX_VIDEOS_TO_PROCESS:
                video_id = all_videoIds[index]
                index += 1
                processed_count += 1

                # 進捗表示 (例: 10件ごと、または最後)
                if processed_count % 10 == 1 or index >= len(all_videoIds) or processed_count >= MAX_VIDEOS_TO_PROCESS:
                     #yield f"data: {json.dumps({'type': 'progress', 'message': f'動画情報を取得中... ({processed_count}/{min(total_ids_to_process, MAX_VIDEOS_TO_PROCESS)}) ID: {video_id}'})}\n\n"
                     yield f"data: {json.dumps({'type': 'progress', 'message': f'動画情報を取得中... ({processed_count}/{min(len(all_videoIds), MAX_VIDEOS_TO_PROCESS)}) ID: {video_id}'})}\n\n"

                target_url = BASEURL + video_id
                if target_url in visited_urls:
                    # yield f"data: {json.dumps({'type': 'progress', 'message': f'スキップ (既に訪問済み): {video_id}'})}\n\n" # 多すぎると煩雑
                    continue
                visited_urls.add(target_url)

                logging.info(f"[SSE] Processing video {processed_count}/{MAX_VIDEOS_TO_PROCESS} (List index {index-1}/{len(all_videoIds)}): {video_id}")

                # 個別動画ページから詳細情報を取得
                if index > 400:
                    time.sleep(2)
                elif index > 200:
                    time.sleep(1)    
                
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
                # else: # AND条件もチェックする場合 (オプション)
                #     if re.search(r_strings, temp_title) or re.search(r_strings, temp_super_title) or re.search(r_strings, temp_description):
                #         check = True
                #         logging.info(f"[SSE] AND Keyword match found for video {video_id}.")
                #         yield f"data: {json.dumps({'type': 'progress', 'message': f'ANDキーワード一致: {video_id}'})}\n\n"

                if not check:
                    logging.info(f"[SSE] No keyword match for video {video_id}. Skipping.")
                    # yield f"data: {json.dumps({'type': 'progress', 'message': f'キーワード不一致 - スキップ: {video_id}'})}\n\n" # 多すぎると煩雑
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
                json_dict = video_details.get('raw_json_dict')
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


                # --- 関連動画の収集 ---
                #json_dict = video_details.get('raw_json_dict')
                #if json_dict:
                #    # write file
                #    with open(f"test{index}.json", 'w') as f:
                #        json.dump(json_dict, f, indent=4)
                #    try:
                #        if 'contents' in json_dict and 'twoColumnWatchNextResults' in json_dict['contents']:
                #            secondary_results_section = json_dict['contents']['twoColumnWatchNextResults'].get('secondaryResults', {})
                #            if secondary_results_section:
                #                secondary_results = secondary_results_section.get('secondaryResults', {}).get('results', [])
                #                added_related_count = 0
                #                for result in secondary_results:
                #                    if 'compactVideoRenderer' in result:
                #                        related_video_id = result['compactVideoRenderer'].get('videoId')
                #                        if related_video_id:
                #                            related_video_url = BASEURL + related_video_id
                #                            # 新しい動画IDで、かつ訪問済みでも処理待ちでもない場合に追加
                #                            if related_video_id not in all_videoIds and related_video_url not in visited_urls:
                #                                 all_videoIds.append(related_video_id)
                #                                 added_related_count += 1
                #                                 logging.debug(f"[SSE] Added related video ID: {related_video_id}")
                #                                 # リストが長くなりすぎないように制限 (オプション)
                #                                 if len(all_videoIds) > MAX_VIDEOS_TO_PROCESS * 3: # 制限を緩和
                #                                     logging.warning("[SSE] Related video list is very long, trimming.")
                #                                     all_videoIds = all_videoIds[:MAX_VIDEOS_TO_PROCESS * 3]
                #                                     break
                #                if added_related_count > 0:
                #                     yield f"data: {json.dumps({'type': 'progress', 'message': f'関連動画 {added_related_count} 件を追加。リストサイズ: {len(all_videoIds)}'})}\n\n"
                #    except (KeyError, IndexError, TypeError) as e:
                #        logging.error(f"[SSE] Error extracting related videos for {video_id}: {e}")
                #        yield f"data: {json.dumps({'type': 'progress', 'message': f'関連動画取得エラー ({video_id}): {str(e)[:30]}...'})}\n\n"
                else:
                    print('raw_json_dict: error!')
                
                # リクエスト間隔を空ける (関数内で設定済み)

            yield f"data: {json.dumps({'type': 'progress', 'message': 'データ収集完了。結果をソート中...'})}\n\n"

            # --- 結果のソート ---
            try:
                filtered_results.sort(key=lambda x: parse_date_for_sorting(x.get('date_text', '')), reverse=True)
                logging.info("[SSE] Results sorted by date (newest first).")
                yield f"data: {json.dumps({'type': 'progress', 'message': '結果を日付順にソートしました。'})}\n\n"
            except Exception as e:
                logging.error(f"[SSE] Error sorting results: {e}")
                yield f"data: {json.dumps({'type': 'progress', 'message': f'ソートエラー: {str(e)}'})}\n\n"

            # --- データベースに保存 ---
            if items_to_save:
                try:
                    db_session.add_all(items_to_save)
                    db_session.commit()
                    logging.info(f"[SSE] Saved {len(items_to_save)} items to database.")
                    yield f"data: {json.dumps({'type': 'progress', 'message': f'データベースに {len(items_to_save)} 件保存しました。'})}\n\n"
                except Exception as e:
                    logging.error(f"[SSE] Error saving to database: {e}")
                    db_session.rollback()
                    yield f"data: {json.dumps({'type': 'progress', 'message': f'データベース保存エラー: {str(e)}'})}\n\n"
            db_session.close()

            # --- テキストファイルの生成 ---
            yield f"data: {json.dumps({'type': 'progress', 'message': 'テキストファイルを生成中...'})}\n\n"
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
                logging.info(f"[SSE] Text file created at: {text_file_path}")
                yield f"data: {json.dumps({'type': 'progress', 'message': 'テキストファイルを生成しました。'})}\n\n"
            except Exception as e:
                logging.error(f"[SSE] Error creating text file: {e}")
                yield f"data: {json.dumps({'type': 'progress', 'message': f'テキストファイル生成エラー: {str(e)}'})}\n\n"

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
            # DBセッションが開いていたら閉じる (generator内でのエラー処理は難しい場合があるため、try-finallyを使う方が良い)
            # try:
            #     if 'db_session' in locals() and db_session:
            #         db_session.close()
            # except:
            #     pass

    # text/event-stream 形式でレスポンスをストリームする
    return Response(stream_with_context(generate()), mimetype='text/event-stream')

@app.route('/download/<file_type>')
def download_file(file_type):
    try:
        logging.info(f"[Download] Request received for file_type: {file_type}")
        if 'session_id' not in session:
            logging.warning("[Download] No active session found.")
            return jsonify({'error': 'No active session'}), 400

        temp_dir = f"removefolder/{session['session_id']}"
        logging.info(f"[Download] Looking for files in session directory: {temp_dir}")
        # ディレクトリが存在するか確認
        if not os.path.exists(temp_dir):
            logging.error(f"[Download] Session directory does not exist: {temp_dir}")
            return jsonify({'error': 'Session directory not found'}), 404

        # 中身をリストアップ (デバッグ用)
        try:
            files_in_dir = os.listdir(temp_dir)
            logging.info(f"[Download] Files in session directory: {files_in_dir}")
        except Exception as e:
            logging.error(f"[Download] Error listing session directory: {e}")

        if file_type == 'sqlite':
            file_path = f"{temp_dir}/sqlite_.db"
            logging.info(f"[Download] Attempting to send SQLite file: {file_path}")
            # ファイルが存在するか確認
            if os.path.exists(file_path):
                file_size = os.path.getsize(file_path)
                logging.info(f"[Download] SQLite file exists, size: {file_size} bytes")
                # send_file が返すオブジェクトを確認
                response = send_file(file_path, as_attachment=True, download_name='youtube_search.db')
                logging.info(f"[Download] send_file called for SQLite. Response type: {type(response)}")
                return response
            else:
                logging.error(f"[Download] SQLite file not found at: {file_path}")
                return jsonify({'error': 'SQLite file not found on disk'}), 404

        elif file_type == 'txt':
            # ... (txt ファイル処理も同様にログを追加) ...
            txt_files = [f for f in os.listdir(temp_dir) if f.endswith('_all.txt')]
            if txt_files:
                file_path = os.path.join(temp_dir, txt_files[0])
                if os.path.exists(file_path):
                    # ファイル名を適切に設定
                    suggested_filename = txt_files[0]
                    logging.info(f"[Download] Attempting to send TXT file: {file_path}")
                    response = send_file(file_path, as_attachment=True, download_name=suggested_filename)
                    logging.info(f"[Download] send_file called for TXT. Response type: {type(response)}")
                    return response
                else:
                    logging.error(f"[Download] TXT file path does not exist: {file_path}")
                    return jsonify({'error': 'Text file not found on disk'}), 404
            else:
                logging.warning(f"[Download] No text file found in session directory: {temp_dir}")
                return jsonify({'error': 'Text file not found'}), 404

        logging.warning(f"[Download] Unsupported file type requested: {file_type}")
        return jsonify({'error': 'File type not supported'}), 400
    except Exception as e:
        logging.error(f"[Download] Error in download route: {e}", exc_info=True)
        return jsonify({'error': f'Download error: {str(e)}'}), 500

##@app.route('/download/<file_type>')
#def download_file(file_type):
#    try:
#        if 'session_id' not in session:
#            return jsonify({'error': 'No active session'}), 400
#        temp_dir = f"removefolder/{session['session_id']}"
#
#        if file_type == 'sqlite':
#            file_path = f"{temp_dir}/sqlite_.db"
#            if os.path.exists(file_path):
#                return send_file(file_path, as_attachment=True, download_name='youtube_search.db')
#        elif file_type == 'txt':
#             # セッションディレクトリ内の *_all.txt ファイルを探す
#             txt_files = [f for f in os.listdir(temp_dir) if f.endswith('_all.txt')]
#             if txt_files:
#                 # 複数ある場合は最初のものを選択
#                 file_path = os.path.join(temp_dir, txt_files[0])
#                 if os.path.exists(file_path):
#                     # ファイル名を適切に設定
#                     suggested_filename = txt_files[0]
#                     return send_file(file_path, as_attachment=True, download_name=suggested_filename)
#                 else:
#                     logging.error(f"Text file path does not exist: {file_path}")
#                     return jsonify({'error': 'Text file not found on disk'}), 500
#             else:
#                 logging.warning(f"No text file found in session directory: {temp_dir}")
#                 return jsonify({'error': 'Text file not found'}), 404
#        return jsonify({'error': 'File type not supported or file not found'}), 404
#    except Exception as e:
#        logging.error(f"Error in download route: {e}", exc_info=True)
#        return jsonify({'error': f'Download error: {str(e)}'}), 500

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
    # --- 重要: Gunicorn タイムアウトを延長 ---
    # このコードを直接実行する場合 (例: python app.py) は関係ありませんが、
    # Gunicorn で実行する場合は、コマンドラインで --timeout を指定してください。
    # 例: gunicorn --timeout 300 app:app
    app.run(debug=True, host='0.0.0.0', port=5000)

# youtube_scraper.py
import urllib.request
import urllib.parse
import re
import json
import time
import logging
from bs4 import BeautifulSoup
import urllib.error
import datetime

# --- setup_requests 関数 ---
# setup_requests 関数は app.py からコピーしてくるか、
# 必要に応じて引数として opener を受け取るように変更する必要があります。
# ここでは、単純化のため、必要な設定を関数内で行うようにします。
# より良い方法は、app.py で setup_requests を呼び出し、
# その opener を引数として渡すことです。
def setup_requests_for_scraper():
    """Setup urllib with better headers and SSL context for scraper"""
    import ssl
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
        logging.error(f"Error setting up requests in scraper: {e}")

# --- 移植した first_access 関数 ---
def first_access(keyword):
    """Streamlit コードから移植した first_access 関数"""
    # setup_requests() は app.py で呼び出されるか、ここでも呼び出す
    # setup_requests_for_scraper()
    time.sleep(1) # 必要に応じて調整
    target_url = "https://www.youtube.com/results?search_query=" + keyword
    try:
        # setup_requests_for_scraper() で設定された opener を使用
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
        time.sleep(2) # リクエスト間隔を空ける (2秒に変更)
        # setup_requests_for_scraper() で設定された opener を使用
        # app.py で setup_requests() を呼び出していれば、それも有効
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

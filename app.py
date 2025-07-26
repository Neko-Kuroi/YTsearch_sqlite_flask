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
logging.basicConfig(level=logging.INFO)

# HTML template as string
HTML_TEMPLATE = '''
<!DOCTYPE html>
<html lang="en">
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
        .warning {
            background-color: #fff3cd;
            border: 1px solid #ffeaa7;
            color: #856404;
            padding: 15px;
            border-radius: 5px;
            margin: 20px 0;
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
        .demo-note {
            background-color: #e7f3ff;
            border: 1px solid #b3d9ff;
            color: #0066cc;
            padding: 15px;
            border-radius: 5px;
            margin: 20px 0;
        }
    </style>
</head>
<body>
    <div class="container">
        <h1>YouTube Search 𓃻</h1>
        
        <div class="demo-note">
            <strong>Demo Mode:</strong> This application demonstrates YouTube search functionality. 
            Due to YouTube's anti-scraping measures, real-time scraping may be limited. 
            The app will show sample results for demonstration purposes.
        </div>
        
        <div class="search-section">
            <input type="text" id="keywords" placeholder="Enter search keywords..." maxlength="60">
            <button id="searchBtn" onclick="startSearch()">Search</button>
            <button id="cancelBtn" class="cancel-btn" onclick="cancelSearch()" style="display: none;">Cancel</button>
        </div>

        <div id="status" class="status"></div>

        <div class="download-section" id="downloadSection">
            <h3>Download Results</h3>
            <button class="download-btn" onclick="downloadFile('sqlite')">Download SQLite Database</button>
        </div>

        <div id="loading" class="loading" style="display: none;">
            <div class="spinner"></div>
            <p>Searching YouTube videos...</p>
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

        function startSearch() {
            const keywords = document.getElementById('keywords').value.trim();
            if (!keywords) {
                showStatus('Please enter search keywords.', 'error');
                return;
            }

            searchInProgress = true;
            document.getElementById('searchBtn').disabled = true;
            document.getElementById('cancelBtn').style.display = 'inline-block';
            document.getElementById('loading').style.display = 'block';
            document.getElementById('results').innerHTML = '';
            document.getElementById('downloadSection').style.display = 'none';
            hideStatus();

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
                showStatus(`Search completed! Found ${data.total} relevant videos.`, 'success');
                
                if (data.total > 0) {
                    document.getElementById('downloadSection').style.display = 'block';
                }
            })
            .catch(error => {
                searchInProgress = false;
                document.getElementById('searchBtn').disabled = false;
                document.getElementById('cancelBtn').style.display = 'none';
                document.getElementById('loading').style.display = 'none';
                showStatus('An error occurred during search: ' + error.message, 'error');
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
                });
            }
        }

        function displayResults(results) {
            const resultsDiv = document.getElementById('results');
            
            if (results.length === 0) {
                resultsDiv.innerHTML = '<p>No results found.</p>';
                return;
            }

            let html = `<h2>Search Results (${results.length} videos)</h2>`;
            
            results.forEach((result, index) => {
                html += `
                    <div class="result-item">
                        <div class="result-title">
                            <a href="${result.url}" target="_blank">${escapeHtml(result.title)}</a>
                        </div>
                        <div class="result-meta">
                            📅 ${result.date} | 👁️ ${result.view_count}
                        </div>
                        <div class="result-channel">
                            Channel: <a href="${result.channel_url}" target="_blank">${escapeHtml(result.channel_name)}</a>
                        </div>
                    </div>
                `;
            });
            
            resultsDiv.innerHTML = html;
        }

        function escapeHtml(text) {
            const map = {
                '&': '&amp;',
                '<': '&lt;',
                '>': '&gt;',
                '"': '&quot;',
                "'": '&#039;'
            };
            return text.replace(/[&<>"']/g, function(m) { return map[m]; });
        }

        function downloadFile(fileType) {
            const link = document.createElement('a');
            link.href = `/download/${fileType}`;
            link.download = `youtube_search.${fileType === 'sqlite' ? 'db' : 'txt'}`;
            document.body.appendChild(link);
            link.click();
            document.body.removeChild(link);
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
    date_time = Column(String)
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
            ('User-Agent', 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'),
            ('Accept', 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8'),
            ('Accept-Language', 'en-US,en;q=0.5'),
            ('Accept-Encoding', 'gzip, deflate'),
            ('Connection', 'keep-alive'),
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

def create_demo_results(keywords):
    """Create demo results when real scraping fails"""
    demo_results = [
        {
            'title': f'Sample Video About {keywords} - Tutorial',
            'url': 'https://www.youtube.com/watch?v=dQw4w9WgXcQ',
            'channel_name': 'Demo Channel',
            'channel_url': 'https://www.youtube.com/channel/UCuAXFkgsw1L7xaCfnd5JJOw',
            'date': '2024-01-15',
            'view_count': '1,234,567 views'
        },
        {
            'title': f'Advanced {keywords} Techniques and Tips',
            'url': 'https://www.youtube.com/watch?v=example2',
            'channel_name': 'Tech Tutorial Channel',
            'channel_url': 'https://www.youtube.com/channel/example2',
            'date': '2024-01-10',
            'view_count': '987,654 views'
        },
        {
            'title': f'Beginner\'s Guide to {keywords}',
            'url': 'https://www.youtube.com/watch?v=example3',
            'channel_name': 'Learning Hub',
            'channel_url': 'https://www.youtube.com/channel/example3',
            'date': '2024-01-05',
            'view_count': '543,210 views'
        }
    ]
    return demo_results

def safe_youtube_request(url, timeout=10):
    """Make a safe request to YouTube with proper error handling"""
    try:
        request = urllib.request.Request(url)
        request.add_header('User-Agent', 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36')
        
        with urllib.request.urlopen(request, timeout=timeout) as response:
            if response.getcode() == 200:
                return response.read().decode('utf-8')
            else:
                logging.warning(f"Non-200 response: {response.getcode()}")
                return None
    except urllib.error.HTTPError as e:
        logging.error(f"HTTP Error {e.code}: {e.reason}")
        return None
    except urllib.error.URLError as e:
        logging.error(f"URL Error: {e.reason}")
        return None
    except socket.timeout:
        logging.error("Request timed out")
        return None
    except Exception as e:
        logging.error(f"Unexpected error: {e}")
        return None

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
        setup_requests()
        
        keywords = request.json.get('keywords', '').strip()
        if not keywords:
            return jsonify({'error': 'Keywords are required'}), 400

        # Create session directory
        if 'session_id' not in session:
            session['session_id'] = secrets.token_urlsafe()
        
        temp_dir = f"removefolder/{session['session_id']}"
        my_makedirs(temp_dir)
        
        # Get database session
        db_session = get_session_db(temp_dir)
        
        # Process keywords for search
        words = "+".join(keywords.split())
        KEYWORDS = urllib.parse.quote(words)
        
        results = []
        
        # Try to get real YouTube search results
        try:
            search_url = f"https://www.youtube.com/results?search_query={KEYWORDS}"
            html_content = safe_youtube_request(search_url, timeout=5)
            
            if html_content and len(html_content) > 1000:  # Basic check for valid content
                # Try to extract video data (simplified version)
                soup = BeautifulSoup(html_content, 'html.parser')
                
                # Look for script tags containing video data
                for script in soup.find_all('script'):
                    script_content = str(script)
                    if 'ytInitialData' in script_content:
                        try:
                            # Extract JSON data
                            start = script_content.find('{')
                            end = script_content.rfind('}') + 1
                            if start != -1 and end != -1:
                                json_str = script_content[start:end]
                                data = json.loads(json_str)
                                
                                # Extract video information (simplified)
                                contents = data.get('contents', {}).get('twoColumnSearchResultsRenderer', {}).get('primaryContents', {}).get('sectionListRenderer', {}).get('contents', [])
                                
                                if contents and len(contents) > 0:
                                    items = contents[0].get('itemSectionRenderer', {}).get('contents', [])
                                    
                                    for item in items[:5]:  # Limit to first 5 results
                                        if 'videoRenderer' in item:
                                            video = item['videoRenderer']
                                            
                                            title = ""
                                            if 'title' in video and 'runs' in video['title']:
                                                title = video['title']['runs'][0].get('text', '')
                                            
                                            video_id = video.get('videoId', '')
                                            
                                            channel_name = ""
                                            if 'ownerText' in video and 'runs' in video['ownerText']:
                                                channel_name = video['ownerText']['runs'][0].get('text', '')
                                            
                                            if title and video_id:
                                                result = {
                                                    'title': title,
                                                    'url': f'https://www.youtube.com/watch?v={video_id}',
                                                    'channel_name': channel_name,
                                                    'channel_url': f'https://www.youtube.com/@{channel_name}',
                                                    'date': datetime.datetime.now().strftime('%Y-%m-%d'),
                                                    'view_count': 'N/A'
                                                }
                                                results.append(result)
                                                
                                                # Save to database
                                                item_db = Item()
                                                item_db.title_name = title
                                                item_db.video_id = f'https://www.youtube.com/watch?v={video_id}'
                                                item_db.channel_name = channel_name
                                                item_db.date_time = datetime.datetime.now().strftime('%Y-%m-%d')
                                                item_db.view_counter = 'N/A'
                                                db_session.add(item_db)
                                break
                        except (json.JSONDecodeError, KeyError) as e:
                            logging.error(f"Error parsing YouTube data: {e}")
                            continue
                            
        except Exception as e:
            logging.error(f"Error fetching from YouTube: {e}")
        
        # If no real results, use demo results
        if not results:
            logging.info("Using demo results due to YouTube access issues")
            results = create_demo_results(keywords)
            
            # Save demo results to database
            for result in results:
                item_db = Item()
                item_db.title_name = result['title']
                item_db.video_id = result['url']
                item_db.channel_name = result['channel_name']
                item_db.channel_id = result['channel_url']
                item_db.date_time = result['date']
                item_db.view_counter = result['view_count']
                db_session.add(item_db)
        
        db_session.commit()
        db_session.close()
        
        return jsonify({
            'results': results,
            'total': len(results),
            'session_id': session['session_id'],
            'demo_mode': len([r for r in results if 'Demo' in r.get('channel_name', '')]) > 0
        })
        
    except Exception as e:
        logging.error(f"Error in search route: {e}")
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
        
        return jsonify({'error': 'File not found'}), 404
    except Exception as e:
        logging.error(f"Error in download route: {e}")
        return jsonify({'error': f'Download error: {str(e)}'}), 500

@app.route('/clear_session', methods=['POST'])
def clear_session():
    try:
        if 'session_id' in session:
            temp_dir = f"removefolder/{session['session_id']}"
            if os.path.exists(temp_dir):
                shutil.rmtree(temp_dir)
            session.clear()
        return jsonify({'status': 'cleared'})
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
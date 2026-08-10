import time
import os
#import hashlib
#import tempfile
import time
import base64
import subprocess
import threading
import sys
import re
from IPython.display import HTML, display
import logging
import requests # Import the requests library


# ログの設定
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)


def setup_bore_tunnel():
    """Rust製のboreトンネルの設定"""
    print(" Bore トンネルをセットアップしています...")

    os.system('wget -nc https://github.com/ekzhang/bore/releases/download/v0.6.0/bore-v0.6.0-x86_64-unknown-linux-musl.tar.gz')
    os.system('tar -zxvf bore-v0.6.0-x86_64-unknown-linux-musl.tar.gz')
    os.system('chmod 764 bore')

    print(" flask アプリケーションを起動しています...")
    flask_process = subprocess.Popen(
        ["python3", "-m", "gunicorn", "--timeout", "10000", "--bind", "0.0.0.0:5000", "app:app", "--access-logfile", "-", "--error-logfile", "-"],
    )

    time.sleep(10)

    print(" bore トンネルを開始しています...")
    bore_process = subprocess.Popen(['./bore', 'local', '5000', '--to', 'bore.pub'],
                                   stdout=subprocess.PIPE,
                                   stderr=subprocess.PIPE,
                                   text=True,
                                   bufsize=1
                                   )

    print(" トンネルURLを待機しています...")
    url_found = False
    url = ""
    start_time = time.time()
    timeout = 130

    while time.time() - start_time < timeout:
        line = bore_process.stdout.readline()
        if line:
            match = re.search(r'(bore\.pub:\d+)', line)
            if match:
                extracted_url_part = match.group(0).strip()
                url = f"{extracted_url_part}"
                url_found = True
                break

        if bore_process.poll() is not None:
            print("Boreプロセスが予期せず終了しました。")
            break

        time.sleep(0.1)

    if url_found:
        print(f"✅ トンネルが開始されました: {url}")
        display(HTML(f'<a href="http://{url}" target="_blank" style="font-size:18px; color:pink;">{url}</a>'))
        print("\n--- Boreトンネルへの内部curlテスト ---")
        try:
            curl_url = f"http://{url}"
            curl_result = subprocess.run(['curl', '-s', '-I', curl_url], capture_output=True, text=True, timeout=10)
            print("curl出力（ヘッダのみ）：")
            print(curl_result.stdout.strip())
            if "200 OK" in curl_result.stdout:
                print("✅ curlテスト成功: HTTP 200 OK を受信しました。ブラウザでアクセスできるはずです。")
            else:
                print("❌ curlテスト失敗: 予期しない応答コードを受信しました。")
        except subprocess.TimeoutExpired:
            print("❌ curlテスト失敗: タイムアウトしました。Boreサービスが応答していません。")
        except Exception as e:
            print(f"❌ curlテスト中にエラーが発生しました: {e}")
        print("----------------------------")

    else:
        print("⚠️ トンネルURLの取得に失敗しました。")

    return flask_process, bore_process

def setup_cloudflare_tunnel():
    """Cloudflare Tunnelの設定"""
    print("☁️ Cloudflare Tunnel をセットアップしています...")

    # cloudflaredのダウンロードとインストール（エラーを隠さず表示する）
    os.system('sudo wget -nc https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64.deb')
    os.system('sudo dpkg -i cloudflared-linux-amd64.deb || sudo apt-get install -f -y')

    # cloudflaredが実際にインストールされたか確認
    check = subprocess.run(['which', 'cloudflared'], capture_output=True, text=True)
    if not check.stdout.strip():
        print("❌ cloudflaredのインストールに失敗しました。上記のdpkg/aptログを確認してください。")
    else:
        print(f"✅ cloudflaredインストール確認: {check.stdout.strip()}")
        version = subprocess.run(['cloudflared', '--version'], capture_output=True, text=True)
        print(f"   バージョン: {version.stdout.strip()}")

    print(" flask アプリケーションを起動しています...")
    flask_process = subprocess.Popen(
        ["python3", "-m", "gunicorn","--timeout", "10000", "--bind", "0.0.0.0:5000", "app:app", "--access-logfile", "-", "--error-logfile", "-"],
    )

    time.sleep(10)  # サーバーの起動を待つ

    # Cloudflareトンネルの起動
    print("☁️ Cloudflare トンネルを開始しています...")
    tunnel_process = subprocess.Popen(
        ['cloudflared', 'tunnel', '--url', 'http://localhost:5000',
         '--protocol', 'http2', '--loglevel', 'info'],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1)

    # cloudflaredの出力からURLを抽出するループ
    url_found = False
    url = ""
    start_time = time.time()
    timeout = 130

    while time.time() - start_time < timeout:
        line = tunnel_process.stderr.readline() # Cloudflare TunnelはstderrにURLを出す傾向がある
        if line:
            print(f"[CF] {line.strip()}")  # 全行表示してエラー内容を可視化
            if 'https://' in line and 'trycloudflare.com' in line:
                match = re.search(r'(https:\/\/[^\s]+\.trycloudflare\.com)', line)
                if match:
                    url = match.group(0).strip()
                    url_found = True
                    break

        if tunnel_process.poll() is not None:
            print("Cloudflare Tunnelプロセスが予期せず終了しました。")
            break

        time.sleep(0.1)

    if url_found:
        print(f"✅ Cloudflare トンネルが開始されました: {url}")

        # URL検出後もstderrを読み続けないとパイプが詰まる可能性があるため、
        # バックグラウンドスレッドで継続的にドレインする
        def _drain_stderr(proc):
            try:
                for line in iter(proc.stderr.readline, ''):
                    if not line:
                        break
            except Exception:
                pass
        drain_thread = threading.Thread(target=_drain_stderr, args=(tunnel_process,), daemon=True)
        drain_thread.start()

        # トンネルがエッジに伝播するまで少し待ってから疎通確認（リトライ付き）
        print("\n--- トンネル疎通確認（伝播待ち）---")
        reachable = False
        for attempt in range(1, 13):  # 最大 約60秒 リトライ
            try:
                check_resp = requests.get(url, timeout=5)
                if check_resp.status_code < 500:
                    print(f"✅ 疎通確認成功 (試行{attempt}回目): HTTP {check_resp.status_code}")
                    reachable = True
                    break
                else:
                    print(f"⏳ 試行{attempt}回目: HTTP {check_resp.status_code}、再試行します...")
            except Exception as e:
                print(f"⏳ 試行{attempt}回目: 未到達 ({type(e).__name__})、再試行します...")
            time.sleep(5)

        if not reachable:
            print("⚠️ 60秒経っても疎通確認できませんでした。URLは有効な可能性がありますが、")
            print("   もう少し待ってからブラウザで再アクセスしてみてください（1033が出る場合は再試行）。")

        display(HTML(f'<a href="{url}" target="_blank" style="font-size:18px; color:pink;">ファイルアップロードサービスにアクセス: {url}</a>'))
    else:
        print("⚠️ CloudflareトンネルURLの取得に失敗しました。残りのログ:")
        try:
            remaining_err = tunnel_process.stderr.read()
            if remaining_err:
                print(f"[CF stderr]\n{remaining_err.strip()}")
        except Exception as e:
            print(f"stderr読み取りエラー: {e}")
        try:
            remaining_out = tunnel_process.stdout.read()
            if remaining_out:
                print(f"[CF stdout]\n{remaining_out.strip()}")
        except Exception as e:
            print(f"stdout読み取りエラー: {e}")

    return flask_process, tunnel_process

def wait_for_flask_server(port=5000, timeout=15):
    """flaskサーバーが起動し、リクエストに応答するのを待機します。"""
    url = f"http://localhost:{port}"
    print(f"Waiting for Go server to start at {url}...")
    start_time = time.time()
    while time.time() - start_time < timeout:
        try:
            response = requests.get(url, timeout=1)
            if response.status_code == 200:
                print(f"✅ flask server is up and running! Status code: {response.status_code}")
                return True
        except requests.exceptions.ConnectionError:
            pass
        except Exception as e:
            print(f"Error during flask server health check: {e}")
            pass
        time.sleep(1)
    print(f"❌ flask server did not respond within {timeout} seconds.")
    return False


def get_colab_external_ip():
    """Colabの外部IPアドレスを取得します。"""
    try:
        result = subprocess.run(['curl', 'ipinfo.io/ip'], capture_output=True, text=True, check=True)
        return result.stdout.strip()
    except Exception as e:
        print(f"⚠️ 外部IPアドレスの取得に失敗しました: {e}")
        return "UNKNOWN_IP"

selected_tunnel_service = ""
while True:
    print("\n--- トンネル方法を選択してください ---")
    print("1. Bore")
    print("2. Cloudflared")
    choice = input("選択 (1/2): ").strip()

    if choice == '1':
        selected_tunnel_service = "bore"
        break
    elif choice == '2':
        selected_tunnel_service = "cloudflared"
        break
    else:
        print("無効な選択です。1 または 2 を入力してください。")


if selected_tunnel_service == "bore":
    flask_process, bore_process = setup_bore_tunnel()
elif selected_tunnel_service == "cloudflared":
    flask_process, cloudflared_process = setup_cloudflare_tunnel()

print(f"\nColab 外部IPアドレス: {get_colab_external_ip()}")

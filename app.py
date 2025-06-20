import os
import requests
import json
import hmac
import hashlib
import base64
import time
from flask import Flask, request, abort
from dotenv import load_dotenv
import jwt

# .envファイルから環境変数を読み込む
load_dotenv()

app = Flask(__name__)

# --- 環境変数から設定を読み込み ---
# Backlog API設定
BACKLOG_SPACE_ID = os.getenv('BACKLOG_SPACE_ID')
BACKLOG_API_KEY = os.getenv('BACKLOG_API_KEY')
BACKLOG_PROJECT_ID = os.getenv('BACKLOG_PROJECT_ID')
BACKLOG_ISSUE_TYPE_ID = os.getenv('BACKLOG_ISSUE_TYPE_ID')
BACKLOG_PRIORITY_ID = os.getenv('BACKLOG_PRIORITY_ID')

# LINE WORKS API 2.0設定
LINEWORKS_BOT_SECRET = os.getenv('LINEWORKS_BOT_SECRET')
LINEWORKS_CLIENT_ID = os.getenv('LINEWORKS_CLIENT_ID')
LINEWORKS_CLIENT_SECRET = os.getenv('LINEWORKS_CLIENT_SECRET')
LINEWORKS_SERVICE_ACCOUNT = os.getenv('LINEWORKS_SERVICE_ACCOUNT')
# .envファイルから改行を含むPRIVATE KEYを正しく読み込む
LINEWORKS_PRIVATE_KEY = os.getenv('LINEWORKS_PRIVATE_KEY', '').replace('\\n', '\n')


# --- グローバル変数 ---
# アクセストークンと有効期限をキャッシュするための変数
access_token_cache = {
    "token": None,
    "expires_at": 0
}


def get_lineworks_access_token() -> str:
    """
    JWTを生成し、LINE WORKSからアクセストークンを取得する関数。
    取得したトークンは有効期限までキャッシュする。
    """
    global access_token_cache
    current_time = int(time.time())

    # キャッシュが有効であればそれを返す
    if access_token_cache["token"] and access_token_cache["expires_at"] > current_time:
        print("Using cached access token.")
        return access_token_cache["token"]

    print("Generating new access token.")
    # JWT (JSON Web Token) の生成
    jwt_payload = {
        "iss": LINEWORKS_CLIENT_ID,
        "sub": LINEWORKS_SERVICE_ACCOUNT,
        "iat": current_time,
        "exp": current_time + 3600,  # 有効期間は1時間
    }
    
    try:
        # RS256アルゴリズムで署名
        assertion = jwt.encode(
            jwt_payload,
            LINEWORKS_PRIVATE_KEY,
            algorithm="RS256"
        )
    except Exception as e:
        print(f"Error encoding JWT: {e}")
        return None

    # アクセストークンのリクエスト
    token_url = "https://auth.worksmobile.com/b/common/api/v1/oauth/token"
    headers = {"Content-Type": "application/x-www-form-urlencoded"}
    token_payload = {
        "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
        "assertion": assertion,
        "client_id": LINEWORKS_CLIENT_ID,
        "client_secret": LINEWORKS_CLIENT_SECRET,
        "scope": "bot directory.read" # 必要なスコープを記述
    }

    try:
        response = requests.post(token_url, headers=headers, data=token_payload)
        response.raise_for_status()
        token_data = response.json()

        # トークンと有効期限をキャッシュに保存
        access_token_cache["token"] = token_data['access_token']
        # 有効期限の5分前を期限として設定
        access_token_cache["expires_at"] = current_time + token_data['expires_in'] - 300
        
        return access_token_cache["token"]
    except requests.exceptions.RequestException as e:
        print(f"Error getting access token: {e}")
        print(f"Response Body: {response.text}")
        return None


def get_lineworks_user_name(user_id: str) -> str:
    """
    LINE WORKSのユーザーIDから表示名を取得する関数 (API 2.0)
    """
    access_token = get_lineworks_access_token()
    if not access_token:
        return "不明なユーザー (Token Error)"

    url = f"https://www.worksapis.com/v1.0/users/{user_id}"
    headers = {
        "Authorization": f"Bearer {access_token}"
    }
    try:
        response = requests.get(url, headers=headers)
        response.raise_for_status()
        user_data = response.json()
        return user_data.get('userName', {}).get('displayName', '不明なユーザー')
    except requests.exceptions.RequestException as e:
        print(f"Error fetching LINE WORKS user name: {e}")
        print(f"Response Body: {response.text}")
        return "不明なユーザー (API Error)"


def create_backlog_issue(subject: str, description: str) -> bool:
    """
    Backlogに課題を作成する関数
    """
    if not all([BACKLOG_SPACE_ID, BACKLOG_API_KEY, BACKLOG_PROJECT_ID, BACKLOG_ISSUE_TYPE_ID, BACKLOG_PRIORITY_ID]):
        print("Error: Backlog API settings are missing.")
        return False

    url = f"https://{BACKLOG_SPACE_ID}.backlog.jp/api/v2/issues"
    params = {"apiKey": BACKLOG_API_KEY}
    payload = {
        "projectId": BACKLOG_PROJECT_ID,
        "summary": subject,
        "description": description,
        "issueTypeId": BACKLOG_ISSUE_TYPE_ID,
        "priorityId": BACKLOG_PRIORITY_ID,
    }
    try:
        response = requests.post(url, params=params, json=payload)
        response.raise_for_status()
        print(f"Backlog issue created successfully: {response.json().get('issueKey')}")
        return True
    except requests.exceptions.RequestException as e:
        print(f"Error creating Backlog issue: {e}")
        print(f"Response Body: {response.text}")
        return False


@app.route("/callback", methods=['POST'])
def callback():
    """
    LINE WORKSからのコールバックを受け取るエンドポイント
    """
    signature = request.headers.get('X-Works-Signature')
    if not signature:
        abort(400)

    hashed = hmac.new(
        LINEWORKS_BOT_SECRET.encode('utf-8'),
        request.data,
        hashlib.sha256
    ).digest()
    expected_signature = base64.b64encode(hashed).decode('utf-8')

    if not hmac.compare_digest(signature, expected_signature):
        abort(401)

    data = request.get_json()
    print(f"Received event: {json.dumps(data, indent=2)}")

    if data.get('type') == 'url_verification':
        return data.get('challenge')

    if data.get('type') == 'message':
        content = data.get('content', {})
        if content.get('type') == 'text':
            user_id = data['source']['userId']
            message_text = content.get('text')

            user_name = get_lineworks_user_name(user_id)
            subject = f"【LINE WORKS】{user_name}さんからのメッセージ"
            create_backlog_issue(subject, message_text)

    return "OK", 200


if __name__ == "__main__":
    app.run(port=5000, debug=True)


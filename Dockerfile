# ベースとなるPythonのイメージを指定
FROM python:3.9-slim

# 作業ディレクトリを設定
WORKDIR /app

# 必要なライブラリをインストール
# requirements.txtを先にコピーすることで、コード変更時にもライブラリの再インストールをスキップできる
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# アプリケーションのソースコードをコピー
COPY . .

# アプリケーションを起動するコマンド
# Cloud Runは環境変数PORTでリッスンすべきポートを渡してくる
# gunicornがそのポートを使ってFlaskアプリを起動する
CMD exec gunicorn --bind :$PORT --workers 1 --threads 8 --timeout 0 app:app
"""Vercel とローカルの入口。`python app.py` でローカル起動。"""
from futari import create_app

app = create_app()

if __name__ == "__main__":
    app.run(debug=True, port=5000)

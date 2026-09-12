import os
from flask import Flask, request

app = Flask(__name__)

@app.route("/")
def home():
    return "GPT Threads bot is running."

@app.route("/auth/threads/callback")
def threads_callback():
    code = request.args.get("code")
    if code:
        return "Threads authorization received. You can close this page."
    return "Threads callback is working."

@app.route("/threads/deauthorize", methods=["GET", "POST"])
def threads_deauthorize():
    return "OK", 200

@app.route("/threads/delete", methods=["GET", "POST"])
def threads_delete():
    return "OK", 200

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)

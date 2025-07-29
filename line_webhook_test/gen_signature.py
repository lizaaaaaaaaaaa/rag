import sys
import hmac
import hashlib
import base64

if len(sys.argv) != 3:
    print("使い方: python gen_signature.py <チャネルシークレット> <bodyファイル>")
    sys.exit(1)

channel_secret = sys.argv[1]
with open(sys.argv[2], "rb") as f:
    body = f.read()

hash = hmac.new(channel_secret.encode("utf-8"), body, hashlib.sha256).digest()
signature = base64.b64encode(hash).decode("utf-8")
print(signature)

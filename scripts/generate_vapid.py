"""プッシュ通知用の鍵（VAPID）を作る。出力を Vercel の環境変数に登録する。

使い方: python scripts/generate_vapid.py
"""
import base64

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec


def b64url(data):
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def main():
    key = ec.generate_private_key(ec.SECP256R1())
    private = key.private_numbers().private_value.to_bytes(32, "big")
    public = key.public_key().public_bytes(
        serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint
    )
    print("VAPID_PUBLIC_KEY=" + b64url(public))
    print("VAPID_PRIVATE_KEY=" + b64url(private))


if __name__ == "__main__":
    main()

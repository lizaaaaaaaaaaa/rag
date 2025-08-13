#!/usr/bin/env python3
"""
プロキシ環境対応 LINE API テストスクリプト
"""

import requests
import os

# プロキシ設定（企業環境に応じて変更）
PROXIES = {
    'http': 'http://proxy.company.com:8080',
    'https': 'https://proxy.company.com:8080'
}

# LINE Bot Token
LINE_TOKEN = "YOUR_LINE_TOKEN_HERE"

def test_with_proxy():
    headers = {"Authorization": f"Bearer {LINE_TOKEN}"}
    
    try:
        response = requests.get(
            "https://api.line.me/v2/bot/info",
            headers=headers,
            proxies=PROXIES,
            timeout=15
        )
        
        print(f"Status: {response.status_code}")
        print(f"Response: {response.text}")
        
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    test_with_proxy()

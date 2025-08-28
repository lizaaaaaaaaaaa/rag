# api/routers/line_utils.py
from urllib.parse import urlencode, urlparse, urlunparse, parse_qsl

__all__ = ["with_utm"]


def with_utm(url: str, campaign: str, *, medium: str = "richmenu", ab: str = "A") -> str:
    """
    LINE リッチメニュー/返信URLに UTM + AB を統一付与する軽量ユーティリティ。
    既存のクエリは保持しつつ、以下キーを上書きします。
      - utm_source=line
      - utm_medium=<medium>
      - utm_campaign=<campaign>
      - ab=<ab>

    Params:
      url: 付与対象URL（LIFF/サイトURLなど）
      campaign: ボタン名やキャンペーン名（例: "ai_consult"）
      medium: 既定 "richmenu"（返信テキスト等なら "message" などに変更可）
      ab: "A" | "B" などのバリアント記号

    Returns:
      UTM/AB が統一付与された URL
    """
    if not isinstance(url, str) or url == "":
        return url  # 型ガード（極小コスト）

    u = urlparse(url)
    # 既存クエリを取得（空文字も保持）
    q = dict(parse_qsl(u.query, keep_blank_values=True))

    # 統一上書き
    q["utm_source"] = "line"
    q["utm_medium"] = medium
    q["utm_campaign"] = campaign
    q["ab"] = ab

    new_query = urlencode(q, doseq=True)
    return urlunparse((u.scheme, u.netloc, u.path, u.params, new_query, u.fragment))

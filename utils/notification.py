# ====================
# utils/notification.py
# ====================
"""
通知システムユーティリティ
メール・LINE通知の統合管理

機能:
- SMTP メール送信
- LINE メッセージ送信
- 通知テンプレート管理
- 配信履歴管理
- エラーハンドリング

Requirements:
- aiosmtplib
- line-bot-sdk
- jinja2
"""

import asyncio
import logging
import smtplib
import ssl
from datetime import datetime, timedelta  # ← timedelta を追加
from typing import List, Optional, Dict, Any, Union
from email.mime.text import MimeText
from email.mime.multipart import MimeMultipart
from email.mime.base import MimeBase
from email import encoders
import aiosmtplib
from linebot.v3 import WebhookHandler
from linebot.v3.messaging import (
    Configuration, ApiClient, MessagingApi,
    PushMessageRequest, TextMessage
)
from linebot.v3.exceptions import InvalidSignatureError
import jinja2

from config import settings

# ロギング設定
logger = logging.getLogger(__name__)

# ==================================================
# 設定クラス
# ==================================================

class SMTPConfig:
    """SMTP設定"""
    def __init__(
        self,
        host: str = "localhost",
        port: int = 587,
        username: str = "",
        password: str = "",
        use_tls: bool = True,
        use_ssl: bool = False,
        timeout: int = 60
    ):
        self.host = host
        self.port = port
        self.username = username
        self.password = password
        self.use_tls = use_tls
        self.use_ssl = use_ssl
        self.timeout = timeout

class LINEConfig:
    """LINE設定"""
    def __init__(
        self,
        channel_access_token: str = "",
        channel_secret: str = ""
    ):
        self.channel_access_token = channel_access_token
        self.channel_secret = channel_secret

# ==================================================
# 通知テンプレート管理
# ==================================================

class NotificationTemplate:
    """通知テンプレート"""

    # デフォルトテンプレート
    DEFAULT_TEMPLATES = {
        "consent_expiry_warning": {
            "email": {
                "subject": "【重要】同意期限のお知らせ（{{days}}日前）",
                "body": """
お客様の同意期限が {{expiry_date}} に迫っています。

継続してサービスをご利用いただくには、期限前に再同意手続きを行ってください。

同意更新URL: {{renewal_url}}

ご不明な点がございましたら、サポートまでお問い合わせください。
                """.strip()
            },
            "line": {
                "message": """
🔔 同意期限のお知らせ

期限: {{expiry_date}}
あと{{days}}日で期限切れとなります。

継続利用には再同意が必要です。
▼ 同意更新
{{renewal_url}}
                """.strip()
            }
        },
        "system_alert": {
            "email": {
                "subject": "[{{severity}}] システムアラート: {{alert_type}}",
                "body": """
システムアラートが発生しました。

アラートタイプ: {{alert_type}}
重要度: {{severity}}
発生時刻: {{timestamp}}

詳細:
{{message}}

{{details}}

確認をお願いいたします。
                """.strip()
            }
        },
        "compliance_report": {
            "email": {
                "subject": "コンプライアンス報告 - {{period}}",
                "body": """
コンプライアンス報告を送付いたします。

報告期間: {{period}}
生成日時: {{generated_at}}

サマリー:
- 総同意数: {{total_consents}}
- 有効同意: {{active_consents}}
- 取り消し: {{withdrawn_consents}}
- GDPR準拠: {{gdpr_compliant}}

詳細は添付ファイルをご確認ください。
                """.strip()
            }
        }
    }

    def __init__(self):
        self.env = jinja2.Environment(
            loader=jinja2.DictLoader({}),
            autoescape=jinja2.select_autoescape(['html', 'xml'])
        )

    def render(
        self,
        template_name: str,
        template_type: str,
        variables: Dict[str, Any]
    ) -> str:
        """テンプレートレンダリング"""
        try:
            if template_name in self.DEFAULT_TEMPLATES:
                template_data = self.DEFAULT_TEMPLATES[template_name].get(template_type, {})

                if template_type == "email":
                    content = template_data.get("body", "")
                elif template_type == "line":
                    content = template_data.get("message", "")
                else:
                    content = str(template_data)

                template = self.env.from_string(content)
                return template.render(**variables)
            else:
                logger.warning(f"Template not found: {template_name}")
                return f"Template {template_name} not found"

        except Exception as e:
            logger.error(f"Template rendering failed: {e}")
            return f"Template rendering error: {str(e)}"

    def render_subject(self, template_name: str, variables: Dict[str, Any]) -> str:
        """メール件名レンダリング"""
        try:
            if template_name in self.DEFAULT_TEMPLATES:
                email_template = self.DEFAULT_TEMPLATES[template_name].get("email", {})
                subject_template = email_template.get("subject", "通知")

                template = self.env.from_string(subject_template)
                return template.render(**variables)
            else:
                return "通知"

        except Exception as e:
            logger.error(f"Subject rendering failed: {e}")
            return "通知"

# ==================================================
# メール送信
# ==================================================

async def send_email_notification(
    subject: str,
    body: str,
    recipients: List[str],
    smtp_config: Optional[Union[SMTPConfig, Dict[str, Any]]] = None,
    sender: Optional[str] = None,
    html_body: Optional[str] = None,
    attachments: Optional[List[Dict[str, Any]]] = None
) -> bool:
    """非同期メール送信"""
    try:
        # SMTP設定準備
        if smtp_config is None:
            smtp_config = SMTPConfig(
                host=settings.notification_config.get('smtp', {}).get('host', 'localhost'),
                port=settings.notification_config.get('smtp', {}).get('port', 587),
                username=settings.notification_config.get('smtp', {}).get('username', ''),
                password=settings.notification_config.get('smtp', {}).get('password', ''),
                use_tls=settings.notification_config.get('smtp', {}).get('use_tls', True)
            )
        elif isinstance(smtp_config, dict):
            smtp_config = SMTPConfig(**smtp_config)

        if sender is None:
            sender = smtp_config.username or "noreply@example.com"

        # メッセージ作成
        message = MimeMultipart("alternative")
        message["Subject"] = subject
        message["From"] = sender
        message["To"] = ", ".join(recipients)
        message["Date"] = datetime.utcnow().strftime("%a, %d %b %Y %H:%M:%S +0000")

        # テキスト部分
        text_part = MimeText(body, "plain", "utf-8")
        message.attach(text_part)

        # HTML部分（オプション）
        if html_body:
            html_part = MimeText(html_body, "html", "utf-8")
            message.attach(html_part)

        # 添付ファイル（オプション）
        if attachments:
            for attachment in attachments:
                part = MimeBase("application", "octet-stream")
                part.set_payload(attachment.get("content", b""))
                encoders.encode_base64(part)
                part.add_header(
                    "Content-Disposition",
                    f"attachment; filename= {attachment.get('filename', 'attachment')}"
                )
                message.attach(part)

        # SMTP送信
        async with aiosmtplib.SMTP(
            hostname=smtp_config.host,
            port=smtp_config.port,
            timeout=smtp_config.timeout
        ) as smtp:

            if smtp_config.use_tls:
                await smtp.starttls()

            if smtp_config.username and smtp_config.password:
                await smtp.login(smtp_config.username, smtp_config.password)

            await smtp.send_message(message)

        logger.info(f"Email sent successfully to {len(recipients)} recipients")
        return True

    except Exception as e:
        logger.error(f"Failed to send email: {e}")
        return False

def send_email_notification_sync(
    subject: str,
    body: str,
    recipients: List[str],
    smtp_config: Optional[Union[SMTPConfig, Dict[str, Any]]] = None,
    sender: Optional[str] = None
) -> bool:
    """同期メール送信（レガシー）"""
    try:
        # SMTP設定準備
        if smtp_config is None:
            smtp_config = SMTPConfig(
                host=settings.notification_config.get('smtp', {}).get('host', 'localhost'),
                port=settings.notification_config.get('smtp', {}).get('port', 587),
                username=settings.notification_config.get('smtp', {}).get('username', ''),
                password=settings.notification_config.get('smtp', {}).get('password', ''),
                use_tls=settings.notification_config.get('smtp', {}).get('use_tls', True)
            )
        elif isinstance(smtp_config, dict):
            smtp_config = SMTPConfig(**smtp_config)

        if sender is None:
            sender = smtp_config.username or "noreply@example.com"

        # メッセージ作成
        message = MimeMultipart()
        message["Subject"] = subject
        message["From"] = sender
        message["To"] = ", ".join(recipients)

        message.attach(MimeText(body, "plain", "utf-8"))

        # SMTP送信
        context = ssl.create_default_context()
        with smtplib.SMTP(smtp_config.host, smtp_config.port) as server:
            if smtp_config.use_tls:
                server.starttls(context=context)

            if smtp_config.username and smtp_config.password:
                server.login(smtp_config.username, smtp_config.password)

            server.sendmail(sender, recipients, message.as_string())

        logger.info(f"Email sent successfully to {len(recipients)} recipients")
        return True

    except Exception as e:
        logger.error(f"Failed to send email (sync): {e}")
        return False

# ==================================================
# LINE 送信
# ==================================================

async def send_line_notification(
    user_id: str,
    message: str,
    config: Optional[Union[LINEConfig, Dict[str, Any]]] = None
) -> bool:
    """LINE メッセージ送信"""
    try:
        # LINE設定準備
        if config is None:
            config = LINEConfig(
                channel_access_token=settings.notification_config.get('line', {}).get('channel_access_token', ''),
                channel_secret=settings.notification_config.get('line', {}).get('channel_secret', '')
            )
        elif isinstance(config, dict):
            config = LINEConfig(**config)

        if not config.channel_access_token:
            logger.warning("LINE channel access token not configured")
            return False

        # LINE Bot API設定
        configuration = Configuration(access_token=config.channel_access_token)

        async with ApiClient(configuration) as api_client:
            line_bot_api = MessagingApi(api_client)

            # メッセージ送信
            push_message_request = PushMessageRequest(
                to=user_id,
                messages=[TextMessage(text=message)]
            )

            await line_bot_api.push_message(push_message_request)

        logger.info(f"LINE message sent successfully to user: {user_id[:8]}...")
        return True

    except Exception as e:
        logger.error(f"Failed to send LINE message: {e}")
        return False

async def send_line_broadcast(
    message: str,
    config: Optional[Union[LINEConfig, Dict[str, Any]]] = None
) -> bool:
    """LINE ブロードキャスト送信"""
    try:
        # LINE設定準備
        if config is None:
            config = LINEConfig(
                channel_access_token=settings.notification_config.get('line', {}).get('channel_access_token', ''),
                channel_secret=settings.notification_config.get('line', {}).get('channel_secret', '')
            )
        elif isinstance(config, dict):
            config = LINEConfig(**config)

        if not config.channel_access_token:
            logger.warning("LINE channel access token not configured")
            return False

        # LINE Bot API設定
        configuration = Configuration(access_token=config.channel_access_token)

        async with ApiClient(configuration) as api_client:
            line_bot_api = MessagingApi(api_client)

            # ブロードキャスト送信
            from linebot.v3.messaging import BroadcastRequest
            broadcast_request = BroadcastRequest(
                messages=[TextMessage(text=message)]
            )

            await line_bot_api.broadcast(broadcast_request)

        logger.info("LINE broadcast sent successfully")
        return True

    except Exception as e:
        logger.error(f"Failed to send LINE broadcast: {e}")
        return False

# ==================================================
# 統合通知システム
# ==================================================

class NotificationManager:
    """統合通知マネージャー"""

    def __init__(self):
        self.template_manager = NotificationTemplate()

    async def send_templated_notification(
        self,
        template_name: str,
        variables: Dict[str, Any],
        recipients: Dict[str, List[str]],  # {"email": [...], "line": [...]}
        smtp_config: Optional[Union[SMTPConfig, Dict[str, Any]]] = None,
        line_config: Optional[Union[LINEConfig, Dict[str, Any]]] = None
    ) -> Dict[str, bool]:
        """テンプレート使用通知送信"""
        results = {"email": False, "line": False}

        try:
            # メール送信
            if recipients.get("email"):
                subject = self.template_manager.render_subject(template_name, variables)
                body = self.template_manager.render(template_name, "email", variables)

                results["email"] = await send_email_notification(
                    subject=subject,
                    body=body,
                    recipients=recipients["email"],
                    smtp_config=smtp_config
                )

            # LINE送信
            if recipients.get("line"):
                message = self.template_manager.render(template_name, "line", variables)

                line_results = []
                for user_id in recipients["line"]:
                    result = await send_line_notification(
                        user_id=user_id,
                        message=message,
                        config=line_config
                    )
                    line_results.append(result)

                results["line"] = all(line_results) if line_results else False

            return results

        except Exception as e:
            logger.error(f"Failed to send templated notification: {e}")
            return {"email": False, "line": False}

    async def send_consent_expiry_notification(
        self,
        user_email: Optional[str],
        line_user_id: Optional[str],
        consent_id: str,
        expiry_date: datetime,
        days_until_expiry: int,
        renewal_url: str
    ) -> Dict[str, bool]:
        """同意期限通知送信"""
        variables = {
            "consent_id": consent_id,
            "expiry_date": expiry_date.strftime("%Y年%m月%d日"),
            "days": days_until_expiry,
            "renewal_url": renewal_url
        }

        recipients = {}
        if user_email:
            recipients["email"] = [user_email]
        if line_user_id:
            recipients["line"] = [line_user_id]

        return await self.send_templated_notification(
            template_name="consent_expiry_warning",
            variables=variables,
            recipients=recipients
        )

    async def send_system_alert(
        self,
        alert_type: str,
        severity: str,
        message: str,
        details: Dict[str, Any],
        recipients: List[str]
    ) -> bool:
        """システムアラート送信"""
        variables = {
            "alert_type": alert_type,
            "severity": severity,
            "message": message,
            "timestamp": datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC"),
            "details": "\n".join([f"{k}: {v}" for k, v in details.items()])
        }

        result = await self.send_templated_notification(
            template_name="system_alert",
            variables=variables,
            recipients={"email": recipients}
        )

        return result.get("email", False)

# ==================================================
# グローバルインスタンス
# ==================================================

notification_manager = NotificationManager()

# ==================================================
# 便利関数
# ==================================================

async def send_notification(
    message: str,
    recipients: Dict[str, List[str]],
    subject: Optional[str] = None
) -> Dict[str, bool]:
    """簡易通知送信"""
    results = {"email": False, "line": False}

    try:
        # メール送信
        if recipients.get("email") and subject:
            results["email"] = await send_email_notification(
                subject=subject,
                body=message,
                recipients=recipients["email"]
            )

        # LINE送信
        if recipients.get("line"):
            line_results = []
            for user_id in recipients["line"]:
                result = await send_line_notification(
                    user_id=user_id,
                    message=message
                )
                line_results.append(result)

            results["line"] = all(line_results) if line_results else False

        return results

    except Exception as e:
        logger.error(f"Failed to send notification: {e}")
        return {"email": False, "line": False}

# ==================================================
# テスト関数
# ==================================================

async def test_notifications():
    """通知システムテスト"""
    try:
        # メールテスト
        email_result = await send_email_notification(
            subject="テストメール",
            body="これはテストメールです。",
            recipients=["test@example.com"]
        )

        print(f"Email test result: {email_result}")

        # LINEテスト（実際のuser_idが必要）
        # line_result = await send_line_notification(
        #     user_id="test_user_id",
        #     message="これはテストメッセージです。"
        # )
        # print(f"LINE test result: {line_result}")

        # テンプレートテスト
        template_result = await notification_manager.send_consent_expiry_notification(
            user_email="test@example.com",
            line_user_id=None,
            consent_id="test_consent_123",
            expiry_date=datetime.utcnow() + timedelta(days=30),
            days_until_expiry=30,
            renewal_url="https://example.com/consent/renew"
        )

        print(f"Template test result: {template_result}")

    except Exception as e:
        print(f"Notification test failed: {e}")

if __name__ == "__main__":
    # テスト実行
    asyncio.run(test_notifications())

/**
 * Web同意バナー（CMP: Consent Management Platform）
 * 
 * 機能:
 * - Cookie同意バナー表示
 * - 外部送信通知
 * - プライバシーポリシー同意
 * - 同意設定管理
 * - 法的要件対応（電気通信事業法、GDPR等）
 * 
 * 使用方法:
 * <script src="/static/js/consent_banner.js"></script>
 * <script>
 *   ConsentManager.init({
 *     apiEndpoint: '/api/consent',
 *     privacyPolicyUrl: '/privacy',
 *     cookiePolicyUrl: '/cookie',
 *     termsUrl: '/terms'
 *   });
 * </script>
 */

(function(window, document) {
    'use strict';

    // ==================================================
    // グローバル設定
    // ==================================================
    
    const CONSENT_MANAGER_VERSION = '1.3.0';
    const STORAGE_KEY = 'consent_preferences';
    const BANNER_ID = 'consent-banner';
    const MODAL_ID = 'consent-modal';
    
    // デフォルト設定
    const DEFAULT_CONFIG = {
        apiEndpoint: '/api/consent',
        privacyPolicyUrl: '/privacy',
        cookiePolicyUrl: '/cookie',
        termsUrl: '/terms',
        policyVersion: 'pp_v1.3',
        tosVersion: 'tos_v1.4',
        expiryDays: 365,
        position: 'bottom', // 'top', 'bottom'
        theme: 'light', // 'light', 'dark'
        language: 'ja',
        autoShow: true,
        debugMode: false
    };

    // 同意カテゴリ定義
    const CONSENT_CATEGORIES = {
        necessary: {
            name: '必須Cookie',
            description: 'サイトの基本機能に必要なCookie',
            required: true,
            enabled: true
        },
        analytics: {
            name: 'アナリティクス',
            description: 'サイト利用状況の分析のためのCookie',
            required: false,
            enabled: false
        },
        marketing: {
            name: 'マーケティング',
            description: '広告配信・パーソナライゼーションのためのCookie',
            required: false,
            enabled: false
        },
        external: {
            name: '外部送信',
            description: 'AI処理等のための外部サービスへのデータ送信',
            required: false,
            enabled: false
        }
    };

    // ==================================================
    // メインクラス: ConsentManager
    // ==================================================
    
    class ConsentManager {
        constructor() {
            this.config = { ...DEFAULT_CONFIG };
            this.consents = { ...CONSENT_CATEGORIES };
            this.isInitialized = false;
            this.bannerElement = null;
            this.modalElement = null;
            this.callbacks = {
                onConsentGiven: [],
                onConsentWithdrawn: [],
                onPreferencesChanged: []
            };
        }

        /**
         * 初期化
         * @param {Object} options - 設定オプション
         */
        init(options = {}) {
            if (this.isInitialized) {
                this.log('ConsentManager is already initialized');
                return;
            }

            // 設定のマージ
            this.config = { ...this.config, ...options };
            
            // DOM準備完了を待つ
            if (document.readyState === 'loading') {
                document.addEventListener('DOMContentLoaded', () => this._initialize());
            } else {
                this._initialize();
            }
        }

        /**
         * 内部初期化処理
         */
        _initialize() {
            this.log('Initializing ConsentManager v' + CONSENT_MANAGER_VERSION);

            // 既存の同意状況をロード
            this._loadConsents();

            // UIの構築
            this._createStyles();
            this._createBanner();
            this._createModal();

            // イベントリスナーの設定
            this._setupEventListeners();

            // 同意状況をチェック
            this._checkConsentStatus();

            this.isInitialized = true;
            this.log('ConsentManager initialized successfully');
        }

        /**
         * 既存の同意をロード
         */
        _loadConsents() {
            try {
                const stored = localStorage.getItem(STORAGE_KEY);
                if (stored) {
                    const data = JSON.parse(stored);
                    
                    // 有効期限チェック
                    if (data.expires && new Date(data.expires) > new Date()) {
                        // 既存の同意を復元
                        Object.keys(this.consents).forEach(key => {
                            if (data.consents && data.consents[key] !== undefined) {
                                this.consents[key].enabled = data.consents[key].enabled;
                            }
                        });
                        
                        this.log('Loaded existing consents');
                        return true;
                    } else {
                        // 期限切れの場合はクリア
                        localStorage.removeItem(STORAGE_KEY);
                        this.log('Expired consents cleared');
                    }
                }
            } catch (error) {
                this.log('Error loading consents: ' + error.message);
                localStorage.removeItem(STORAGE_KEY);
            }
            
            return false;
        }

        /**
         * 同意状況をチェックしてバナー表示判定
         */
        _checkConsentStatus() {
            const hasValidConsent = this._loadConsents();
            
            if (!hasValidConsent && this.config.autoShow) {
                // 同意が無い場合はバナーを表示
                this.showBanner();
            } else if (hasValidConsent) {
                // 既に同意済みの場合は外部スクリプトを有効化
                this._enableConsentedServices();
            }
        }

        /**
         * CSSスタイルの作成
         */
        _createStyles() {
            const existingStyles = document.getElementById('consent-manager-styles');
            if (existingStyles) return;

            const styles = document.createElement('style');
            styles.id = 'consent-manager-styles';
            styles.textContent = `
                /* 同意バナー基本スタイル */
                #${BANNER_ID} {
                    position: fixed;
                    left: 0;
                    right: 0;
                    ${this.config.position}: 0;
                    background: ${this.config.theme === 'dark' ? '#1a1a1a' : '#ffffff'};
                    color: ${this.config.theme === 'dark' ? '#ffffff' : '#333333'};
                    border-top: ${this.config.position === 'bottom' ? '1px solid #ddd' : 'none'};
                    border-bottom: ${this.config.position === 'top' ? '1px solid #ddd' : 'none'};
                    box-shadow: 0 ${this.config.position === 'bottom' ? '-2px' : '2px'} 10px rgba(0,0,0,0.1);
                    z-index: 999999;
                    padding: 20px;
                    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
                    font-size: 14px;
                    line-height: 1.5;
                    display: none;
                    animation: slideIn${this.config.position === 'bottom' ? 'Up' : 'Down'} 0.3s ease-out;
                }

                @keyframes slideInUp {
                    from { transform: translateY(100%); }
                    to { transform: translateY(0); }
                }

                @keyframes slideInDown {
                    from { transform: translateY(-100%); }
                    to { transform: translateY(0); }
                }

                #${BANNER_ID} .consent-banner-content {
                    max-width: 1200px;
                    margin: 0 auto;
                    display: flex;
                    align-items: center;
                    justify-content: space-between;
                    flex-wrap: wrap;
                    gap: 20px;
                }

                #${BANNER_ID} .consent-banner-text {
                    flex: 1;
                    min-width: 300px;
                }

                #${BANNER_ID} .consent-banner-title {
                    font-weight: 600;
                    margin-bottom: 8px;
                    color: ${this.config.theme === 'dark' ? '#ffffff' : '#1a1a1a'};
                }

                #${BANNER_ID} .consent-banner-description {
                    margin-bottom: 12px;
                }

                #${BANNER_ID} .consent-banner-links a {
                    color: #0066cc;
                    text-decoration: none;
                    margin-right: 15px;
                }

                #${BANNER_ID} .consent-banner-links a:hover {
                    text-decoration: underline;
                }

                #${BANNER_ID} .consent-banner-buttons {
                    display: flex;
                    gap: 10px;
                    flex-wrap: wrap;
                }

                #${BANNER_ID} .consent-btn {
                    padding: 12px 24px;
                    border: none;
                    border-radius: 6px;
                    font-size: 14px;
                    font-weight: 600;
                    cursor: pointer;
                    transition: all 0.2s ease;
                    white-space: nowrap;
                }

                #${BANNER_ID} .consent-btn-primary {
                    background: #00B900;
                    color: white;
                }

                #${BANNER_ID} .consent-btn-primary:hover {
                    background: #00A000;
                }

                #${BANNER_ID} .consent-btn-secondary {
                    background: transparent;
                    color: ${this.config.theme === 'dark' ? '#ffffff' : '#333333'};
                    border: 1px solid #ddd;
                }

                #${BANNER_ID} .consent-btn-secondary:hover {
                    background: ${this.config.theme === 'dark' ? '#333333' : '#f5f5f5'};
                }

                #${BANNER_ID} .consent-btn-settings {
                    background: transparent;
                    color: #666;
                    border: 1px solid #ccc;
                }

                #${BANNER_ID} .consent-btn-settings:hover {
                    background: #f8f8f8;
                }

                /* モーダル */
                #${MODAL_ID} {
                    position: fixed;
                    top: 0;
                    left: 0;
                    width: 100%;
                    height: 100%;
                    background: rgba(0, 0, 0, 0.5);
                    z-index: 1000000;
                    display: none;
                    align-items: center;
                    justify-content: center;
                    padding: 20px;
                }

                #${MODAL_ID} .consent-modal-content {
                    background: white;
                    border-radius: 12px;
                    max-width: 600px;
                    width: 100%;
                    max-height: 80vh;
                    overflow-y: auto;
                    box-shadow: 0 20px 40px rgba(0,0,0,0.2);
                    animation: modalSlideIn 0.3s ease-out;
                }

                @keyframes modalSlideIn {
                    from {
                        opacity: 0;
                        transform: scale(0.9) translateY(20px);
                    }
                    to {
                        opacity: 1;
                        transform: scale(1) translateY(0);
                    }
                }

                #${MODAL_ID} .consent-modal-header {
                    padding: 24px;
                    border-bottom: 1px solid #eee;
                    position: relative;
                }

                #${MODAL_ID} .consent-modal-title {
                    font-size: 20px;
                    font-weight: 600;
                    margin: 0;
                    color: #1a1a1a;
                }

                #${MODAL_ID} .consent-modal-close {
                    position: absolute;
                    top: 24px;
                    right: 24px;
                    background: none;
                    border: none;
                    font-size: 24px;
                    cursor: pointer;
                    color: #666;
                    padding: 0;
                    width: 30px;
                    height: 30px;
                    display: flex;
                    align-items: center;
                    justify-content: center;
                }

                #${MODAL_ID} .consent-modal-body {
                    padding: 24px;
                }

                #${MODAL_ID} .consent-category {
                    border: 1px solid #e0e0e0;
                    border-radius: 8px;
                    margin-bottom: 16px;
                    overflow: hidden;
                }

                #${MODAL_ID} .consent-category-header {
                    padding: 16px;
                    background: #f8f9fa;
                    display: flex;
                    align-items: center;
                    justify-content: space-between;
                }

                #${MODAL_ID} .consent-category-info {
                    flex: 1;
                }

                #${MODAL_ID} .consent-category-name {
                    font-weight: 600;
                    margin-bottom: 4px;
                }

                #${MODAL_ID} .consent-category-description {
                    font-size: 13px;
                    color: #666;
                }

                #${MODAL_ID} .consent-toggle {
                    position: relative;
                    width: 50px;
                    height: 24px;
                    background: #ccc;
                    border-radius: 12px;
                    cursor: pointer;
                    transition: background 0.2s ease;
                }

                #${MODAL_ID} .consent-toggle.enabled {
                    background: #00B900;
                }

                #${MODAL_ID} .consent-toggle.disabled {
                    background: #ccc;
                    cursor: not-allowed;
                }

                #${MODAL_ID} .consent-toggle::after {
                    content: '';
                    position: absolute;
                    top: 2px;
                    left: 2px;
                    width: 20px;
                    height: 20px;
                    background: white;
                    border-radius: 50%;
                    transition: transform 0.2s ease;
                }

                #${MODAL_ID} .consent-toggle.enabled::after {
                    transform: translateX(26px);
                }

                #${MODAL_ID} .consent-modal-footer {
                    padding: 24px;
                    border-top: 1px solid #eee;
                    display: flex;
                    gap: 12px;
                    justify-content: flex-end;
                }

                /* レスポンシブ対応 */
                @media (max-width: 768px) {
                    #${BANNER_ID} .consent-banner-content {
                        flex-direction: column;
                        align-items: stretch;
                    }

                    #${BANNER_ID} .consent-banner-buttons {
                        justify-content: stretch;
                    }

                    #${BANNER_ID} .consent-btn {
                        flex: 1;
                        text-align: center;
                    }

                    #${MODAL_ID} {
                        padding: 10px;
                    }

                    #${MODAL_ID} .consent-modal-content {
                        max-height: 90vh;
                    }
                }

                /* 外部送信通知バッジ */
                .external-data-badge {
                    display: inline-block;
                    background: #ff6b35;
                    color: white;
                    font-size: 11px;
                    padding: 2px 6px;
                    border-radius: 3px;
                    margin-left: 8px;
                    font-weight: 600;
                }
            `;

            document.head.appendChild(styles);
        }

        /**
         * 同意バナーの作成
         */
        _createBanner() {
            if (document.getElementById(BANNER_ID)) return;

            const banner = document.createElement('div');
            banner.id = BANNER_ID;
            banner.innerHTML = `
                <div class="consent-banner-content">
                    <div class="consent-banner-text">
                        <div class="consent-banner-title">
                            Cookieとデータ利用について
                            <span class="external-data-badge">外部送信あり</span>
                        </div>
                        <div class="consent-banner-description">
                            当サイトではCookieや外部AI処理によるデータ送信を行います。継続利用には同意が必要です。
                        </div>
                        <div class="consent-banner-links">
                            <a href="${this.config.privacyPolicyUrl}" target="_blank">プライバシーポリシー</a>
                            <a href="${this.config.cookiePolicyUrl}" target="_blank">Cookie利用について</a>
                            <a href="${this.config.termsUrl}" target="_blank">利用規約</a>
                        </div>
                    </div>
                    <div class="consent-banner-buttons">
                        <button type="button" class="consent-btn consent-btn-secondary" data-action="decline">
                            必須のみ
                        </button>
                        <button type="button" class="consent-btn consent-btn-settings" data-action="settings">
                            設定
                        </button>
                        <button type="button" class="consent-btn consent-btn-primary" data-action="accept-all">
                            すべて同意
                        </button>
                    </div>
                </div>
            `;

            document.body.appendChild(banner);
            this.bannerElement = banner;
        }

        /**
         * 同意設定モーダルの作成
         */
        _createModal() {
            if (document.getElementById(MODAL_ID)) return;

            const modal = document.createElement('div');
            modal.id = MODAL_ID;
            
            let categoriesHtml = '';
            Object.entries(this.consents).forEach(([key, category]) => {
                categoriesHtml += `
                    <div class="consent-category">
                        <div class="consent-category-header">
                            <div class="consent-category-info">
                                <div class="consent-category-name">${category.name}</div>
                                <div class="consent-category-description">${category.description}</div>
                            </div>
                            <div class="consent-toggle ${category.enabled ? 'enabled' : 'disabled'} ${category.required ? 'disabled' : ''}" 
                                 data-category="${key}" 
                                 ${category.required ? 'data-required="true"' : ''}></div>
                        </div>
                    </div>
                `;
            });

            modal.innerHTML = `
                <div class="consent-modal-content">
                    <div class="consent-modal-header">
                        <h2 class="consent-modal-title">プライバシー設定</h2>
                        <button type="button" class="consent-modal-close" data-action="close-modal">&times;</button>
                    </div>
                    <div class="consent-modal-body">
                        <p>以下の設定でCookieの利用と外部送信についてご選択ください。</p>
                        ${categoriesHtml}
                        <div style="margin-top: 20px; padding: 16px; background: #fff3cd; border-radius: 6px; font-size: 13px;">
                            <strong>外部送信について:</strong><br>
                            AI応答生成のため、お客様の質問内容をOpenAI社等の外部サービスに送信します。
                            送信される情報は匿名化され、個人を特定する情報は含まれません。
                        </div>
                    </div>
                    <div class="consent-modal-footer">
                        <button type="button" class="consent-btn consent-btn-secondary" data-action="save-settings">
                            設定を保存
                        </button>
                        <button type="button" class="consent-btn consent-btn-primary" data-action="accept-all-modal">
                            すべて同意
                        </button>
                    </div>
                </div>
            `;

            document.body.appendChild(modal);
            this.modalElement = modal;
        }

        /**
         * イベントリスナーの設定
         */
        _setupEventListeners() {
            // バナーボタンのクリック
            if (this.bannerElement) {
                this.bannerElement.addEventListener('click', (e) => {
                    const action = e.target.getAttribute('data-action');
                    if (action) {
                        this._handleBannerAction(action);
                    }
                });
            }

            // モーダルのクリック
            if (this.modalElement) {
                this.modalElement.addEventListener('click', (e) => {
                    const action = e.target.getAttribute('data-action');
                    const category = e.target.getAttribute('data-category');
                    
                    if (action) {
                        this._handleModalAction(action);
                    } else if (category && e.target.classList.contains('consent-toggle')) {
                        this._toggleConsentCategory(category);
                    } else if (e.target === this.modalElement) {
                        // モーダル外クリックで閉じる
                        this.hideModal();
                    }
                });
            }

            // ESCキーでモーダルを閉じる
            document.addEventListener('keydown', (e) => {
                if (e.key === 'Escape' && this.modalElement.style.display === 'flex') {
                    this.hideModal();
                }
            });
        }

        /**
         * バナーアクションの処理
         */
        _handleBannerAction(action) {
            switch (action) {
                case 'accept-all':
                    this._acceptAllConsents();
                    break;
                case 'decline':
                    this._declineOptionalConsents();
                    break;
                case 'settings':
                    this.showModal();
                    break;
            }
        }

        /**
         * モーダルアクションの処理
         */
        _handleModalAction(action) {
            switch (action) {
                case 'close-modal':
                    this.hideModal();
                    break;
                case 'save-settings':
                    this._saveConsentSettings();
                    break;
                case 'accept-all-modal':
                    this._acceptAllConsents();
                    break;
            }
        }

        /**
         * 同意カテゴリのトグル
         */
        _toggleConsentCategory(category) {
            if (this.consents[category] && !this.consents[category].required) {
                this.consents[category].enabled = !this.consents[category].enabled;
                this._updateModalToggle(category);
            }
        }

        /**
         * モーダルトグルの更新
         */
        _updateModalToggle(category) {
            const toggle = this.modalElement.querySelector(`[data-category="${category}"]`);
            if (toggle) {
                toggle.classList.toggle('enabled', this.consents[category].enabled);
            }
        }

        /**
         * すべての同意を受け入れ
         */
        _acceptAllConsents() {
            Object.keys(this.consents).forEach(key => {
                this.consents[key].enabled = true;
            });
            
            this._saveAndProcessConsents();
        }

        /**
         * オプションの同意を拒否（必須のみ）
         */
        _declineOptionalConsents() {
            Object.keys(this.consents).forEach(key => {
                this.consents[key].enabled = this.consents[key].required;
            });
            
            this._saveAndProcessConsents();
        }

        /**
         * 現在の設定を保存
         */
        _saveConsentSettings() {
            this._saveAndProcessConsents();
        }

        /**
         * 同意を保存して処理
         */
        async _saveAndProcessConsents() {
            try {
                // ローカルストレージに保存
                const consentData = {
                    consents: this.consents,
                    timestamp: new Date().toISOString(),
                    expires: new Date(Date.now() + this.config.expiryDays * 24 * 60 * 60 * 1000).toISOString(),
                    policyVersion: this.config.policyVersion,
                    tosVersion: this.config.tosVersion
                };
                
                localStorage.setItem(STORAGE_KEY, JSON.stringify(consentData));

                // サーバーに送信
                await this._submitConsentToServer(consentData);

                // UI更新
                this.hideBanner();
                this.hideModal();

                // 同意済みサービスを有効化
                this._enableConsentedServices();

                // コールバック実行
                this._executeCallbacks('onConsentGiven', this.consents);

                this.log('Consent settings saved successfully');

            } catch (error) {
                this.log('Error saving consent settings: ' + error.message);
                alert('同意設定の保存中にエラーが発生しました。もう一度お試しください。');
            }
        }

        /**
         * サーバーに同意データを送信
         */
        async _submitConsentToServer(consentData) {
            const payload = {
                user_id: this._generateUserID(),
                consented_at: consentData.timestamp,
                policy_version: consentData.policyVersion,
                tos_version: consentData.tosVersion,
                consents: {
                    privacy_consent: consentData.consents.necessary.enabled,
                    external_data_consent: consentData.consents.external.enabled,
                    analytics_consent: consentData.consents.analytics.enabled,
                    marketing_consent: consentData.consents.marketing.enabled
                },
                user_agent: navigator.userAgent,
                ip_address: await this._getClientIP(),
                metadata: {
                    consent_method: 'web_banner',
                    page_url: window.location.href,
                    referrer: document.referrer
                }
            };

            const response = await fetch(this.config.apiEndpoint + '/submit', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify(payload)
            });

            if (!response.ok) {
                throw new Error(`Server response: ${response.status}`);
            }

            const result = await response.json();
            this.log('Consent submitted to server: ' + result.consent_id);
            
            return result;
        }

        /**
         * 同意済みサービスの有効化
         */
        _enableConsentedServices() {
            // Google Analytics
            if (this.consents.analytics.enabled) {
                this._enableGoogleAnalytics();
            }

            // マーケティングツール
            if (this.consents.marketing.enabled) {
                this._enableMarketingTools();
            }

            // 外部AI処理
            if (this.consents.external.enabled) {
                this._enableExternalAI();
            }

            this.log('Consented services enabled');
        }

        /**
         * Google Analytics有効化
         */
        _enableGoogleAnalytics() {
            if (window.gtag) {
                window.gtag('consent', 'update', {
                    'analytics_storage': 'granted'
                });
                this.log('Google Analytics enabled');
            }
        }

        /**
         * マーケティングツール有効化
         */
        _enableMarketingTools() {
            if (window.gtag) {
                window.gtag('consent', 'update', {
                    'ad_storage': 'granted',
                    'ad_user_data': 'granted',
                    'ad_personalization': 'granted'
                });
                this.log('Marketing tools enabled');
            }
        }

        /**
         * 外部AI処理有効化
         */
        _enableExternalAI() {
            // AIチャット機能の有効化
            window.AI_PROCESSING_ENABLED = true;
            
            // カスタムイベント発火
            window.dispatchEvent(new CustomEvent('consentGranted', {
                detail: { category: 'external', enabled: true }
            }));
            
            this.log('External AI processing enabled');
        }

        // ==================================================
        // 公開メソッド
        // ==================================================

        /**
         * バナーを表示
         */
        showBanner() {
            if (this.bannerElement) {
                this.bannerElement.style.display = 'block';
                this.log('Consent banner shown');
            }
        }

        /**
         * バナーを非表示
         */
        hideBanner() {
            if (this.bannerElement) {
                this.bannerElement.style.display = 'none';
                this.log('Consent banner hidden');
            }
        }

        /**
         * モーダルを表示
         */
        showModal() {
            if (this.modalElement) {
                this.modalElement.style.display = 'flex';
                document.body.style.overflow = 'hidden';
                this.log('Consent modal shown');
            }
        }

        /**
         * モーダルを非表示
         */
        hideModal() {
            if (this.modalElement) {
                this.modalElement.style.display = 'none';
                document.body.style.overflow = '';
                this.log('Consent modal hidden');
            }
        }

        /**
         * 同意取り消し
         */
        async withdrawConsent() {
            try {
                // ローカルストレージをクリア
                localStorage.removeItem(STORAGE_KEY);

                // サーバーに取り消し通知
                await fetch(this.config.apiEndpoint + '/withdraw', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json'
                    },
                    body: JSON.stringify({
                        user_id: this._generateUserID(),
                        withdrawal_reason: 'user_request'
                    })
                });

                // 同意状態をリセット
                Object.keys(this.consents).forEach(key => {
                    this.consents[key].enabled = this.consents[key].required;
                });

                // バナーを再表示
                this.showBanner();

                // コールバック実行
                this._executeCallbacks('onConsentWithdrawn');

                this.log('Consent withdrawn successfully');

            } catch (error) {
                this.log('Error withdrawing consent: ' + error.message);
                throw error;
            }
        }

        /**
         * 現在の同意状況を取得
         */
        getConsentStatus() {
            return { ...this.consents };
        }

        /**
         * 特定カテゴリの同意状況を確認
         */
        hasConsent(category) {
            return this.consents[category] && this.consents[category].enabled;
        }

        /**
         * コールバック登録
         */
        on(event, callback) {
            if (this.callbacks[event]) {
                this.callbacks[event].push(callback);
            }
        }

        // ==================================================
        // ユーティリティメソッド
        // ==================================================

        /**
         * ユーザーID生成
         */
        _generateUserID() {
            let userId = localStorage.getItem('consent_user_id');
            if (!userId) {
                userId = 'web_' + Date.now() + '_' + Math.random().toString(36).substr(2, 9);
                localStorage.setItem('consent_user_id', userId);
            }
            return userId;
        }

        /**
         * クライアントIP取得
         */
        async _getClientIP() {
            try {
                const response = await fetch('https://api.ipify.org?format=json');
                const data = await response.json();
                return data.ip;
            } catch {
                return 'unknown';
            }
        }

        /**
         * コールバック実行
         */
        _executeCallbacks(event, data) {
            this.callbacks[event].forEach(callback => {
                try {
                    callback(data);
                } catch (error) {
                    this.log('Callback error: ' + error.message);
                }
            });
        }

        /**
         * デバッグログ
         */
        log(message) {
            if (this.config.debugMode) {
                console.log('[ConsentManager] ' + message);
            }
        }
    }

    // ==================================================
    // グローバル公開
    // ==================================================

    // シングルトンインスタンス
    const consentManager = new ConsentManager();

    // グローバルに公開
    window.ConsentManager = consentManager;

    // 自動初期化のサポート
    if (window.ConsentManagerConfig) {
        consentManager.init(window.ConsentManagerConfig);
    }

})(window, document);
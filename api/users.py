from fastapi_users.db import SQLAlchemyBaseUserTable, SQLAlchemyUserDatabase
from fastapi_users import FastAPIUsers, models
from fastapi_users.authentication import CookieTransport, AuthenticationBackend, OAuth2AuthorizationCodeBearer
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker, declarative_base
from fastapi import Depends

DATABASE_URL = "sqlite+aiosqlite:///./test.db"
Base = declarative_base()
engine = create_async_engine(DATABASE_URL, echo=True)
async_session_maker = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

class UserTable(Base, SQLAlchemyBaseUserTable):
    pass

# ユーザDBインスタンス
async def get_user_db():
    async with async_session_maker() as session:
        yield SQLAlchemyUserDatabase(session, UserTable)

# 認証 backend
cookie_transport = CookieTransport(cookie_name="auth", cookie_max_age=3600)
oauth_client_id = "（Googleコンソールで取得した値）"
oauth_client_secret = "（Googleコンソールで取得した値）"
oauth_backend = OAuth2AuthorizationCodeBearer(
    authorizationUrl="https://accounts.google.com/o/oauth2/v2/auth",
    tokenUrl="https://oauth2.googleapis.com/token",
    clientId=oauth_client_id,
    clientSecret=oauth_client_secret,
    scopes=["openid", "email", "profile"],
)
auth_backend = AuthenticationBackend(
    name="google",
    transport=cookie_transport,
    get_strategy=oauth_backend,
)

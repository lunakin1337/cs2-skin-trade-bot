"""Общие ключи состояния aiohttp-приложения (для веб-приложения и API)."""

from aiogram import Bot
from aiohttp import web

from config.settings import BotConfig
from database.repository import Repositories

CONFIG_KEY: web.AppKey[BotConfig] = web.AppKey("config", BotConfig)
REPOS_KEY: web.AppKey[Repositories] = web.AppKey("repos", Repositories)
BOT_KEY: web.AppKey[Bot] = web.AppKey("bot", Bot)
CONFIG_OVERRIDE_KEY: web.AppKey[object] = web.AppKey("config_override", object)
DB_PATH_OVERRIDE_KEY: web.AppKey[object] = web.AppKey("db_path_override", object)
